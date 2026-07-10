# Setup Guide

Time: ~20 minutes. No local Python needed — everything runs on GitHub.

## 1. Create the repository

1. Create a **private** GitHub repository (e.g. `invest-os`).
2. Upload this entire project folder to it (GitHub web UI: *Add file →
   Upload files*, drag the folder contents in, commit). Or with git:
   ```bash
   git init && git add -A && git commit -m "initial"
   git remote add origin git@github.com:YOURNAME/invest-os.git
   git push -u origin main
   ```

## 2. Get your API keys

**Anthropic (required, the only paid piece):**
1. console.anthropic.com → API Keys → Create Key.
2. Add $10 of credit to start; expect $3–8/month at a 10-ticker watchlist.

**Telegram (recommended for alerts, free, 3 minutes):**
1. In Telegram, message **@BotFather** → `/newbot` → follow prompts.
   Copy the **bot token**.
2. Message your new bot anything (this opens the chat).
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and
   copy the `"chat":{"id": ...}` number — that's your **chat id**.

**FRED (optional, free):** fred.stlouisfed.org → API key, for macro context.

**Email instead of Telegram (optional):** for Gmail, create an App
Password (Google Account → Security → 2-Step Verification → App
passwords) and set `alerts.channel: email` in `config/settings.yaml` plus
the `email:` addresses.

## 3. Add secrets to the repo

Repo → **Settings → Secrets and variables → Actions → New repository
secret**. Add:

| Secret | Required |
|---|---|
| `ANTHROPIC_API_KEY` | yes |
| `TELEGRAM_BOT_TOKEN` | for Telegram alerts |
| `TELEGRAM_CHAT_ID` | for Telegram alerts |
| `FRED_API_KEY` | optional |
| `SMTP_USER`, `SMTP_PASSWORD` | only if using email |

## 4. Enable the dashboard

Repo → **Settings → Pages** → Source: *Deploy from a branch* → Branch:
`main`, folder `/docs` → Save. Your dashboard will live at
`https://YOURNAME.github.io/invest-os/`.

Note: on a free GitHub plan, Pages sites are public even for private
repos (the URL is unguessable but not access-controlled, and the page
sets `noindex`). If that bothers you, either upgrade to GitHub Pro for
private Pages, or skip Pages and open `docs/index.html` from the repo
directly — it's a self-contained file.

## 5. Personalize

1. `config/watchlist.yaml` — your tickers, positions, cost basis.
2. `config/settings.yaml` — set `edgar_user_agent` to your real
   name/email (SEC etiquette), pick alert channel, tune thresholds.
3. `config/philosophy.md` — it ships with your stated philosophy; adjust
   wording if anything reads wrong.

## 6. First run

Repo → **Actions → Morning research run → Run workflow**. First run
takes a few minutes. It will:
- create `research/<TICKER>/` folders with thesis templates and
  auto-derived `assumptions.yaml`,
- build the dashboard,
- commit everything back.

## 7. Write your theses (the important part)

Edit each `research/<TICKER>/thesis.md`, replacing the template. Delete
the `STATUS: TEMPLATE` banner line when done — **deep analysis stays
paused for a ticker until you do**, by design: the system judges new
information *against your thesis*, so there must be one.

Sanity-check each `assumptions.yaml` too; the auto-derived growth and
discount rates are starting points, not gospel.

Commit, then trigger the workflow once more. From tomorrow it runs
itself at 4:45 AM Pacific on weekdays.

## 8. Log your decisions

Whenever you buy/sell/trim/pass, record it with your reasoning:
```bash
python scripts/journal_decision.py MSFT buy "20% below base fair value, thesis intact" --price 452.10
```
(or add a `decision` line to `journal/journal.jsonl` via the GitHub web
editor if you don't run Python locally). Future-you audits past-you.

## Local runs (optional)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in keys
./scripts/run_local.sh
python -m pytest tests/
```

## Troubleshooting

- **No alerts ever:** working as intended if nothing material happened.
  Check Actions logs — each run prints items found and triage verdicts.
- **A run failed:** an issue labeled `run-failure` is opened
  automatically with a link to the log.
- **yfinance field errors:** Yahoo changes their API occasionally; the
  code degrades to `None` rather than crashing, but if fundamentals go
  missing for days, update yfinance (`pip install -U yfinance`) and bump
  it in `requirements.txt`.
- **EDGAR 403s:** your `edgar_user_agent` is missing/generic. Set a real
  contact string.
