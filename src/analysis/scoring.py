"""Conviction scoring + alert decisions.

Conviction (0-100) = thesis strength adjusted by quality and valuation,
with the philosophy's explicit penalties applied deterministically:
  - net debt / EBITDA above the healthy ceiling
  - ROIC below the healthy floor
  - declining FCF trend
  - valuation stretched far above fair value

Alerts fire ONLY on the user's stated conditions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConvictionResult:
    score: float
    thesis_strength: int
    adjustments: list[str] = field(default_factory=list)


def fcf_trend(fcf_history: list[float]) -> str:
    """'growing' | 'flat' | 'declining' | 'unknown' from annual FCF series."""
    h = [v for v in fcf_history if v is not None]
    if len(h) < 3:
        return "unknown"
    recent, older = h[-1], h[0]
    if older <= 0:
        return "growing" if recent > 0 else "declining"
    change = recent / older - 1
    if change > 0.10:
        return "growing"
    if change < -0.10:
        return "declining"
    return "flat"


def compute_conviction(thesis_strength: int, snapshot, valuation,
                       settings) -> ConvictionResult:
    score = float(thesis_strength)
    adj: list[str] = []

    max_leverage = settings.get("valuation", "max_healthy_net_debt_to_ebitda",
                                default=2.5)
    min_roic = settings.get("valuation", "min_healthy_roic", default=0.12)

    lev = snapshot.net_debt_to_ebitda
    if lev is not None and lev > max_leverage:
        penalty = min(20.0, (lev - max_leverage) * 8)
        score -= penalty
        adj.append(f"-{penalty:.0f}: net debt/EBITDA {lev:.1f}x exceeds "
                   f"{max_leverage}x ceiling")

    if snapshot.roic is not None and snapshot.roic < min_roic:
        penalty = min(15.0, (min_roic - snapshot.roic) * 100)
        score -= penalty
        adj.append(f"-{penalty:.0f}: ROIC {snapshot.roic:.1%} below "
                   f"{min_roic:.0%} floor")

    trend = fcf_trend(snapshot.fcf_history)
    if trend == "declining":
        score -= 10
        adj.append("-10: multi-year FCF trend is declining")
    elif trend == "growing":
        score += 5
        adj.append("+5: consistent multi-year FCF growth")

    if valuation and valuation.fair_base > 0 and snapshot.price:
        upside = valuation.fair_base / snapshot.price - 1
        if upside < -0.25:
            score -= 12
            adj.append(f"-12: price {abs(upside):.0%} above base fair value")
        elif upside > 0.20:
            score += 8
            adj.append(f"+8: price {upside:.0%} below base fair value")

    score = max(0.0, min(100.0, score))
    return ConvictionResult(score=round(score, 1),
                            thesis_strength=thesis_strength,
                            adjustments=adj)


# ---------------------------------------------------------------------
# Alert decisions — exactly the user's conditions, nothing else.
# ---------------------------------------------------------------------

def alert_reasons(analysis: dict[str, Any] | None,
                  prev_valuation, new_valuation,
                  snapshot,
                  insider_buys: list,
                  settings) -> list[str]:
    reasons: list[str] = []
    val_thresh = settings.get("alerts", "valuation_change_threshold_pct",
                              default=10.0)
    price_thresh = settings.get("alerts", "price_move_threshold_pct",
                                default=5.0)
    min_buys = settings.get("alerts", "insider_cluster_min_buys", default=2)
    min_value = settings.get("alerts", "insider_min_value_usd", default=100000)

    if analysis:
        if analysis.get("thesis_impact") in ("strengthens", "weakens"):
            reasons.append(f"Thesis {analysis['thesis_impact']}: "
                           f"{analysis.get('headline', '')}")
        cred = analysis.get("management_credibility", {}).get("change")
        if cred in ("improved", "declined"):
            reasons.append(f"Management credibility {cred}")
        if analysis.get("new_risks"):
            reasons.append(f"New risk: {analysis['new_risks'][0]}")
        if analysis.get("kill_criteria_triggered"):
            reasons.append("KILL CRITERION AT RISK: "
                           f"{analysis['kill_criteria_triggered'][0]}")
        cat_guidance = "guidance" in json_lower(analysis)
        if cat_guidance:
            reasons.append("Guidance change detected")

    if prev_valuation is not None and new_valuation is not None:
        prev_base = prev_valuation["fair_value_base"]
        if prev_base and new_valuation.fair_base:
            change = abs(new_valuation.fair_base / prev_base - 1) * 100
            if change >= val_thresh:
                direction = "up" if new_valuation.fair_base > prev_base else "down"
                reasons.append(f"Fair value moved {direction} {change:.0f}%")

    big_buys = [b for b in insider_buys
                if b.action == "buy" and b.value >= min_value]
    distinct = {b.insider for b in big_buys}
    if len(distinct) >= min_buys:
        total = sum(b.value for b in big_buys)
        reasons.append(f"Insider buying cluster: {len(distinct)} insiders, "
                       f"${total:,.0f} total")
    elif big_buys:
        b = max(big_buys, key=lambda x: x.value)
        reasons.append(f"Major insider buy: {b.insider} ({b.role}) "
                       f"${b.value:,.0f}")

    move = snapshot.change_pct
    if move is not None and abs(move) >= price_thresh:
        explained = bool(analysis and analysis.get("thesis_impact") != "neutral")
        if not explained:
            reasons.append(f"Price moved {move:+.1f}% without an identified "
                           "material driver")
    return reasons


def json_lower(d: dict[str, Any]) -> str:
    import json as _json
    try:
        return _json.dumps(d).lower()
    except (TypeError, ValueError):
        return ""
