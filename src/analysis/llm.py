"""Anthropic API wrapper with cost guardrails and defensive JSON parsing."""
from __future__ import annotations

import json
import re
from typing import Any

import anthropic

from src.config import env


class LLM:
    def __init__(self, settings):
        self.client = anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY"))
        self.triage_model = settings.get("models", "triage",
                                         default="claude-haiku-4-5-20251001")
        self.analyst_model = settings.get("models", "analyst",
                                          default="claude-sonnet-4-6")
        self.max_triage_tokens = settings.get("models", "max_triage_tokens",
                                              default=1200)
        self.max_analysis_tokens = settings.get("models", "max_analysis_tokens",
                                                default=3500)
        self.deep_budget = settings.get("models", "max_deep_analyses_per_run",
                                        default=6)
        self.deep_used = 0

    @property
    def deep_budget_left(self) -> bool:
        return self.deep_used < self.deep_budget

    def _call(self, model: str, system: str, user: str,
              max_tokens: int) -> str:
        msg = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")

    def triage(self, system: str, user: str) -> dict[str, Any]:
        raw = self._call(self.triage_model, system, user, self.max_triage_tokens)
        return parse_json(raw)

    def analyze(self, system: str, user: str) -> dict[str, Any]:
        self.deep_used += 1
        raw = self._call(self.analyst_model, system, user,
                         self.max_analysis_tokens)
        return parse_json(raw)


def parse_json(raw: str) -> dict[str, Any]:
    """LLMs occasionally wrap JSON in fences or add preamble; recover it."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.M).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {"_parse_error": True, "_raw": raw[:2000]}
