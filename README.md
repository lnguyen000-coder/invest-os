# Investment Research OS

A personal, autonomous research system for a long-term investor. It runs
every weekday before the US market opens, reads what's new on your
watchlist (SEC filings, insider Form 4s, news, price action, macro),
judges whether any of it matters to *your* thesis, updates a living
research document per company, re-runs valuations, and messages you
**only when something material changed**. No daily noise.

It is deliberately **not** a trading bot. It's an analyst that argues with
your thesis every morning so you don't have to read 10-Qs at 5 AM.

## How it thinks

1. **Your thesis is the anchor.** You write `research/<TICKER>/thesis.md`
   once — moat, drivers, kill criteria. The system reads it every run and
   never edits it.
2. **Two-stage intelligence for cost control.** A cheap model (Haiku)
   triages every new item for materiality against your thesis. Only items
   scoring ≥ 6/10 reach the expensive analyst model (Sonnet), which reads
   the actual filing text and produces a structured investment-committee
   memo: what changed, why it matters, intrinsic value effect, management
   credibility, moat, revenue quality, margin structure, new risks, kill
   criteria, and proposed valuation assumption changes.
3. **Numbers stay deterministic.** Valuation is Python math (two-stage
   DCF, earnings power value, exit multiple, reverse DCF), driven by
   `assumptions.yaml` that *you* control. The LLM proposes assumption
   changes in the research doc; only a human commits them.
4. **Philosophy is enforced in code**, not just in prompts: net debt/EBITDA
   above 2.5x and ROIC below 12% take deterministic conviction penalties;
   consistent FCF growth earns credit. See `config/philosophy.md`.
5. **Everything is auditable.** Research docs, an append-only journal
   (`journal/journal.jsonl` + monthly markdown), and the SQLite state file
   are committed back to the repo each run — git history is your audit
   trail.

## Repo map

```
config/          watchlist.yaml · settings.yaml · philosophy.md
src/
  data/          edgar.py (filings, Form 4) · market.py (yfinance) · macro.py (FRED)
  analysis/      llm.py · triage.py · deep.py · scoring.py
  valuation/     models.py (DCF, EPV, exit multiple, reverse DCF)
  output/        research_doc.py · journal.py · alerts.py · dashboard.py
  main.py        the daily pipeline
research/        <TICKER>/thesis.md · research.md · assumptions.yaml
journal/         journal.jsonl · YYYY-MM.md
state/           research.db (SQLite)
docs/            generated dashboard (GitHub Pages)
scripts/         journal_decision.py · run_local.sh
.github/         daily.yml (scheduled run) · tests.yml (CI)
tests/           36 tests: valuation math, alert contract, pipeline plumbing
```

## Daily flow

```
04:45 PT  GitHub Actions wakes up
          ├─ per ticker: snapshot → new filings/insiders/news → dedupe
          ├─ triage (Haiku) → deep analysis (Sonnet, budget-capped)
          ├─ valuation refresh → conviction score → alert decision
          ├─ research.md + journal + SQLite updated
          ├─ dashboard regenerated → GitHub Pages
          └─ ONE Telegram/email digest — only if something fired
```

## Alert contract

You get pinged only for: thesis strengthens/weakens · fair value moves
≥ 10% · management credibility change · insider buying cluster or single
buy ≥ $100k · guidance change · new risk · kill criterion at risk ·
price move ≥ 5% with no identified driver. Configurable in
`config/settings.yaml`. If nothing qualifies, you hear nothing.

## Costs

| Component | Cost |
|---|---|
| SEC EDGAR, yfinance, FRED | $0 |
| GitHub Actions (private repo, ~5 min/day) | $0 (within free 2,000 min/mo) |
| GitHub Pages dashboard | $0 |
| Telegram alerts | $0 |
| Anthropic API (10 tickers, triage+capped deep analysis) | **~$3–8/mo** |

## Setup

See [SETUP.md](SETUP.md). ~20 minutes: create repo → add secrets → enable
Pages → write your theses → trigger the first run.

## Not advice

Valuations are model outputs under stated assumptions. The system exists
to sharpen your judgment, not replace it.
