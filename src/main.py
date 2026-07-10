"""Daily pipeline. One run = one pre-market pass over the watchlist.

Per ticker:
  1. fetch snapshot, filings, insider txs, news
  2. dedupe against seen_items
  3. rule-based + LLM triage → materiality
  4. deep analysis (budget-capped) on material items
  5. deterministic valuation from assumptions.yaml
  6. conviction scoring with philosophy penalties
  7. research doc + journal + DB writes
  8. queue alerts
Then: dashboard regeneration, single alert digest (only if non-empty).

Every stage is fail-soft: one ticker's data outage never kills the run.
"""
from __future__ import annotations

import json
import traceback
from typing import Any

from src import config
from src.db import DB
from src.data.edgar import EdgarClient
from src.data import market, macro
from src.analysis.llm import LLM
from src.analysis import triage as triage_mod
from src.analysis.deep import run_deep_analysis
from src.analysis.scoring import compute_conviction, alert_reasons
from src.valuation.models import (run_valuation, derive_default_assumptions,
                                  Assumptions)
from src.output import research_doc, journal, dashboard
from src.output.alerts import AlertSink, Alert


def fundamentals_block(snap) -> str:
    lev = snap.net_debt_to_ebitda
    return "\n".join(filter(None, [
        f"Price: {snap.price}  (prev close {snap.prev_close}, "
        f"move {snap.change_pct:+.1f}%)" if snap.change_pct is not None
        else f"Price: {snap.price}",
        f"Market cap: {snap.market_cap:,}" if snap.market_cap else None,
        f"TTM revenue: {snap.revenue:,}" if snap.revenue else None,
        f"TTM FCF: {snap.fcf:,}" if snap.fcf else None,
        f"FCF history (annual, oldest→newest): "
        f"{[round(v / 1e9, 2) for v in snap.fcf_history]} $B"
        if snap.fcf_history else None,
        f"Revenue history: {[round(v / 1e9, 2) for v in snap.revenue_history]} $B"
        if snap.revenue_history else None,
        f"Gross margin history: "
        f"{[round(m, 3) for m in snap.gross_margin_history]}"
        if snap.gross_margin_history else None,
        f"Net debt / EBITDA: {lev:.2f}x" if lev is not None else None,
        f"ROIC (approx): {snap.roic:.1%}" if snap.roic is not None else None,
        f"Valuation context: {snap.raw_info}" if snap.raw_info else None,
    ]))


def valuation_block(val) -> str:
    if not val:
        return "No valuation available (missing FCF data)."
    ig = (f"{val.implied_growth_at_price:.1%}"
          if val.implied_growth_at_price is not None else "n/a")
    return (f"Fair value/share — low {val.fair_low:,.2f}, "
            f"base {val.fair_base:,.2f}, high {val.fair_high:,.2f}. "
            f"DCF {val.dcf_per_share and round(val.dcf_per_share, 2)}, "
            f"EPV {val.epv_per_share and round(val.epv_per_share, 2)}, "
            f"exit-multiple {val.exit_multiple_per_share and round(val.exit_multiple_per_share, 2)}. "
            f"Growth implied by current price (reverse DCF): {ig}.")


def collect_new_items(db: DB, edgar: EdgarClient, tkr, snap,
                      settings) -> tuple[list[dict], list]:
    """Gather unseen items across sources. Returns (items, insider_txs)."""
    items: list[dict[str, Any]] = []
    filings_days = settings.get("lookback", "filings_days", default=4)
    news_days = settings.get("lookback", "news_days", default=2)
    insider_days = settings.get("lookback", "insider_days", default=14)

    filings = []
    try:
        filings = edgar.recent_filings(tkr.symbol, days=filings_days)
    except Exception as e:
        print(f"  [warn] EDGAR filings failed for {tkr.symbol}: {e}")
    for f in filings:
        if db.is_seen(f.uid):
            continue
        items.append({
            "id": f.uid, "source": "edgar", "form": f.form,
            "category": f.category, "headline": f"{f.form}: {f.title}",
            "date": f.filed_at, "url": f.url, "_filing": f,
        })

    insider_txs = []
    try:
        insider_txs = edgar.insider_transactions(tkr.symbol, days=insider_days)
    except Exception as e:
        print(f"  [warn] Form 4 fetch failed for {tkr.symbol}: {e}")
    for tx in insider_txs:
        if db.is_seen(tx.uid):
            continue
        items.append({
            "id": tx.uid, "source": "form4", "action": tx.action,
            "value": tx.value,
            "headline": (f"Insider {tx.action}: {tx.insider} ({tx.role}) "
                         f"{tx.shares:,.0f} sh @ {tx.price:,.2f} "
                         f"(${tx.value:,.0f})"),
            "date": tx.filed_at,
        })

    try:
        for n in market.fetch_news(tkr.symbol, days=news_days):
            if db.is_seen(n.uid):
                continue
            items.append({
                "id": n.uid, "source": "news",
                "headline": f"{n.title} ({n.publisher})",
                "date": n.published_at, "url": n.link,
            })
    except Exception as e:
        print(f"  [warn] news fetch failed for {tkr.symbol}: {e}")

    move = snap.change_pct
    thresh = settings.get("alerts", "price_move_threshold_pct", default=5.0)
    if move is not None and abs(move) >= thresh:
        pid = f"price:{tkr.symbol}:{snap.prev_close}:{snap.price}"
        if not db.is_seen(pid):
            items.append({
                "id": pid, "source": "price", "change_pct": move,
                "headline": f"Price moved {move:+.1f}% vs previous close",
                "date": "",
            })
    return items, insider_txs


