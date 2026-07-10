"""Market data via yfinance (free, unofficial Yahoo Finance wrapper).

Everything is wrapped defensively: yfinance fields come and go, so every
accessor degrades to None instead of crashing the morning run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import yfinance as yf


@dataclass
class Snapshot:
    symbol: str
    price: float | None = None
    prev_close: float | None = None
    change_pct: float | None = None
    market_cap: float | None = None
    shares_out: float | None = None
    # fundamentals (TTM / most recent)
    revenue: float | None = None
    ebitda: float | None = None
    ebit: float | None = None
    net_income: float | None = None
    fcf: float | None = None
    total_debt: float | None = None
    cash: float | None = None
    equity: float | None = None
    invested_capital: float | None = None
    roic: float | None = None
    fcf_history: list[float] = field(default_factory=list)   # oldest → newest
    revenue_history: list[float] = field(default_factory=list)
    gross_margin_history: list[float] = field(default_factory=list)
    beta: float | None = None
    next_earnings: str | None = None
    analyst_target_mean: float | None = None
    raw_info: dict[str, Any] = field(default_factory=dict)

    @property
    def net_debt(self) -> float | None:
        if self.total_debt is None:
            return None
        return self.total_debt - (self.cash or 0.0)

    @property
    def net_debt_to_ebitda(self) -> float | None:
        nd, e = self.net_debt, self.ebitda
        if nd is None or not e:
            return None
        return nd / e


@dataclass
class NewsItem:
    symbol: str
    title: str
    publisher: str
    link: str
    published_at: str
    uid_raw: str

    @property
    def uid(self) -> str:
        return f"news:{self.uid_raw}"


def _safe(d: dict, key: str) -> Any:
    v = d.get(key)
    return v if v not in ("", "None") else None


def _series_from_df(df, row_names: list[str]) -> list[float]:
    """Pull a row from a yfinance statement DataFrame, oldest→newest."""
    if df is None or getattr(df, "empty", True):
        return []
    for name in row_names:
        if name in df.index:
            vals = df.loc[name].dropna().tolist()
            return list(reversed([float(v) for v in vals]))  # yf is newest-first
    return []


def fetch_snapshot(symbol: str) -> Snapshot:
    t = yf.Ticker(symbol)
    snap = Snapshot(symbol=symbol)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    snap.raw_info = {k: info.get(k) for k in (
        "longName", "sector", "industry", "trailingPE", "forwardPE",
        "priceToSalesTrailing12Months", "enterpriseToEbitda",
    )}
    snap.price = _safe(info, "currentPrice") or _safe(info, "regularMarketPrice")
    snap.prev_close = _safe(info, "previousClose")
    if snap.price and snap.prev_close:
        snap.change_pct = (snap.price / snap.prev_close - 1) * 100
    snap.market_cap = _safe(info, "marketCap")
    snap.shares_out = _safe(info, "sharesOutstanding")
    snap.total_debt = _safe(info, "totalDebt")
    snap.cash = _safe(info, "totalCash")
    snap.ebitda = _safe(info, "ebitda")
    snap.beta = _safe(info, "beta")
    snap.analyst_target_mean = _safe(info, "targetMeanPrice")
    snap.fcf = _safe(info, "freeCashflow")
    snap.revenue = _safe(info, "totalRevenue")
    snap.net_income = _safe(info, "netIncomeToCommon")

    # Statement histories (annual) for trend analysis
    try:
        fin = t.financials
        cf = t.cashflow
        bs = t.balance_sheet
    except Exception:
        fin = cf = bs = None

    snap.revenue_history = _series_from_df(fin, ["Total Revenue"])
    ocf = _series_from_df(cf, ["Operating Cash Flow",
                               "Total Cash From Operating Activities"])
    capex = _series_from_df(cf, ["Capital Expenditure", "Capital Expenditures"])
    if ocf and capex:
        n = min(len(ocf), len(capex))
        snap.fcf_history = [ocf[i] + capex[i] for i in range(n)]  # capex negative
    gross = _series_from_df(fin, ["Gross Profit"])
    if gross and snap.revenue_history:
        n = min(len(gross), len(snap.revenue_history))
        snap.gross_margin_history = [
            gross[i] / snap.revenue_history[i]
            for i in range(n) if snap.revenue_history[i]
        ]
    ebit_hist = _series_from_df(fin, ["EBIT", "Operating Income"])
    snap.ebit = ebit_hist[-1] if ebit_hist else None

    equity_hist = _series_from_df(bs, ["Stockholders Equity",
                                       "Total Stockholder Equity"])
    snap.equity = equity_hist[-1] if equity_hist else None
    if snap.equity is not None and snap.total_debt is not None:
        snap.invested_capital = snap.equity + snap.total_debt - (snap.cash or 0)
        if snap.ebit and snap.invested_capital and snap.invested_capital > 0:
            snap.roic = (snap.ebit * 0.79) / snap.invested_capital  # ~21% tax

    # Next earnings date
    try:
        cal = t.calendar
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if dates:
            snap.next_earnings = str(dates[0])
    except Exception:
        pass
    return snap


def fetch_news(symbol: str, days: int = 2) -> list[NewsItem]:
    t = yf.Ticker(symbol)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[NewsItem] = []
    try:
        items = t.news or []
    except Exception:
        return []
    for it in items:
        content = it.get("content", it)  # yfinance changed shape in 2024/25
        title = content.get("title") or ""
        pub = content.get("pubDate") or content.get("providerPublishTime")
        if isinstance(pub, (int, float)):
            ts = datetime.fromtimestamp(pub, tz=timezone.utc)
        else:
            try:
                ts = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
        if ts < cutoff or not title:
            continue
        link = ""
        cu = content.get("canonicalUrl")
        if isinstance(cu, dict):
            link = cu.get("url", "")
        link = link or content.get("link", "")
        provider = content.get("provider")
        publisher = (provider.get("displayName") if isinstance(provider, dict)
                     else content.get("publisher", "")) or ""
        out.append(NewsItem(
            symbol=symbol, title=title, publisher=publisher, link=link,
            published_at=ts.isoformat(timespec="seconds"),
            uid_raw=it.get("id") or content.get("id") or f"{symbol}:{title[:60]}",
        ))
    return out
