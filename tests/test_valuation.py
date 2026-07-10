"""Valuation math must be exact and stable — these are the numbers you
trust with real decisions."""
import math

import pytest

from src.valuation.models import (Assumptions, dcf_value,
                                  earnings_power_value, exit_multiple_value,
                                  implied_growth, run_valuation)


def base_assumptions(**over) -> Assumptions:
    d = dict(fcf_base=100.0, growth_stage1=0.08, growth_stage2=0.05,
             terminal_growth=0.025, discount_rate=0.09,
             projection_years=10, shares_out=10.0, net_debt=0.0,
             ebit=120.0, normalized_ev_ebit=16.0)
    d.update(over)
    return Assumptions(**d)


def test_dcf_hand_calculation():
    """Verify against an independent hand calculation."""
    a = base_assumptions()
    fcf, pv = a.fcf_base, 0.0
    for yr in range(1, 11):
        g = 0.08 if yr <= 5 else 0.05
        fcf *= 1 + g
        pv += fcf / 1.09 ** yr
    terminal = fcf * 1.025 / (0.09 - 0.025)
    pv += terminal / 1.09 ** 10
    expected = pv / 10.0
    assert math.isclose(dcf_value(a), expected, rel_tol=1e-9)


def test_dcf_higher_growth_higher_value():
    lo = dcf_value(base_assumptions(growth_stage1=0.05))
    hi = dcf_value(base_assumptions(growth_stage1=0.12))
    assert hi > lo


def test_dcf_net_debt_reduces_equity_value():
    clean = dcf_value(base_assumptions(net_debt=0))
    levered = dcf_value(base_assumptions(net_debt=500))
    assert math.isclose(clean - levered, 500 / 10.0, rel_tol=1e-9)


def test_dcf_rejects_terminal_growth_above_discount():
    with pytest.raises(ValueError):
        dcf_value(base_assumptions(discount_rate=0.02, terminal_growth=0.025))


def test_epv_is_zero_growth_floor():
    a = base_assumptions()
    epv = earnings_power_value(a)
    # NOPAT 120*0.79 = 94.8; EV = 94.8/0.09 = 1053.33; /10 shares
    assert math.isclose(epv, 94.8 / 0.09 / 10, rel_tol=1e-9)
    # For a growing business, DCF should exceed the no-growth floor
    assert dcf_value(a) > epv


def test_epv_none_without_ebit():
    assert earnings_power_value(base_assumptions(ebit=None)) is None
    assert earnings_power_value(base_assumptions(ebit=-50)) is None


def test_exit_multiple():
    a = base_assumptions()
    ev5 = 120 * 1.08 ** 5 * 16
    expected = (ev5 / 1.09 ** 5 - 0) / 10
    assert math.isclose(exit_multiple_value(a), expected, rel_tol=1e-9)


def test_reverse_dcf_recovers_known_growth():
    """If the price IS the DCF at growth g, implied growth must return g."""
    g = 0.07
    a = base_assumptions(growth_stage1=g, growth_stage2=g)
    price = dcf_value(a)
    solved = implied_growth(base_assumptions(), price)
    assert solved is not None
    assert abs(solved - g) < 0.002


def test_reverse_dcf_out_of_range_returns_none():
    assert implied_growth(base_assumptions(), price=1e9) is None
    assert implied_growth(base_assumptions(fcf_base=0), price=100) is None


def test_run_valuation_blend_bounds():
    r = run_valuation(base_assumptions(), price=150.0)
    assert r.fair_low <= r.fair_base <= r.fair_high
    assert r.fair_low == min(v for v in (r.dcf_per_share, r.epv_per_share,
                                         r.exit_multiple_per_share) if v)
    assert r.components["price_at_calc"] == 150.0


def test_run_valuation_no_fcf_degrades_gracefully():
    r = run_valuation(base_assumptions(fcf_base=0, ebit=None), price=100.0)
    assert r.fair_base == 0.0
    assert r.dcf_per_share is None
