"""Pipeline plumbing: doc lifecycle, journal append-only behavior, analysis
schema normalization, JSON recovery, DB dedupe, dashboard generation."""
import json

import pytest

import src.config as config
from src.analysis.deep import normalize_analysis
from src.analysis.llm import parse_json
from src.config import Settings, Ticker
from src.db import DB
from src.valuation.models import Assumptions, run_valuation


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Redirect all writable dirs into tmp."""
    for attr in ("RESEARCH_DIR", "JOURNAL_DIR", "STATE_DIR", "DOCS_DIR"):
        monkeypatch.setattr(config, attr, tmp_path / attr.lower())
    # modules captured the values at import time — patch them too
    import src.output.research_doc  # noqa
    import src.output.journal as journal_mod
    import src.output.dashboard as dash_mod
    monkeypatch.setattr(journal_mod, "JOURNAL_DIR", tmp_path / "journal")
    monkeypatch.setattr(dash_mod, "DOCS_DIR", tmp_path / "docs")
    return tmp_path


def make_ticker(tmp_path) -> Ticker:
    t = Ticker(symbol="TEST", name="Test Corp")
    return t


# ---- research doc lifecycle ------------------------------------------

def test_bootstrap_and_template_detection(sandbox, monkeypatch):
    from src.output import research_doc as rd
    t = Ticker(symbol="TEST", name="Test Corp")
    monkeypatch.setattr(config, "RESEARCH_DIR", sandbox / "research")
    a = Assumptions(fcf_base=100, shares_out=10)
    assert rd.bootstrap(t, None, a) is True
    assert rd.thesis_is_template(t) is True          # untouched template
    thesis = t.research_dir / "thesis.md"
    thesis.write_text("# My real thesis\nQuality compounder.",
                      encoding="utf-8")
    assert rd.thesis_is_template(t) is False
    # second bootstrap must not overwrite the human's thesis
    assert rd.bootstrap(t, None, a) is False
    assert "compounder" in rd.read_thesis(t)
    loaded = rd.load_assumptions(t)
    assert loaded is not None and loaded.fcf_base == 100


def test_append_entry_newest_first(sandbox, monkeypatch):
    from src.output import research_doc as rd
    from src.analysis.scoring import ConvictionResult
    monkeypatch.setattr(config, "RESEARCH_DIR", sandbox / "research")
    t = Ticker(symbol="TEST", name="Test Corp")
    rd.bootstrap(t, None, Assumptions(fcf_base=100, shares_out=10))
    val = run_valuation(Assumptions(fcf_base=100, shares_out=10, ebit=120),
                        price=90)
    conv = ConvictionResult(score=72.0, thesis_strength=70)
    a1 = normalize_analysis({"headline": "FIRST", "thesis_impact": "neutral",
                             "thesis_strength": 70})
    a2 = normalize_analysis({"headline": "SECOND", "thesis_impact": "weakens",
                             "thesis_strength": 55})
    rd.append_entry(t, a1, val, conv, alerted=False)
    rd.append_entry(t, a2, val, conv, alerted=True)
    doc = (t.research_dir / "research.md").read_text(encoding="utf-8")
    assert doc.index("SECOND") < doc.index("FIRST")   # newest on top
    assert "ALERTED" in doc
    assert "WEAKENS" in doc


# ---- journal ---------------------------------------------------------

def test_journal_append_only_dual_format(sandbox):
    from src.output import journal
    journal.log("analysis", "TEST", {"headline": "h1",
                                     "committee_memo": "memo one",
                                     "thesis_impact": "neutral"})
    journal.log("decision", "TEST", {"action": "buy",
                                     "reasoning": "cheap vs fair value"})
    jsonl = (sandbox / "journal" / "journal.jsonl").read_text().strip().splitlines()
    assert len(jsonl) == 2
    rec = json.loads(jsonl[0])
    assert rec["kind"] == "analysis" and rec["symbol"] == "TEST"
    md_files = list((sandbox / "journal").glob("*.md"))
    assert len(md_files) == 1
    assert "memo one" in md_files[0].read_text()


# ---- analysis schema safety ------------------------------------------

def test_normalize_fills_missing_and_clamps():
    out = normalize_analysis({"thesis_strength": 250,
                              "thesis_impact": "banana"})
    assert out["thesis_strength"] == 100
    assert out["thesis_impact"] == "neutral"
    assert out["intrinsic_value_effect"]["direction"] == "none"


def test_normalize_merges_nested():
    out = normalize_analysis({"moat_assessment": {"change": "widened"}})
    assert out["moat_assessment"]["change"] == "widened"
    assert "evidence" in out["moat_assessment"]


def test_parse_json_recovers_fenced_and_wrapped():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here you go: {"a": 1} hope that helps') == {"a": 1}
    assert parse_json("not json at all")["_parse_error"] is True


# ---- db dedupe & history ---------------------------------------------

def test_db_dedupe_and_history(sandbox):
    db = DB(sandbox / "state" / "t.db")
    run = db.start_run()
    assert not db.is_seen("edgar:123")
    db.mark_seen("edgar:123", "TEST", "edgar")
    assert db.is_seen("edgar:123")
    db.add_conviction(run, "TEST", 70, 72.5, {})
    db.add_conviction(run, "TEST", 60, 61.0, {})
    hist = db.conviction_history("TEST")
    assert [h["conviction_score"] for h in hist] == [72.5, 61.0]
    assert db.last_conviction("TEST")["thesis_strength"] == 60
    db.add_valuation(run, "TEST", 100.0, 90, 110, 130, {})
    assert db.last_valuation("TEST")["fair_value_base"] == 110
    db.upsert_catalyst("TEST", "2099-01-01", "Earnings", "test")
    db.upsert_catalyst("TEST", "2099-01-01", "Earnings", "test")  # idempotent
    assert len(db.upcoming_catalysts("TEST")) == 1
    db.finish_run(run)
    db.close()


# ---- dashboard -------------------------------------------------------

def test_dashboard_generates_valid_page(sandbox):
    from src.output import dashboard
    rows = [{
        "symbol": "TEST", "name": "Test Corp", "conviction": 72.5,
        "thesis_strength": 70, "conviction_history": [65, 68, 72.5],
        "price": 90.0, "fair_low": 80.0, "fair_base": 110.0,
        "fair_high": 130.0, "upside_pct": 22.2, "last_impact": "strengthens",
        "last_memo": "Business <b>compounding</b> nicely.",  # must be escaped
        "risks": ["Customer concentration"], "catalysts":
        [{"date": "2099-01-01", "label": "Earnings"}],
        "position_value": 900.0, "thesis_needed": False,
    }, {
        "symbol": "NEWCO", "name": "New Co", "conviction": None,
        "thesis_needed": True, "conviction_history": [],
    }]
    history = [{"date": "2026-07-01", "symbol": "TEST",
                "impact": "strengthens", "headline": "Margins inflected",
                "strength": 70}]
    dashboard.generate(rows, [], history, Settings(raw={}))
    page = (sandbox / "docs" / "index.html").read_text()
    assert "TEST" in page and "NEWCO" in page
    assert "&lt;b&gt;" in page                 # HTML escaped, no injection
    assert "thesis needed" in page
    assert "Margins inflected" in page
    data = json.loads((sandbox / "docs" / "data.json").read_text())
    assert data["rows"][0]["symbol"] == "TEST"   # sorted by conviction
