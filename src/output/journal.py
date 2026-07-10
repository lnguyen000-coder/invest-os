"""Living investment journal — append-only.

Two mirrors of the same record:
  journal/journal.jsonl   — machine-readable, one JSON object per line
  journal/YYYY-MM.md      — human-readable monthly file

Every alert, thesis update, and system judgment lands here with the
reasoning *at the time*, so future-you can audit past-you. Entries are
never edited or deleted; corrections are new entries.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.config import JOURNAL_DIR


def log(kind: str, symbol: str, payload: dict[str, Any]) -> None:
    """kind: analysis | alert | valuation_shift | decision | system"""
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc)
    record = {
        "ts": ts.isoformat(timespec="seconds"),
        "kind": kind,
        "symbol": symbol,
        **payload,
    }
    with open(JOURNAL_DIR / "journal.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    _append_markdown(ts, kind, symbol, payload)


def _append_markdown(ts: datetime, kind: str, symbol: str,
                     payload: dict[str, Any]) -> None:
    path = JOURNAL_DIR / f"{ts.strftime('%Y-%m')}.md"
    is_new = not path.exists()
    with open(path, "a", encoding="utf-8") as f:
        if is_new:
            f.write(f"# Investment Journal — {ts.strftime('%B %Y')}\n\n")
        f.write(f"## {ts.strftime('%Y-%m-%d %H:%M UTC')} · {symbol} · {kind}\n\n")
        headline = payload.get("headline") or payload.get("summary") or ""
        if headline:
            f.write(f"**{headline}**\n\n")
        reasoning = (payload.get("committee_memo")
                     or payload.get("reasoning")
                     or payload.get("plain_english_summary") or "")
        if reasoning:
            f.write(f"{reasoning}\n\n")
        for key in ("thesis_impact", "thesis_strength", "conviction",
                    "fair_value_base", "price", "alert_reasons"):
            if key in payload and payload[key] not in (None, "", []):
                f.write(f"- {key.replace('_', ' ')}: {payload[key]}\n")
        f.write("\n---\n\n")


def log_decision(symbol: str, action: str, reasoning: str,
                 price: float | None = None) -> None:
    """For YOUR buy/sell/trim decisions — call via scripts/journal_decision.py
    so every trade has its contemporaneous reasoning on record."""
    log("decision", symbol, {
        "action": action, "reasoning": reasoning, "price": price,
    })
