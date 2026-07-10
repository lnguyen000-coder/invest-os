"""Stage 2 — deep analysis. For material events only, the analyst model
reads the full thesis document, the philosophy, current fundamentals, and
the event content, then produces a structured investment-committee memo.

The output schema is the contract the rest of the system depends on:
research docs, journal, alerts, and dashboard all render from it.
"""
from __future__ import annotations

import json
from typing import Any

ANALYST_SYSTEM_TEMPLATE = """{philosophy}

---

You will receive the investor's full thesis document for one company, current
fundamentals, recent valuation, and one or more new material events with
content. Produce ONE consolidated analysis.

Respond ONLY with JSON matching this schema exactly:

{{
  "headline": "<=100 chars, the single most important takeaway",
  "what_changed": "2-4 sentences, plain English, facts only",
  "why_it_matters": "2-5 sentences connecting the change to thesis drivers",
  "thesis_impact": "strengthens" | "weakens" | "neutral",
  "thesis_impact_reasoning": "the argument, as if to an investment committee",
  "intrinsic_value_effect": {{
    "direction": "up" | "down" | "none",
    "magnitude": "none" | "small (<5%)" | "moderate (5-15%)" | "large (>15%)",
    "driver": "growth" | "margins" | "capital_intensity" | "risk" | "none",
    "explanation": "1-3 sentences"
  }},
  "management_credibility": {{
    "change": "improved" | "declined" | "unchanged",
    "evidence": "specific promise-vs-delivery observations, or 'n/a'"
  }},
  "moat_assessment": {{
    "change": "widened" | "narrowed" | "unchanged",
    "evidence": "1-3 sentences"
  }},
  "revenue_quality": {{
    "change": "improved" | "deteriorated" | "unchanged",
    "evidence": "recurring mix, organic vs acquired, pricing vs volume"
  }},
  "margin_structure": {{
    "change": "improving_structurally" | "deteriorating" | "unchanged" | "noisy",
    "evidence": "distinguish structural shifts from one-off items"
  }},
  "new_risks": ["each new risk as one sentence; empty list if none"],
  "kill_criteria_triggered": ["any thesis kill-criterion now at risk; empty if none"],
  "proposed_assumption_changes": [
    {{"field": "growth_stage1|growth_stage2|discount_rate|normalized_ev_ebit|fcf_base",
      "current": <number>, "proposed": <number>, "rationale": "1 sentence"}}
  ],
  "thesis_strength": <0-100, your overall confidence the thesis is intact>,
  "plain_english_summary": "3-6 sentences a smart friend with no finance
    background would fully understand",
  "committee_memo": "5-10 sentences. Formal reasoning: what happened, what it
    means for long-term intrinsic value, what you would do (hold conviction /
    raise / trim / investigate X), and what would prove this judgment wrong."
}}

Judgment rules:
- 'neutral' is a legitimate and common verdict. Do not inflate significance.
- Never propose assumption changes for quarterly noise; only for structural shifts.
- Anchor every claim in the provided material. If content is missing, say what
  you would need to see rather than inventing specifics.
"""


def build_analysis_prompt(symbol: str, thesis_doc: str, fundamentals: str,
                          valuation_summary: str, macro_context: str,
                          events: list[dict[str, Any]]) -> str:
    parts = [
        f"Company: {symbol}",
        f"\n=== INVESTOR'S THESIS DOCUMENT ===\n{thesis_doc}",
        f"\n=== CURRENT FUNDAMENTALS ===\n{fundamentals}",
        f"\n=== CURRENT VALUATION ===\n{valuation_summary}",
    ]
    if macro_context:
        parts.append(f"\n=== MACRO CONTEXT (secondary) ===\n{macro_context}")
    parts.append("\n=== NEW MATERIAL EVENTS ===")
    for i, ev in enumerate(events, 1):
        parts.append(f"\n--- Event {i} ({ev.get('source')}, "
                     f"{ev.get('category')}) ---")
        parts.append(f"Headline: {ev.get('headline', '')}")
        content = ev.get("content", "")
        if content:
            parts.append(f"Content:\n{content[:45000]}")
        if ev.get("triage_reason"):
            parts.append(f"Screener note: {ev['triage_reason']}")
    return "\n".join(parts)


def run_deep_analysis(llm, philosophy: str, symbol: str, thesis_doc: str,
                      fundamentals: str, valuation_summary: str,
                      macro_context: str,
                      events: list[dict[str, Any]]) -> dict[str, Any]:
    system = ANALYST_SYSTEM_TEMPLATE.format(philosophy=philosophy)
    user = build_analysis_prompt(symbol, thesis_doc, fundamentals,
                                 valuation_summary, macro_context, events)
    result = llm.analyze(system, user)
    return normalize_analysis(result)


_DEFAULT = {
    "headline": "Analysis parse failure — review raw output in journal",
    "what_changed": "", "why_it_matters": "",
    "thesis_impact": "neutral", "thesis_impact_reasoning": "",
    "intrinsic_value_effect": {"direction": "none", "magnitude": "none",
                               "driver": "none", "explanation": ""},
    "management_credibility": {"change": "unchanged", "evidence": ""},
    "moat_assessment": {"change": "unchanged", "evidence": ""},
    "revenue_quality": {"change": "unchanged", "evidence": ""},
    "margin_structure": {"change": "unchanged", "evidence": ""},
    "new_risks": [], "kill_criteria_triggered": [],
    "proposed_assumption_changes": [],
    "thesis_strength": 50,
    "plain_english_summary": "", "committee_memo": "",
}


def normalize_analysis(result: dict[str, Any]) -> dict[str, Any]:
    """Guarantee the schema so downstream renderers never KeyError."""
    out = dict(_DEFAULT)
    if result.get("_parse_error"):
        out["_raw"] = result.get("_raw", "")
        return out
    for k, v in result.items():
        if k in _DEFAULT and v is not None:
            if isinstance(_DEFAULT[k], dict) and isinstance(v, dict):
                merged = dict(_DEFAULT[k])
                merged.update(v)
                out[k] = merged
            else:
                out[k] = v
    try:
        out["thesis_strength"] = max(0, min(100, int(out["thesis_strength"])))
    except (TypeError, ValueError):
        out["thesis_strength"] = 50
    if out["thesis_impact"] not in ("strengthens", "weakens", "neutral"):
        out["thesis_impact"] = "neutral"
    return out
