# Roadmap

Shipped in v1: watchlist monitoring (EDGAR filings, Form 4 insiders, news,
price moves, macro context), two-stage LLM analysis against a personal
thesis, four-method deterministic valuation with reverse DCF, philosophy-
weighted conviction scoring, living research docs, append-only journal,
alert digest with strict no-noise contract, static dashboard, scheduled
autonomous runs, failure alerting, 36-test suite.

## v1.x — polish (near term, low effort)
- Earnings-calendar catalysts beyond yfinance (manual catalyst entries in
  a `config/catalysts.yaml`).
- Weekly digest option: one Sunday summary of the week's journal entries
  even if individually immaterial (off by default; opt-in).
- Portfolio math: cost-basis P&L and allocation drift vs. conviction rank.

## v2 — deeper reading (moderate effort)
- **Earnings call transcripts** via a paid key (FMP starter ~$20/mo or
  API Ninjas) — the biggest data gap in v1. Slot into `src/data/` and the
  existing triage flow; the analysis layer needs zero changes.
- Segment-level KPI extraction from 10-Q/10-K (revenue by segment,
  guidance tables) into `state/` for trend charts on the dashboard.
- Peer-relative view: valuation and ROIC vs. 2–3 named competitors.

## v3 — feedback loops (the interesting part)
- **Decision review reports**: quarterly auto-generated "what you said vs.
  what happened" from the journal — thesis strength trajectory vs. forward
  returns per ticker.
- Calibration tracking: when the analyst says "moderate intrinsic value
  impact," measure the realized fair-value drift; tune prompts with data.
- Backtest harness for the conviction score against subsequent 1-year
  returns (research only — this is a learning tool, not a signal).

## Explicit non-goals
Order execution, intraday anything, price prediction, portfolio
optimization math (Markowitz etc.), social sentiment feeds. The system
makes you a better reader of businesses, not a faster trader.
