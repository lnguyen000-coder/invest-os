"""SEC EDGAR (free, official). Filings feed + Form 4 insider activity.

EDGAR etiquette: descriptive User-Agent, <=10 req/s. We stay far under.
Docs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from xml.etree import ElementTree

import requests

_TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:0>10}.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}"

# Forms worth reading, mapped to a coarse category for triage.
INTERESTING_FORMS = {
    "10-K": "annual_report",
    "10-Q": "quarterly_report",
    "8-K": "material_event",
    "8-K/A": "material_event",
    "S-1": "offering",
    "424B5": "offering",
    "DEF 14A": "proxy",
    "SC 13D": "activist_stake",
    "SC 13G": "large_stake",
}


@dataclass
class Filing:
    symbol: str
    cik: str
    form: str
    category: str
    filed_at: str
    accession: str
    primary_doc: str
    title: str
    url: str
    text: str = ""          # extracted later, only if triage wants it

    @property
    def uid(self) -> str:
        return f"edgar:{self.accession}"


@dataclass
class InsiderTx:
    symbol: str
    filed_at: str
    insider: str
    role: str
    action: str             # buy | sell
    shares: float
    price: float
    value: float
    accession: str

    @property
    def uid(self) -> str:
        return f"form4:{self.accession}:{self.insider}"


class EdgarClient:
    def __init__(self, user_agent: str):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent,
                                     "Accept-Encoding": "gzip, deflate"})
        self._cik_map: dict[str, str] | None = None

    def _get(self, url: str, **kw) -> requests.Response:
        time.sleep(0.15)  # stay well under SEC's 10 req/s limit
        r = self.session.get(url, timeout=30, **kw)
        r.raise_for_status()
        return r

    # ---- CIK resolution --------------------------------------------
    def cik_for(self, symbol: str) -> str | None:
        if self._cik_map is None:
            data = self._get(_TICKER_CIK_URL).json()
            self._cik_map = {
                v["ticker"].upper(): str(v["cik_str"]) for v in data.values()
            }
        return self._cik_map.get(symbol.upper())

    # ---- recent filings --------------------------------------------
    def recent_filings(self, symbol: str, days: int = 4) -> list[Filing]:
        cik = self.cik_for(symbol)
        if not cik:
            return []
        data = self._get(_SUBMISSIONS_URL.format(cik=int(cik))).json()
        recent = data.get("filings", {}).get("recent", {})
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()
        out: list[Filing] = []
        forms = recent.get("form", [])
        for i, form in enumerate(forms):
            form = form.strip()
            if form not in INTERESTING_FORMS and form != "4":
                continue
            filed = recent["filingDate"][i]
            if datetime.fromisoformat(filed).date() < cutoff:
                continue
            accession = recent["accessionNumber"][i].replace("-", "")
            doc = recent["primaryDocument"][i]
            if form == "4":
                # Form 4s handled by insider_transactions(); skip here.
                continue
            out.append(Filing(
                symbol=symbol, cik=cik, form=form,
                category=INTERESTING_FORMS[form],
                filed_at=filed, accession=accession, primary_doc=doc,
                title=recent.get("primaryDocDescription", [""] * len(forms))[i] or form,
                url=_ARCHIVE_URL.format(cik=int(cik), accession=accession, doc=doc),
            ))
        return out

    # ---- filing text (for analysis) --------------------------------
    def filing_text(self, filing: Filing, max_chars: int = 60000) -> str:
        """Fetch and strip a filing to plain text, truncated for LLM use."""
        try:
            html = self._get(filing.url).text
        except requests.RequestException:
            return ""
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html,
                      flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;?", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]

    # ---- Form 4 insider transactions --------------------------------
    def insider_transactions(self, symbol: str, days: int = 14) -> list[InsiderTx]:
        cik = self.cik_for(symbol)
        if not cik:
            return []
        data = self._get(_SUBMISSIONS_URL.format(cik=int(cik))).json()
        recent = data.get("filings", {}).get("recent", {})
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()
        txs: list[InsiderTx] = []
        for i, form in enumerate(recent.get("form", [])):
            if form.strip() != "4":
                continue
            filed = recent["filingDate"][i]
            if datetime.fromisoformat(filed).date() < cutoff:
                continue
            accession = recent["accessionNumber"][i].replace("-", "")
            doc = recent["primaryDocument"][i]
            url = _ARCHIVE_URL.format(cik=int(cik), accession=accession, doc=doc)
            txs.extend(self._parse_form4(symbol, filed, accession, url))
        return txs

    def _parse_form4(self, symbol: str, filed: str, accession: str,
                     url: str) -> list[InsiderTx]:
        """Parse the Form 4 XML. Primary doc may be .xml directly or an
        index page; try the xml variant."""
        xml_url = url if url.endswith(".xml") else re.sub(r"/[^/]+$", "", url)
        try:
            if not url.endswith(".xml"):
                # Fetch directory index, find the .xml doc
                idx = self._get(xml_url + "/").text
                m = re.search(r'href="([^"]+\.xml)"', idx)
                if not m:
                    return []
                doc = m.group(1).rsplit("/", 1)[-1]
                xml_url = f"{xml_url}/{doc}"
            raw = self._get(xml_url).text
            root = ElementTree.fromstring(raw)
        except (requests.RequestException, ElementTree.ParseError):
            return []

        def _txt(node, path, default=""):
            el = node.find(path)
            return el.text.strip() if el is not None and el.text else default

        insider = _txt(root, ".//reportingOwner/reportingOwnerId/rptOwnerName")
        role_bits = []
        rel = root.find(".//reportingOwner/reportingOwnerRelationship")
        if rel is not None:
            if _txt(rel, "isDirector") == "1":
                role_bits.append("Director")
            if _txt(rel, "isOfficer") == "1":
                role_bits.append(_txt(rel, "officerTitle", "Officer"))
            if _txt(rel, "isTenPercentOwner") == "1":
                role_bits.append("10% owner")
        role = ", ".join(role_bits) or "Insider"

        out: list[InsiderTx] = []
        for tx in root.findall(".//nonDerivativeTransaction"):
            code = _txt(tx, ".//transactionCoding/transactionCode")
            if code not in ("P", "S"):   # open-market purchase / sale only
                continue
            shares = float(_txt(tx, ".//transactionShares/value", "0") or 0)
            price = float(_txt(tx, ".//transactionPricePerShare/value", "0") or 0)
            out.append(InsiderTx(
                symbol=symbol, filed_at=filed, insider=insider, role=role,
                action="buy" if code == "P" else "sell",
                shares=shares, price=price, value=shares * price,
                accession=accession,
            ))
        return out
