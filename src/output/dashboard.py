"""Dashboard generator. Produces a single static docs/index.html each run;
GitHub Pages serves it. No build step, no JS framework — the data is baked
in at generation time, which is exactly right for a once-daily system.

Design: a private research ledger. Ink-and-paper palette with a ledger
green, mono numerals, and conviction sparklines drawn as inline SVG.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any

from src.config import DOCS_DIR


def _esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


def _money(v: float | None) -> str:
    return f"${v:,.2f}" if v is not None else "—"


def _sparkline(values: list[float], width: int = 120, height: int = 28,
               color: str = "#2E6E4E") -> str:
    if len(values) < 2:
        return "<span class='mono dim'>—</span>"
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    pts = []
    for i, v in enumerate(values):
        x = i / (len(values) - 1) * (width - 4) + 2
        y = height - 3 - (v - lo) / span * (height - 6)
        pts.append(f"{x:.1f},{y:.1f}")
    return (f"<svg class='spark' width='{width}' height='{height}' "
            f"viewBox='0 0 {width} {height}' aria-hidden='true'>"
            f"<polyline points='{' '.join(pts)}' fill='none' "
            f"stroke='{color}' stroke-width='1.5'/></svg>")


def _impact_chip(impact: str) -> str:
    cls = {"strengthens": "up", "weakens": "down"}.get(impact, "flat")
    return f"<span class='chip {cls}'>{_esc(impact)}</span>"


CSS = """
:root{
  --paper:#F2F4F1; --card:#FBFCFA; --ink:#1A2622; --dim:#5C6B64;
  --ledger:#2E6E4E; --ledger-soft:#DDEAE2; --oxblood:#8C3B2E;
  --rule:#C9D4CC; --gold:#8A6D2F;
}
*{box-sizing:border-box;margin:0}
body{background:var(--paper);color:var(--ink);
  font:15px/1.55 "IBM Plex Sans",system-ui,sans-serif;padding:0 0 4rem}
.mono{font-family:"IBM Plex Mono",ui-monospace,monospace}
.dim{color:var(--dim)}
header{border-bottom:2px solid var(--ink);padding:2.2rem 5vw 1.2rem;
  display:flex;flex-wrap:wrap;align-items:baseline;gap:1rem}
header h1{font-family:Spectral,Georgia,serif;font-weight:600;
  font-size:clamp(1.6rem,3.5vw,2.4rem);letter-spacing:-.01em}
.stamp{margin-left:auto;font-family:"IBM Plex Mono",monospace;
  font-size:.78rem;border:1.5px solid var(--ink);padding:.35rem .7rem;
  transform:rotate(-1.2deg);background:var(--card)}
main{padding:0 5vw;max-width:1180px;margin:0 auto}
h2{font-family:Spectral,Georgia,serif;font-weight:600;font-size:1.25rem;
  margin:2.4rem 0 .9rem;display:flex;align-items:center;gap:.6rem}
h2::after{content:"";flex:1;border-top:1px solid var(--rule)}
table{width:100%;border-collapse:collapse;background:var(--card);
  border:1px solid var(--rule)}
th{font-family:"IBM Plex Mono",monospace;font-size:.68rem;
  text-transform:uppercase;letter-spacing:.08em;color:var(--dim);
  text-align:left;padding:.55rem .7rem;border-bottom:2px solid var(--ink)}
td{padding:.6rem .7rem;border-bottom:1px solid var(--rule);
  vertical-align:middle;font-size:.9rem}
td.num,th.num{text-align:right;font-family:"IBM Plex Mono",monospace}
tr:last-child td{border-bottom:none}
.bar{height:7px;background:var(--ledger-soft);min-width:80px;position:relative}
.bar i{position:absolute;inset:0 auto 0 0;background:var(--ledger)}
.chip{font-family:"IBM Plex Mono",monospace;font-size:.7rem;
  padding:.1rem .45rem;border:1px solid currentColor}
.chip.up{color:var(--ledger)} .chip.down{color:var(--oxblood)}
.chip.flat{color:var(--dim)}
.grid{display:grid;gap:1rem;grid-template-columns:repeat(auto-fill,minmax(330px,1fr))}
.card{background:var(--card);border:1px solid var(--rule);padding:1.1rem 1.2rem}
.card h3{font-family:Spectral,Georgia,serif;font-size:1.05rem;
  display:flex;justify-content:space-between;align-items:baseline;gap:.5rem}
.card ul{margin:.5rem 0 0 1.05rem;font-size:.86rem}
.card li{margin:.25rem 0}
.risk{color:var(--oxblood)}
.needs{border-left:4px solid var(--gold);padding-left:1rem}
.memo{font-size:.86rem;border-left:3px solid var(--ledger);
  padding:.4rem 0 .4rem .8rem;margin:.6rem 0;background:var(--ledger-soft)}
footer{margin:3rem 5vw 0;font-size:.75rem;color:var(--dim);
  border-top:1px solid var(--rule);padding-top:.8rem;max-width:1180px}
@media (prefers-reduced-motion:no-preference){
  .spark polyline{stroke-dasharray:400;stroke-dashoffset:400;
    animation:draw 1.1s ease forwards}
  @keyframes draw{to{stroke-dashoffset:0}}}
