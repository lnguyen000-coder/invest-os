"""Living research documents.

research/<SYMBOL>/
  thesis.md          — YOUR thesis. Human-authored. System reads, never edits.
  research.md        — living doc. System-maintained: latest state + change log.
  assumptions.yaml   — valuation assumptions. Bootstrapped, human-tuned.

The split is deliberate: the thesis is the hypothesis, the research doc is
the evidence log. Keeping them separate prevents the system from quietly
rewriting your reasoning underneath you.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.valuation.models import Assumptions

THESIS_TEMPLATE = """# {name} ({symbol}) — Investment Thesis

> STATUS: TEMPLATE — replace every section below with your own view.
> The system will not run deep analysis until this file is edited
> (it checks for this banner).

## Thesis in one paragraph
Why does this business deserve your capital for 5+ years? What do you
believe that the market underappreciates?

## Moat
What is the durable competitive advantage, specifically? (switching costs /
network effects / brand pricing power / scale / regulation)

## Key drivers (what actually moves intrinsic value)
1. ...
2. ...
3. ...

## What I'm paying for growth
What growth/margin expectations justify the current price? Are they demanding?

## Kill criteria (what would make me sell)
1. ...
2. ...
3. ...

## Known risks
- ...

## Management scorecard
Promises made vs. delivered. Capital allocation track record.
"""

RESEARCH_HEADER = """# {name} ({symbol}) — Living Research Document
_Maintained automatically. Newest entries first. Your thesis lives in thesis.md._

"""


def bootstrap(ticker, snapshot=None, default_assumptions: Assumptions | None = None) -> bool:
    """Create research folder on first sight of a ticker. Returns True if
    anything new was created."""
    d: Path = ticker.research_dir
    created = False
    d.mkdir(parents=True, exist_ok=True)
    thesis = d / "thesis.md"
    if not thesis.exists():
        thesis.write_text(
            THESIS_TEMPLATE.format(name=ticker.name, symbol=ticker.symbol),
            encoding="utf-8")
        created = True
    doc = d / "research.md"
    if not doc.exists():
        doc.write_text(
            RESEARCH_HEADER.format(name=ticker.name, symbol=ticker.symbol),
            encoding="utf-8")
        created = True
    assumptions = d / "assumptions.yaml"
    if not assumptions.exists() and default_assumptions is not None:
        payload = default_assumptions.to_dict()
        payload["_note"] = ("Auto-derived from fundamentals on first run. "
                            "Tune these by hand; the system proposes changes "
                            "in research.md but never edits this file.")
        assumptions.write_text(yaml.safe_dump(payload, sort_keys=False),
                               encoding="utf-8")
        created = True
    return created


def thesis_is_template(ticker) -> bool:
    p = ticker.research_dir / "thesis.md"
    if not p.exists():
        return True
    return "STATUS: TEMPLATE" in p.read_text(encoding="utf-8")


def read_thesis(ticker) -> str:
    p = ticker.research_dir / "thesis.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def thesis_summary(ticker, max_chars: int = 900) -> str:
    """First meaningful chunk of the thesis for triage prompts."""
    text = read_thesis(ticker)
    text = re.sub(r"^>.*$", "", text, flags=re.M)   # drop template banner
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_chars]


def load_assumptions(ticker) -> Assumptions | None:
    p = ticker.research_dir / "assumptions.yaml"
    if not p.exists():
        return None
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data.pop("_note", None)
    valid = {k: v for k, v in data.items()
             if k in Assumptions.__dataclass_fields__}
    try:
        return Assumptions(**valid)
    except TypeError:
        return None


def append_entry(ticker, analysis: dict[str, Any], valuation,
                 conviction, alerted: bool) -> None:
    """Prepend a dated entry to research.md (newest first)."""
    doc = ticker.research_dir / "research.md"
    existing = doc.read_text(encoding="utf-8") if doc.exists() else ""
    header_end = existing.find("\n\n")
    header, body = ((existing[:header_end + 2], existing[header_end + 2:])
                    if header_end != -1 else (existing, ""))

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    impact = analysis.get("thesis_impact", "neutral").upper()
    lines = [
        f"## {date} — {analysis.get('headline', 'Update')}",
        f"**Thesis impact: {impact}** · Thesis strength: "
        f"{analysis.get('thesis_strength', '?')}/100 · Conviction: "
        f"{conviction.score if conviction else '?'}/100"
        + (" · **ALERTED**" if alerted else ""),
        "",
        f"**What changed:** {analysis.get('what_changed', '')}",
        "",
        f"**Why it matters:** {analysis.get('why_it_matters', '')}",
        "",
    ]
    ive = analysis.get("intrinsic_value_effect", {})
    lines.append(f"**Intrinsic value:** {ive.get('direction', 'none')} / "
                 f"{ive.get('magnitude', 'none')} via {ive.get('driver', 'n/a')}"
                 f" — {ive.get('explanation', '')}")
    for label, key in (("Management credibility", "management_credibility"),
                       ("Moat", "moat_assessment"),
                       ("Revenue quality", "revenue_quality"),
                       ("Margin structure", "margin_structure")):
        block = analysis.get(key, {})
        change = block.get("change", "unchanged")
        if change not in ("unchanged", "noisy"):
            lines.append(f"**{label}:** {change} — {block.get('evidence', '')}")
    if analysis.get("new_risks"):
        lines.append("**New risks:**")
        lines.extend(f"- {r}" for r in analysis["new_risks"])
    if analysis.get("kill_criteria_triggered"):
        lines.append("**⚠ Kill criteria at risk:**")
        lines.extend(f"- {k}" for k in analysis["kill_criteria_triggered"])
    if analysis.get("proposed_assumption_changes"):
        lines.append("**Proposed valuation assumption changes "
                     "(edit assumptions.yaml to accept):**")
        for p in analysis["proposed_assumption_changes"]:
            lines.append(f"- `{p.get('field')}`: {p.get('current')} → "
                         f"{p.get('proposed')} — {p.get('rationale', '')}")
    if valuation:
        lines.append("")
        lines.append(f"**Valuation:** fair value ${valuation.fair_low:,.0f} / "
                     f"**${valuation.fair_base:,.0f}** / ${valuation.fair_high:,.0f}"
                     + (f" · implied growth at price: "
                        f"{valuation.implied_growth_at_price:.1%}"
                        if valuation.implied_growth_at_price is not None else ""))
    lines.append("")
    lines.append(f"**Committee memo:** {analysis.get('committee_memo', '')}")
    lines.append("")
    lines.append(f"**Plain English:** {analysis.get('plain_english_summary', '')}")
    lines.append("\n---\n")

    doc.write_text(header + "\n".join(lines) + body, encoding="utf-8")
