# HR +EV Tracker — BetMGM Colorado

Scans MLB home run props every 10 minutes, calculates +EV vs. the market,
and sends Pushover alerts to your phone. Includes a PWA you can install
on your iPhone home screen as a dashboard.

---

## Folder structure

```
hr-ev-tracker/
├── server.py          ← Python backend (Flask + APScheduler)
├── requirements.txt
├── Procfile           ← Railway start command
├── railway.json       ← Railway config
├── templates/
│   └── index.html     ← PWA dashboard (served by Flask)
└── static/
    ├── manifest.json  ← PWA manifest
    └── sw.js          ← Service worker
```

---

## Step 1 — Deploy to Railway (free, 5 minutes)

1. Go to https://railway.app and sign up (free)
2. Click **New Project → Deploy from GitHub repo**
   - Push this folder to a GitHub repo first, OR use
     **New Project → Empty Project → Add Service → GitHub Repo**
3. In your Railway project, go to **Variables** and add:

| Variable | Value |
|---|---|
| `ODDS_API_KEY` | Your Odds API key |
| `PUSHOVER_TOKEN` | Your Pushover app token |
| `PUSHOVER_USER` | Your Pushover user key |
| `PUSHOVER_PROXY` | `https://super-art-7372.treymoslof22.workers.dev` |
| `EV_THRESHOLD` | `5.0` |
| `POLL_MINUTES` | `10` |
| `MIN_ODDS` | `-150` |

4. Railway auto-deploys. Click **Settings → Networking → Generate Domain**
   — you'll get a URL like `https://hr-ev-tracker-production.up.railway.app`

5. Visit that URL — you should see the dashboard.

---

## Step 2 — Install on iPhone as a PWA

1. Open your Railway URL in **Safari** on your iPhone
2. Tap the **Share** button (box with arrow pointing up)
3. Tap **Add to Home Screen**
4. Name it "HR EV" and tap **Add**

It now lives on your home screen like a native app. Open it anytime
to see the live dashboard. The Railway server runs 24/7 and sends
Pushover alerts whether your phone is open or not.

---

## Step 3 — Configure the PWA

1. Open the app → tap **Settings** (gear icon)
2. Enter your Railway URL (e.g. `https://hr-ev-tracker-production.up.railway.app`)
3. Tap **Save Settings**
4. Tap **Send Test Alert** — you should get a Pushover notification
5. Switch to **Dashboard** → tap **Scan Now** to run your first scan

---

## How EV is calculated

1. Fetch all HR props from BetMGM + FanDuel + DraftKings + Caesars + ESPN Bet
2. Strip vig from each competitor book to get a no-vig implied probability
3. Average those to get the market's "true probability"
4. Calculate: `EV% = TrueProb × Payout − (1 − TrueProb)`
5. If EV% ≥ threshold (default 5%), send a Pushover alert

---

## Railway free tier limits

- 500 hours/month of compute (enough for 24/7)
- Sleeps after inactivity on free plan — upgrade to Hobby ($5/mo) for
  always-on. Alternatively, use Render.com free tier which stays awake
  if you ping it every 14 minutes (set POLL_MINUTES=14).