"""


def generate(rows: list[dict[str, Any]], catalysts: list[dict[str, Any]],
             history: list[dict[str, Any]], settings) -> None:
    """rows: one dict per ticker with keys used below."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    title = settings.get("dashboard", "title", default="Investment Research OS")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rows_sorted = sorted(rows, key=lambda r: r.get("conviction") or 0,
                         reverse=True)
    total_value = sum((r.get("position_value") or 0) for r in rows) or 0

    # --- watchlist ranking table ---
    trs = []
    for i, r in enumerate(rows_sorted, 1):
        conv = r.get("conviction")
        spark = _sparkline(r.get("conviction_history", []))
        alloc = ""
        if total_value and r.get("position_value"):
            alloc = f"{r['position_value'] / total_value * 100:.0f}%"
        upside = r.get("upside_pct")
        trs.append(f"""
<tr>
 <td class="mono dim">{i:02d}</td>
 <td><strong>{_esc(r['symbol'])}</strong><br>
     <span class="dim" style="font-size:.78rem">{_esc(r.get('name', ''))}</span></td>
 <td class="num">{f"{conv:.0f}" if conv is not None else "—"}
   <div class="bar"><i style="width:{(conv or 0):.0f}%"></i></div></td>
 <td class="num">{r.get('thesis_strength') if r.get('thesis_strength') is not None else '—'}</td>
 <td>{spark}</td>
 <td class="num">{_money(r.get('price'))}</td>
 <td class="num">{_money(r.get('fair_base'))}<br>
   <span class="dim" style="font-size:.75rem">{_money(r.get('fair_low'))}–{_money(r.get('fair_high'))}</span></td>
 <td class="num">{f"{upside:+.0f}%" if upside is not None else "—"}</td>
 <td>{_impact_chip(r.get('last_impact', 'neutral'))}</td>
 <td class="num">{alloc or '—'}</td>
</tr>""")

    # --- per-ticker cards ---
    cards = []
    for r in rows_sorted:
        if r.get("thesis_needed"):
            cards.append(f"""
<div class="card needs">
 <h3>{_esc(r['symbol'])} <span class="mono dim">thesis needed</span></h3>
 <p style="font-size:.86rem;margin-top:.5rem">Edit
 <code>research/{_esc(r['symbol'])}/thesis.md</code> — deep analysis is paused
 until the template banner is removed.</p>
</div>""")
            continue
        risks = "".join(f"<li class='risk'>{_esc(x)}</li>"
                        for x in (r.get("risks") or [])[:4])
        cats = "".join(
            f"<li><span class='mono'>{_esc(c['date'])}</span> {_esc(c['label'])}</li>"
            for c in (r.get("catalysts") or [])[:4])
        memo = r.get("last_memo", "")
        cards.append(f"""
<div class="card">
 <h3>{_esc(r['symbol'])}
   <span class="mono" style="font-size:.85rem">{f"{r.get('conviction'):.0f}/100" if r.get('conviction') is not None else ""}</span></h3>
 {f"<div class='memo'>{_esc(memo)}</div>" if memo else ""}
 {f"<p class='mono dim' style='font-size:.72rem;margin-top:.4rem'>CATALYSTS</p><ul>{cats}</ul>" if cats else ""}
 {f"<p class='mono dim' style='font-size:.72rem;margin-top:.6rem'>ACTIVE RISKS</p><ul>{risks}</ul>" if risks else ""}
</div>""")

    # --- thesis change history ---
    hist_rows = "".join(f"""
<tr><td class="mono">{_esc(h['date'])}</td><td><strong>{_esc(h['symbol'])}</strong></td>
<td>{_impact_chip(h.get('impact', 'neutral'))}</td>
<td>{_esc(h.get('headline', ''))}</td>
<td class="num">{h.get('strength', '—')}</td></tr>"""
        for h in history[:40])

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>{_esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Spectral:wght@500;600&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>
<header>
 <h1>{_esc(title)}</h1>
 <div class="stamp">RUN · {now}</div>
</header>
<main>
 <h2>Watchlist ranking</h2>
 <div style="overflow-x:auto">
 <table>
  <thead><tr><th>#</th><th>Company</th><th class="num">Conviction</th>
  <th class="num">Thesis</th><th>90-day trend</th><th class="num">Price</th>
  <th class="num">Fair value</th><th class="num">Upside</th>
  <th>Last verdict</th><th class="num">Allocation</th></tr></thead>
  <tbody>{"".join(trs)}</tbody>
 </table></div>

 <h2>Positions &amp; watch cards</h2>
 <div class="grid">{"".join(cards)}</div>

 <h2>Thesis change history</h2>
 <div style="overflow-x:auto">
 <table>
  <thead><tr><th>Date</th><th>Ticker</th><th>Impact</th>
  <th>Headline</th><th class="num">Strength</th></tr></thead>
  <tbody>{hist_rows or '<tr><td colspan=5 class=dim>No material changes logged yet.</td></tr>'}</tbody>
 </table></div>
</main>
<footer>Personal research tool. Valuations are model outputs under stated
assumptions, not advice or price targets. Full reasoning lives in
research/&lt;TICKER&gt;/research.md and journal/.</footer>
</body></html>"""

    (DOCS_DIR / "index.html").write_text(page, encoding="utf-8")
    # Machine-readable mirror for future integrations
    (DOCS_DIR / "data.json").write_text(
        json.dumps({"generated": now, "rows": rows_sorted,
                    "history": history[:100]}, indent=1, default=str),
        encoding="utf-8")
