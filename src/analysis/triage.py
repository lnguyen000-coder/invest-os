"""Stage 1 — triage. A cheap model reads every new item's metadata against
the thesis summary and scores materiality 0-10. Only items scoring >= 6
get the expensive deep-analysis treatment. This is where 'do not send me
daily summaries that contain nothing useful' is enforced.
"""
from __future__ import annotations

import json
from typing import Any

TRIAGE_SYSTEM = """You are the first-pass screener for a long-term investor's
research system. You will receive: a one-paragraph thesis summary for a company,
and a batch of new items (filings, news headlines, insider trades, price moves).

Score each item's MATERIALITY to the long-term (5+ year) thesis on a 0-10 scale:
  0-2: noise (routine filings, price chatter, macro commentary, PR fluff)
  3-5: worth logging, not worth deep analysis (minor product news, small insider sales)
  6-7: material — likely affects a thesis driver (guidance change, margin inflection,
       competitive move, sizable insider buying, new risk disclosure)
  8-10: thesis-critical (guidance cut/raise, CEO change, major acquisition,
        accounting restatement, activist stake, regulatory action)

Rules:
- A 10-K or 10-Q is ALWAYS at least 6 (fresh fundamentals must be reviewed).
- An 8-K is 6+ only if the described event touches earnings, guidance,
  leadership, M&A, debt, or legal/regulatory matters.
- Insider open-market BUYS by officers/directors: 6+. Routine sales: 2-4.
- Macro items: 5 max unless directly tied to a thesis driver.
- Unexplained price moves beyond the given threshold: 6.
- Be stingy. Most items are noise. The investor prefers silence to filler.

Respond ONLY with JSON:
{"items": [{"id": "<item id>", "materiality": <0-10>,
            "category": "filing|guidance|insider|news|price|risk|macro",
            "reason": "<one sentence>"}]}
"""


def build_triage_prompt(symbol: str, thesis_summary: str,
                        items: list[dict[str, Any]]) -> str:
    return (
        f"Company: {symbol}\n\n"
        f"Thesis summary:\n{thesis_summary}\n\n"
        f"New items:\n{json.dumps(items, indent=1)}"
    )


def run_triage(llm, symbol: str, thesis_summary: str,
               items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Returns {item_id: {materiality, category, reason}}."""
    if not items:
        return {}
    result = llm.triage(TRIAGE_SYSTEM,
                        build_triage_prompt(symbol, thesis_summary, items))
    out: dict[str, dict[str, Any]] = {}
    for it in result.get("items", []):
        iid = str(it.get("id", ""))
        if not iid:
            continue
        out[iid] = {
            "materiality": int(it.get("materiality", 0)),
            "category": it.get("category", "news"),
            "reason": it.get("reason", ""),
        }
    return out


# Rules that bypass the LLM entirely (deterministic materiality).
def rule_based_materiality(item: dict[str, Any],
                           price_threshold: float) -> int | None:
    """Return a materiality score if a hard rule applies, else None."""
    src = item.get("source", "")
    if src == "edgar" and item.get("form") in ("10-K", "10-Q"):
        return 7
    if src == "price":
        move = abs(float(item.get("change_pct", 0)))
        if move >= price_threshold:
            return 6
        return 0
    if src == "form4" and item.get("action") == "buy":
        if float(item.get("value", 0)) >= 100000:
            return 6
    return None
