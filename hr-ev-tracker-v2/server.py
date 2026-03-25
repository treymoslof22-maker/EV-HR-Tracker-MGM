import os
import time
import logging
import requests
from datetime import datetime
from flask import Flask, jsonify
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ── Config from environment variables ────────────────────────────────────────
ODDS_API_KEY     = os.environ.get("ODDS_API_KEY", "")
PUSHOVER_TOKEN   = os.environ.get("PUSHOVER_TOKEN", "")
PUSHOVER_USER    = os.environ.get("PUSHOVER_USER", "")
PUSHOVER_PROXY   = os.environ.get("PUSHOVER_PROXY", "https://super-art-7372.treymoslof22.workers.dev")
EV_THRESHOLD     = float(os.environ.get("EV_THRESHOLD", "5.0"))   # percent
POLL_MINUTES     = int(os.environ.get("POLL_MINUTES", "10"))
MIN_ODDS         = float(os.environ.get("MIN_ODDS", "-150"))

# ── In-memory state (reset on restart) ───────────────────────────────────────
state = {
    "last_scan": None,
    "bets": [],
    "ev_bets": [],
    "alerts_sent": 0,
    "scans_run": 0,
    "api_remaining": "?",
    "alerted_keys": set(),
    "errors": [],
}

# ── Math helpers ─────────────────────────────────────────────────────────────
def american_to_decimal(odds):
    odds = float(odds)
    return 1 + odds / 100 if odds > 0 else 1 + 100 / abs(odds)

def american_to_implied(odds):
    odds = float(odds)
    return 100 / (odds + 100) if odds > 0 else abs(odds) / (abs(odds) + 100)

def calc_ev(betmgm_odds, true_prob):
    payout = american_to_decimal(betmgm_odds) - 1
    return true_prob * payout - (1 - true_prob)

def avg_american(implied_probs):
    avg = sum(implied_probs) / len(implied_probs)
    if avg <= 0 or avg >= 1:
        return 0
    return round(-avg / (1 - avg) * 100 if avg >= 0.5 else (1 - avg) / avg * 100)

# ── Pushover ─────────────────────────────────────────────────────────────────
def send_pushover(title, message):
    if not PUSHOVER_TOKEN or not PUSHOVER_USER:
        log.warning("Pushover keys not set, skipping alert.")
        return False
    try:
        url = PUSHOVER_PROXY if PUSHOVER_PROXY else "https://api.pushover.net/1/messages.json"
        res = requests.post(url, data={
            "token":   PUSHOVER_TOKEN,
            "user":    PUSHOVER_USER,
            "title":   title,
            "message": message,
            "priority": "1",
            "sound":   "cashregister",
        }, timeout=10)
        data = res.json()
        if data.get("status") == 1:
            state["alerts_sent"] += 1
            log.info(f"Pushover sent: {title}")
            return True
        else:
            log.error(f"Pushover error: {data}")
            return False
    except Exception as e:
        log.error(f"Pushover exception: {e}")
        return False

