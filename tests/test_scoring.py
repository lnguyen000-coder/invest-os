"""The alert engine's promise is 'only notify me when...'. These tests pin
that contract, plus the philosophy penalties in conviction scoring."""
from dataclasses import dataclass, field

from src.analysis.scoring import (compute_conviction, alert_reasons,
                                  fcf_trend)
from src.analysis.triage import rule_based_materiality
from src.config import Settings
from src.valuation.models import Assumptions, run_valuation


def settings() -> Settings:
    return Settings(raw={
        "valuation": {"max_healthy_net_debt_to_ebitda": 2.5,
                      "min_healthy_roic": 0.12},
        "alerts": {"valuation_change_threshold_pct": 10.0,
                   "price_move_threshold_pct": 5.0,
                   "insider_cluster_min_buys": 2,
                   "insider_min_value_usd": 100000},
    })


@dataclass
class FakeSnap:
    price: float | None = 100.0
    change_pct: float | None = 0.0
    total_debt: float | None = 0.0
    cash: float | None = 0.0
    ebitda: float | None = 100.0
    roic: float | None = 0.20
    fcf_history: list = field(default_factory=lambda: [80, 90, 100])

    @property
    def net_debt(self):
        if self.total_debt is None:
            return None
        return self.total_debt - (self.cash or 0)

    @property
    def net_debt_to_ebitda(self):
        nd, e = self.net_debt, self.ebitda
        if nd is None or not e:
            return None
        return nd / e


@dataclass
class FakeTx:
    insider: str
    action: str
    value: float
    role: str = "CFO"


# ---- fcf trend -------------------------------------------------------

def test_fcf_trend():
    assert fcf_trend([80, 90, 100]) == "growing"
    assert fcf_trend([100, 95, 80]) == "declining"
    assert fcf_trend([100, 101, 102]) == "flat"
    assert fcf_trend([100]) == "unknown"
    assert fcf_trend([-10, 5, 20]) == "growing"


# ---- conviction penalties -------------------------------------------

def test_leverage_penalty_applied():
    healthy = compute_conviction(70, FakeSnap(), None, settings())
    levered = compute_conviction(
        70, FakeSnap(total_debt=400.0, ebitda=100.0), None, settings())
    assert levered.score < healthy.score
    assert any("net debt/EBITDA" in a for a in levered.adjustments)


def test_low_roic_penalty():
    weak = compute_conviction(70, FakeSnap(roic=0.05), None, settings())
    assert weak.score < 70
    assert any("ROIC" in a for a in weak.adjustments)


def test_declining_fcf_penalty_and_growth_bonus():
    decl = compute_conviction(70, FakeSnap(fcf_history=[100, 90, 70]),
                              None, settings())
    grow = compute_conviction(70, FakeSnap(), None, settings())
    assert decl.score < grow.score


def test_score_clamped_0_100():
    s = compute_conviction(5, FakeSnap(total_debt=2000.0, roic=0.01,
                                       fcf_history=[100, 80, 50]),
                           None, settings())
    assert 0 <= s.score <= 100


def test_undervaluation_bonus():
    val = run_valuation(Assumptions(fcf_base=100, shares_out=10, ebit=120),
                        price=100)
    cheap_snap = FakeSnap(price=val.fair_base * 0.7)
    rich_snap = FakeSnap(price=val.fair_base * 1.5)
    cheap = compute_conviction(70, cheap_snap, val, settings())
    rich = compute_conviction(70, rich_snap, val, settings())
    assert cheap.score > rich.score


# ---- alert contract --------------------------------------------------

def test_no_alerts_when_nothing_happens():
    reasons = alert_reasons(None, None, None, FakeSnap(change_pct=1.2),
                            [], settings())
    assert reasons == []


def test_neutral_analysis_does_not_alert():
    analysis = {"thesis_impact": "neutral",
                "management_credibility": {"change": "unchanged"},
                "new_risks": [], "kill_criteria_triggered": []}
    reasons = alert_reasons(analysis, None, None, FakeSnap(), [], settings())
    assert reasons == []


def test_thesis_change_alerts():
    analysis = {"thesis_impact": "weakens", "headline": "Guidance cut",
                "management_credibility": {"change": "unchanged"},
                "new_risks": [], "kill_criteria_triggered": []}
    reasons = alert_reasons(analysis, None, None, FakeSnap(), [], settings())
    assert any("weakens" in r for r in reasons)


def test_unexplained_price_move_alerts():
    reasons = alert_reasons(None, None, None, FakeSnap(change_pct=-6.3),
                            [], settings())
    assert any("without an identified" in r for r in reasons)


def test_explained_price_move_does_not_double_alert():
    analysis = {"thesis_impact": "weakens", "headline": "Guidance cut",
                "management_credibility": {"change": "unchanged"},
                "new_risks": [], "kill_criteria_triggered": []}
    reasons = alert_reasons(analysis, None, None, FakeSnap(change_pct=-6.3),
                            [], settings())
    assert not any("without an identified" in r for r in reasons)


def test_insider_cluster_alert():
    txs = [FakeTx("Alice CEO", "buy", 250000),
           FakeTx("Bob CFO", "buy", 150000)]
    reasons = alert_reasons(None, None, None, FakeSnap(), txs, settings())
    assert any("cluster" in r for r in reasons)


def test_single_small_insider_buy_no_alert():
    txs = [FakeTx("Alice CEO", "buy", 20000)]
    reasons = alert_reasons(None, None, None, FakeSnap(), txs, settings())
    assert reasons == []


def test_valuation_shift_alert():
    prev = {"fair_value_base": 100.0}
    new = run_valuation(Assumptions(fcf_base=150, shares_out=10, ebit=120),
                        price=100)
    reasons = alert_reasons(None, prev, new, FakeSnap(), [], settings())
    assert any("Fair value moved" in r for r in reasons)


# ---- triage hard rules ----------------------------------------------

def test_10q_always_material():
    assert rule_based_materiality(
        {"source": "edgar", "form": "10-Q"}, 5.0) == 7


def test_small_price_move_is_noise():
    assert rule_based_materiality(
        {"source": "price", "change_pct": 2.0}, 5.0) == 0


def test_big_insider_buy_material():
    assert rule_based_materiality(
        {"source": "form4", "action": "buy", "value": 500000}, 5.0) == 6