def process_ticker(tkr, db: DB, edgar: EdgarClient, llm: LLM,
                   philosophy: str, macro_ctx: str, settings,
                   sink: AlertSink, run_id: int) -> dict[str, Any]:
    print(f"→ {tkr.symbol}")
    snap = market.fetch_snapshot(tkr.symbol)

    # Bootstrap research folder + assumptions on first sight
    assumptions = research_doc.load_assumptions(tkr)
    if assumptions is None:
        assumptions = derive_default_assumptions(snap, settings)
    research_doc.bootstrap(tkr, snap, assumptions)
    thesis_needed = research_doc.thesis_is_template(tkr)

    # Valuation (deterministic, always runs)
    valuation = None
    if assumptions.fcf_base > 0 and snap.shares_out:
        assumptions.shares_out = float(snap.shares_out)
        assumptions.net_debt = float(snap.net_debt or assumptions.net_debt)
        try:
            valuation = run_valuation(assumptions, snap.price)
        except ValueError as e:
            print(f"  [warn] valuation failed: {e}")

    prev_val = db.last_valuation(tkr.symbol)
    if valuation:
        db.add_valuation(run_id, tkr.symbol, snap.price or 0,
                         valuation.fair_low, valuation.fair_base,
                         valuation.fair_high, valuation.components)

    # Catalysts
    if snap.next_earnings:
        date_only = str(snap.next_earnings)[:10]
        db.upsert_catalyst(tkr.symbol, date_only, "Earnings report", "yfinance")

    # New information
    items, insider_txs = collect_new_items(db, edgar, tkr, snap, settings)
    print(f"  {len(items)} new item(s)")

    analysis = None
    alerted = False
    if items and not thesis_needed:
        # Triage: rules first, LLM for the rest
        thresh = settings.get("alerts", "price_move_threshold_pct", default=5.0)
        scored: dict[str, dict[str, Any]] = {}
        needs_llm = []
        for it in items:
            rule = triage_mod.rule_based_materiality(it, thresh)
            if rule is not None:
                scored[it["id"]] = {"materiality": rule,
                                    "category": it.get("category",
                                                       it["source"]),
                                    "reason": "rule-based"}
            else:
                needs_llm.append({k: v for k, v in it.items()
                                  if not k.startswith("_")})
        if needs_llm:
            try:
                scored.update(triage_mod.run_triage(
                    llm, tkr.symbol, research_doc.thesis_summary(tkr),
                    needs_llm))
            except Exception as e:
                print(f"  [warn] triage failed: {e}")

        material = [it for it in items
                    if scored.get(it["id"], {}).get("materiality", 0) >= 6]
        print(f"  {len(material)} material after triage")

        if material and llm.deep_budget_left:
            # Attach filing text for EDGAR items (the analyst reads sources)
            events = []
            for it in material[:4]:
                ev = {k: v for k, v in it.items() if not k.startswith("_")}
                ev["triage_reason"] = scored.get(it["id"], {}).get("reason", "")
                ev["category"] = scored.get(it["id"], {}).get(
                    "category", it["source"])
                filing = it.get("_filing")
                if filing is not None:
                    ev["content"] = edgar.filing_text(filing)
                events.append(ev)
            try:
                analysis = run_deep_analysis(
                    llm, philosophy, tkr.symbol,
                    research_doc.read_thesis(tkr),
                    fundamentals_block(snap), valuation_block(valuation),
                    macro_ctx, events)
            except Exception as e:
                print(f"  [warn] deep analysis failed: {e}")
                traceback.print_exc()

    # Conviction
    prev_conv = db.last_conviction(tkr.symbol)
    thesis_strength = (analysis["thesis_strength"] if analysis
                       else (prev_conv["thesis_strength"] if prev_conv else 50))
    conviction = compute_conviction(thesis_strength, snap, valuation, settings)
    db.add_conviction(run_id, tkr.symbol, thesis_strength, conviction.score,
                      {"adjustments": conviction.adjustments})

    # Alerts
    reasons = alert_reasons(analysis, prev_val, valuation, snap,
                            [t for t in insider_txs
                             if not db.is_seen(t.uid)], settings)
    if reasons and not thesis_needed:
        alerted = True
        sink.add(Alert(
            symbol=tkr.symbol, reasons=reasons,
            headline=(analysis or {}).get("headline",
                                          "Material change detected"),
            plain_english=(analysis or {}).get("plain_english_summary", ""),
            conviction=conviction.score,
            fair_value=valuation.fair_base if valuation else None,
            price=snap.price))

    # Persist analysis → research doc, journal, events table
    if analysis:
        research_doc.append_entry(tkr, analysis, valuation, conviction,
                                  alerted)
        journal.log("analysis", tkr.symbol, {
            **{k: analysis[k] for k in ("headline", "thesis_impact",
                                        "thesis_strength", "committee_memo",
                                        "plain_english_summary")},
            "conviction": conviction.score,
            "fair_value_base": valuation.fair_base if valuation else None,
            "price": snap.price,
            "alert_reasons": reasons,
        })
        db.add_event(run_id, tkr.symbol, "analysis", "analysis",
                     analysis["headline"], 8, analysis["thesis_impact"],
                     analysis, alerted)
    elif reasons:
        journal.log("alert", tkr.symbol,
                    {"summary": "; ".join(reasons), "price": snap.price})

    # Mark everything seen (analyzed or not — triage verdict is final)
    for it in items:
        db.mark_seen(it["id"], tkr.symbol, it["source"])

    # Row for the dashboard
    conv_hist = [r["conviction_score"] for r in
                 db.conviction_history(tkr.symbol)]
    recent = db.recent_events(tkr.symbol, limit=5)
    last_memo = ""
    risks: list[str] = []
    last_impact = "neutral"
    if recent:
        last = json.loads(recent[0]["analysis_json"] or "{}")
        last_memo = last.get("plain_english_summary", "")[:280]
        last_impact = recent[0]["thesis_impact"] or "neutral"
        for ev in recent:
            a = json.loads(ev["analysis_json"] or "{}")
            risks.extend(a.get("new_risks", []))
    return {
        "symbol": tkr.symbol, "name": tkr.name,
        "conviction": conviction.score,
        "thesis_strength": thesis_strength,
        "conviction_history": conv_hist,
        "price": snap.price,
        "fair_low": valuation.fair_low if valuation else None,
        "fair_base": valuation.fair_base if valuation else None,
        "fair_high": valuation.fair_high if valuation else None,
        "upside_pct": ((valuation.fair_base / snap.price - 1) * 100
                       if valuation and snap.price and valuation.fair_base
                       else None),
        "last_impact": last_impact,
        "last_memo": last_memo,
        "risks": risks[:4],
        "catalysts": [dict(c) for c in db.upcoming_catalysts(tkr.symbol)],
        "position_value": (tkr.shares * snap.price
                           if tkr.shares and snap.price else 0),
        "thesis_needed": thesis_needed,
    }