# ── Core scan logic ───────────────────────────────────────────────────────────
def run_scan():
    if not ODDS_API_KEY:
        log.warning("No ODDS_API_KEY set, skipping scan.")
        return

    log.info("Starting HR odds scan...")
    try:
        resp = requests.get(
            "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/",
            params={
                "apiKey":      ODDS_API_KEY,
                "regions":     "us",
                "markets":     "batter_home_runs",
                "oddsFormat":  "american",
                "bookmakers":  "betmgm,fanduel,draftkings,pointsbet,caesars,espnbet",
            },
            timeout=20
        )
        state["api_remaining"] = resp.headers.get("x-requests-remaining", "?")
        resp.raise_for_status()
        games = resp.json()
    except Exception as e:
        msg = f"Odds API error: {e}"
        log.error(msg)
        state["errors"].append({"time": now_str(), "msg": msg})
        return

    state["scans_run"] += 1
    all_bets = []

    for game in games:
        betmgm = next((b for b in (game.get("bookmakers") or [])
                       if b["key"] == "betmgm"), None)
        if not betmgm:
            continue

        other_books = [b for b in (game.get("bookmakers") or [])
                       if b["key"] != "betmgm"]

        hr_market = next((m for m in (betmgm.get("markets") or [])
                          if m["key"] == "batter_home_runs"), None)
        if not hr_market:
            continue

        for outcome in hr_market.get("outcomes") or []:
            player = outcome.get("description") or outcome.get("name", "?")
            betmgm_odds = float(outcome["price"])

            if betmgm_odds < MIN_ODDS:
                continue

            # Collect implied probs from other books
            market_probs = []
            for book in other_books:
                mkt = next((m for m in (book.get("markets") or [])
                            if m["key"] == "batter_home_runs"), None)
                if not mkt:
                    continue
                o = next((x for x in (mkt.get("outcomes") or [])
                          if (x.get("description") or x.get("name")) == player), None)
                if o:
                    market_probs.append(american_to_implied(float(o["price"])))

            if len(market_probs) < 2:
                continue

            avg_vig_prob = sum(market_probs) / len(market_probs)
            true_prob = avg_vig_prob / (1 + (avg_vig_prob - 0.5) * 0.05)
            betmgm_implied = american_to_implied(betmgm_odds)
            ev = calc_ev(betmgm_odds, true_prob)
            ev_pct = ev * 100
            market_avg_odds = avg_american(market_probs)
            is_positive = ev_pct >= EV_THRESHOLD

            bet = {
                "player":          player,
                "game":            f"{game.get('away_team','?')} @ {game.get('home_team','?')}",
                "betmgm_odds":     betmgm_odds,
                "market_avg_odds": market_avg_odds,
                "betmgm_implied":  round(betmgm_implied * 100, 1),
                "true_prob":       round(true_prob * 100, 1),
                "ev_pct":          round(ev_pct, 2),
                "is_positive":     is_positive,
                "key":             f"{player}-{betmgm_odds}-{game.get('id','')}",
                "scanned_at":      now_str(),
            }
            all_bets.append(bet)

    all_bets.sort(key=lambda b: b["ev_pct"], reverse=True)
    state["bets"] = all_bets
    state["ev_bets"] = [b for b in all_bets if b["is_positive"]]
    state["last_scan"] = now_str()

    log.info(f"Scan complete: {len(all_bets)} players, {len(state['ev_bets'])} +EV")

    # Send alerts for new +EV bets
    for bet in state["ev_bets"]:
        if bet["key"] not in state["alerted_keys"]:
            state["alerted_keys"].add(bet["key"])
            msg = (
                f"⚾ {bet['player']}\n"
                f"{bet['game']}\n"
                f"BetMGM: {'+' if bet['betmgm_odds'] > 0 else ''}{int(bet['betmgm_odds'])}\n"
                f"True Prob: {bet['true_prob']}%\n"
                f"EV: +{bet['ev_pct']}%\n"
                f"Bet now on BetMGM Colorado!"
            )
            send_pushover(f"⚾ +EV HR: {bet['player']}", msg)

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ── API Routes ────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    from flask import render_template
    return render_template("index.html")

@app.route("/api/status")
def api_status():
    return jsonify({
        "last_scan":      state["last_scan"],
        "scans_run":      state["scans_run"],
        "alerts_sent":    state["alerts_sent"],
        "api_remaining":  state["api_remaining"],
        "ev_count":       len(state["ev_bets"]),
        "total_players":  len(state["bets"]),
        "ev_threshold":   EV_THRESHOLD,
        "poll_minutes":   POLL_MINUTES,
    })

@app.route("/api/bets")
def api_bets():
    return jsonify(state["bets"])

@app.route("/api/ev")
def api_ev():
    return jsonify(state["ev_bets"])

@app.route("/api/scan", methods=["POST"])
def api_scan():
    run_scan()
    return jsonify({"ok": True, "bets": len(state["bets"]), "ev": len(state["ev_bets"])})

@app.route("/api/test-alert", methods=["POST"])
def api_test_alert():
    ok = send_pushover(
        "⚾ HR +EV Tracker — Test",
        "Your tracker is live and running on Railway. You'll receive alerts like this when BetMGM Colorado has +EV HR props."
    )
    return jsonify({"ok": ok})

# ── Scheduler ─────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler()
scheduler.add_job(run_scan, "interval", minutes=POLL_MINUTES, id="scan")
scheduler.start()

if __name__ == "__main__":
    log.info(f"Starting HR +EV Tracker — polling every {POLL_MINUTES} min, threshold {EV_THRESHOLD}%")
    run_scan()  # immediate first scan
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
