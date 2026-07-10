# Monitoring

The system monitors the market for you; this page is how you monitor the system.
Total effort: ~1 minute a day, ~10 minutes a month.

## Daily (passive)
- **Telegram digest** — arrives only on material days.
- **Run failure issue** — if a run crashes, an issue labeled `run-failure`
  opens automatically in the repo. No issue = system healthy. You can also
  enable email notifications for Actions failures in your GitHub settings
  (Settings → Notifications → Actions).

## Weekly (2 minutes)
- Skim the repo's commit list: one "Research run YYYY-MM-DD" commit per
  weekday means the scheduler is alive. Click any commit to see exactly
  what changed in the research docs that day — the diff *is* the changelog.
- Glance at the dashboard's RUN stamp (top-right) — it shows the last
  successful generation time.

## Monthly (10 minutes)
- **Cost:** console.anthropic.com → Usage. Expect $3–8. If it spikes,
  check `deep_analyses` counts in the run logs and lower
  `max_deep_analyses_per_run` or triage thresholds.
- **Actions minutes:** repo Settings → Billing. ~5 min/day ≈ 110/month of
  the 2,000 free.
- **Journal review:** read this month's `journal/YYYY-MM.md` end to end.
  This is the point of the whole system — compare what you believed with
  what happened.

## Health signals in the run log
Each run prints, per ticker: items found, items material after triage,
warnings for any failed data source, and a final line:
`Run complete: ok. Deep analyses: N. Alert digest sent: true/false.`
`status=partial` in the runs table means a ticker failed but the run
continued.

## Known fragility (in honesty order)
1. **yfinance** is an unofficial API. Fields occasionally vanish. The
   code degrades gracefully, but if fundamentals are missing for a week,
   update the package version.
2. **GitHub Actions cron** can drift 5–15 minutes at busy times. Fine for
   a pre-market job scheduled 105 minutes before the open.
3. **Model deprecations**: model names live in `config/settings.yaml`;
   update the strings when Anthropic retires a model (you'll see API
   errors in the run log + a failure issue).
