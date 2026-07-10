"""Macro context via FRED (free API key: https://fred.stlouisfed.org/docs/api/api_key.html).

Philosophy says macro is secondary — so this only produces a compact
context block that gets appended to analysis prompts, never its own alerts
unless a series moves sharply.
"""
from __future__ import annotations

import requests

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

LABELS = {
    "DGS10": "10Y Treasury yield (%)",
    "CPIAUCSL": "CPI index",
    "UNRATE": "Unemployment rate (%)",
}


def fetch_macro_context(series_ids: list[str], api_key: str | None) -> str:
    """Returns a short plain-text macro block, or '' if unavailable."""
    if not api_key:
        return ""
    lines = []
    for sid in series_ids:
        try:
            r = requests.get(FRED_URL, params={
                "series_id": sid, "api_key": api_key, "file_type": "json",
                "sort_order": "desc", "limit": 2,
            }, timeout=20)
            r.raise_for_status()
            obs = [o for o in r.json().get("observations", [])
                   if o.get("value") not in (".", None)]
            if not obs:
                continue
            latest = obs[0]
            prev = obs[1] if len(obs) > 1 else None
            label = LABELS.get(sid, sid)
            line = f"{label}: {latest['value']} (as of {latest['date']})"
            if prev:
                line += f", prior {prev['value']}"
            lines.append(line)
        except requests.RequestException:
            continue
    return "\n".join(lines)
