# Architecture

## Design goals
1. Autonomous: zero interaction on a normal day.
2. Near-zero cost: only the LLM API is paid.
3. Auditable: every judgment written down, versioned, timestamped.
4. Boring infrastructure: nothing to babysit, no servers, no database
   hosting, no framework churn.

## The stack, and why

| Layer | Choice | Why |
|---|---|---|
| Scheduler | GitHub Actions cron | Free, reliable enough for daily jobs, secrets management built in, logs retained |
| Compute | Ubuntu runner, Python 3.12 | Plain Python; no framework needed for a 5-minute batch job |
| Storage | Git repo (markdown + SQLite) | The research doc IS the product; git gives history, diffs, backup for free |
| Filings | SEC EDGAR official APIs | Free, canonical, includes Form 4 insider XML |
| Market data | yfinance | Free; wrapped defensively because it's unofficial |
| Macro | FRED API | Free, official, optional |
| Intelligence | Anthropic API: Haiku triage → Sonnet analysis | Two-stage design cuts cost ~10x vs analyzing everything with the big model |
| Alerts | Telegram bot (or SMTP) | Free push notifications; digest-only, never empty |
| Dashboard | Static HTML on GitHub Pages | A once-daily system needs zero client-side complexity |

Deliberate non-choices: no LangChain (two prompts don't need a
framework), no vector DB (the thesis doc fits in context), no hosted
database (SQLite in git is plenty at this scale), no Airflow (one cron).

## Data flow

```
                 ┌────────────── GitHub Actions (cron 11:45 UTC M-F) ─────────────┐
                 │                                                                 │
 SEC EDGAR ──────┤  collect → dedupe (seen_items) → triage (Haiku, rules first)   │
 yfinance  ──────┤        ↓ materiality ≥ 6                                       │
 FRED      ──────┤  deep analysis (Sonnet, reads filing text, capped/run)         │
                 │        ↓ structured JSON memo                                  │
                 │  valuation (deterministic) → conviction (philosophy penalties) │
                 │        ↓                                                       │
                 │  research/<T>/research.md · journal/ · state/research.db       │
                 │        ↓                                                       │
                 │  docs/index.html (Pages) · Telegram digest (only if non-empty) │
                 │        ↓                                                       │
                 │  git commit + push  ← the audit trail                          │
                 └─────────────────────────────────────────────────────────────────┘
```

## Key contracts

**Analysis schema** (`src/analysis/deep.py`): the JSON the analyst model
must return. `normalize_analysis()` guarantees it downstream, so renderers
never crash on a malformed LLM response.

**Alert contract** (`src/analysis/scoring.py::alert_reasons`): the only
place alert conditions live, pinned by tests. Neutral analysis → silence.

**Human/machine boundary**: `thesis.md` and `assumptions.yaml` are
human-owned (system reads, never writes after bootstrap); `research.md`,
`journal/`, `state/`, `docs/` are system-owned. The LLM can only
*propose* assumption changes.

## Failure model

- Per-ticker try/except: one ticker's outage never kills the run.
- Every external call degrades to empty/None with a logged warning.
- Run failure → auto-opened GitHub issue labeled `run-failure`.
- Alert delivery failure → digest printed to the Actions log (never lost).
- LLM JSON failure → normalized default (neutral) + raw text preserved.

## Cost model

Per run at 10 tickers: ~10 triage calls on metadata batches (Haiku,
tiny) + 0–6 deep analyses (Sonnet, ~15–50k input tokens when filing text
attached). Quiet days: pennies. 10-Q season days: $0.30–1.00.
`max_deep_analyses_per_run` is the hard ceiling.

## Security

Secrets only in GitHub Actions secrets / local `.env` (gitignored). The
repo contains positions and theses — keep it private. Dashboard sets
`noindex`; see SETUP.md for the Pages visibility caveat.