def main() -> int:
    settings = config.load_settings()
    watchlist = config.load_watchlist()
    philosophy = config.load_philosophy()
    db = DB()
    run_id = db.start_run()
    edgar = EdgarClient(settings.get("identity", "edgar_user_agent",
                                     default="Personal Research System"))
    llm = LLM(settings)
    sink = AlertSink(settings)

    macro_ctx = ""
    if settings.get("macro", "enabled", default=False):
        macro_ctx = macro.fetch_macro_context(
            settings.get("macro", "fred_series", default=[]) or [],
            config.env("FRED_API_KEY"))

    rows: list[dict[str, Any]] = []
    failures = 0
    for tkr in watchlist:
        try:
            rows.append(process_ticker(tkr, db, edgar, llm, philosophy,
                                       macro_ctx, settings, sink, run_id))
        except Exception as e:
            failures += 1
            print(f"[error] {tkr.symbol} failed entirely: {e}")
            traceback.print_exc()
            journal.log("system", tkr.symbol,
                        {"summary": f"run failure: {e}"})

    # Thesis-change history for dashboard
    history = []
    for tkr in watchlist:
        for ev in db.recent_events(tkr.symbol, limit=10):
            history.append({
                "date": ev["occurred_at"][:10], "symbol": ev["symbol"],
                "impact": ev["thesis_impact"], "headline": ev["headline"],
                "strength": json.loads(ev["analysis_json"] or "{}"
                                       ).get("thesis_strength"),
            })
    history.sort(key=lambda h: h["date"], reverse=True)

    dashboard.generate(rows, [], history, settings)
    sent = sink.flush()
    status = "ok" if failures == 0 else f"partial ({failures} failed)"
    db.finish_run(run_id, status=status,
                  notes=f"alerts_sent={sent}, deep_analyses={llm.deep_used}")
    print(f"Run complete: {status}. Deep analyses: {llm.deep_used}. "
          f"Alert digest sent: {sent}.")
    db.close()
    return 0 if failures < len(watchlist) else 1


if __name__ == "__main__":
    raise SystemExit(main())
