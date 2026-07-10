"""Deterministic valuation engine.

Four approaches, blended into a fair-value range:
  1. Two-stage FCF DCF (base case)
  2. Reverse DCF — what growth is priced in at today's price
  3. Exit multiple (EV/EBIT at a normalized multiple)
  4. Earnings Power Value — value assuming zero growth (the floor)

Assumptions live per-ticker in research/<SYMBOL>/assumptions.yaml so you
can override anything the auto-derivation gets wrong. The LLM analyst may
PROPOSE assumption changes after material events, but it writes them as
proposals in the research doc — a human commits them. Numbers stay
deterministic and auditable.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class Assumptions:
    fcf_base: float                 # starting FCF, absolute $
    growth_stage1: float = 0.08     # years 1-5
    growth_stage2: float = 0.05     # years 6-10
    terminal_growth: float = 0.025
    discount_rate: float = 0.09
    projection_years: int = 10
    shares_out: float = 1.0
    net_debt: float = 0.0
    ebit: float | None = None
    normalized_ev_ebit: float = 16.0
    tax_rate: float = 0.21

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValuationResult:
    dcf_per_share: float | None
    epv_per_share: float | None
    exit_multiple_per_share: float | None
    implied_growth_at_price: float | None   # reverse DCF
    fair_low: float
    fair_base: float
    fair_high: float
    components: dict[str, Any]


def dcf_value(a: Assumptions) -> float:
    """Enterprise value of projected FCF + terminal value, then to equity/share."""
    if a.discount_rate <= a.terminal_growth:
        raise ValueError("Discount rate must exceed terminal growth")
    fcf = a.fcf_base
    pv = 0.0
    half = a.projection_years // 2
    for year in range(1, a.projection_years + 1):
        g = a.growth_stage1 if year <= half else a.growth_stage2
        fcf *= (1 + g)
        pv += fcf / (1 + a.discount_rate) ** year
    terminal = fcf * (1 + a.terminal_growth) / (a.discount_rate - a.terminal_growth)
    pv += terminal / (1 + a.discount_rate) ** a.projection_years
    equity = pv - a.net_debt
    return equity / a.shares_out


def earnings_power_value(a: Assumptions) -> float | None:
    """Zero-growth value: normalized after-tax EBIT capitalized at the
    discount rate. Bruce Greenwald's floor valuation."""
    if not a.ebit or a.ebit <= 0:
        return None
    nopat = a.ebit * (1 - a.tax_rate)
    ev = nopat / a.discount_rate
    return (ev - a.net_debt) / a.shares_out


def exit_multiple_value(a: Assumptions) -> float | None:
    """Year-5 EBIT at a normalized multiple, discounted back."""
    if not a.ebit or a.ebit <= 0:
        return None
    ebit5 = a.ebit * (1 + a.growth_stage1) ** 5
    ev5 = ebit5 * a.normalized_ev_ebit
    pv = ev5 / (1 + a.discount_rate) ** 5
    return (pv - a.net_debt) / a.shares_out


def implied_growth(a: Assumptions, price: float,
                   lo: float = -0.20, hi: float = 0.40,
                   tol: float = 1e-4) -> float | None:
    """Reverse DCF: solve for the single-stage growth (both stages equal)
    that makes DCF value == current price. Bisection."""
    if price <= 0 or a.fcf_base <= 0:
        return None

    def value_at(g: float) -> float:
        trial = Assumptions(**{**a.to_dict(),
                               "growth_stage1": g, "growth_stage2": g})
        return dcf_value(trial)

    f_lo, f_hi = value_at(lo) - price, value_at(hi) - price
    if f_lo * f_hi > 0:
        return None  # price outside solvable range
    for _ in range(80):
        mid = (lo + hi) / 2
        f_mid = value_at(mid) - price
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def run_valuation(a: Assumptions, price: float | None) -> ValuationResult:
    dcf = None
    if a.fcf_base and a.fcf_base > 0:
        dcf = dcf_value(a)
    epv = earnings_power_value(a)
    exit_v = exit_multiple_value(a)
    growth = implied_growth(a, price) if (price and a.fcf_base > 0) else None

    candidates = [v for v in (dcf, epv, exit_v) if v is not None and v > 0]
    if candidates:
        # Base = weighted toward DCF; low = min (usually EPV); high = max.
        if dcf is not None:
            others = [v for v in candidates if v != dcf]
            base = dcf * 0.6 + (sum(others) / len(others)) * 0.4 if others else dcf
        else:
            base = sum(candidates) / len(candidates)
        low, high = min(candidates), max(candidates)
    else:
        low = base = high = 0.0

    return ValuationResult(
        dcf_per_share=dcf,
        epv_per_share=epv,
        exit_multiple_per_share=exit_v,
        implied_growth_at_price=growth,
        fair_low=low, fair_base=base, fair_high=high,
        components={
            "assumptions": a.to_dict(),
            "dcf": dcf, "epv": epv, "exit_multiple": exit_v,
            "implied_growth": growth, "price_at_calc": price,
        },
    )


def derive_default_assumptions(snapshot, settings) -> Assumptions:
    """Bootstrap sensible assumptions from live fundamentals. Written to
    research/<SYMBOL>/assumptions.yaml on first run for the human to tune."""
    rf = settings.get("valuation", "risk_free_rate", default=0.042)
    erp = settings.get("valuation", "equity_risk_premium", default=0.05)
    beta = snapshot.beta if snapshot.beta and 0.3 < snapshot.beta < 3 else 1.0
    discount = max(0.07, rf + beta * erp)

    hist = snapshot.fcf_history
    growth = 0.06
    if len(hist) >= 3 and hist[0] > 0 and hist[-1] > 0:
        years = len(hist) - 1
        cagr = (hist[-1] / hist[0]) ** (1 / years) - 1
        growth = max(-0.05, min(0.20, cagr))  # clamp to sane band

    return Assumptions(
        fcf_base=float(snapshot.fcf or (hist[-1] if hist else 0) or 0),
        growth_stage1=round(growth, 4),
        growth_stage2=round(max(0.02, growth * 0.6), 4),
        terminal_growth=settings.get("valuation", "terminal_growth", default=0.025),
        discount_rate=round(discount, 4),
        projection_years=settings.get("valuation", "projection_years", default=10),
        shares_out=float(snapshot.shares_out or 1),
        net_debt=float(snapshot.net_debt or 0),
        ebit=float(snapshot.ebit) if snapshot.ebit else None,
    )
