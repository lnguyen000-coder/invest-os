"""SQLite persistence. The DB file lives in state/ and is committed back
to the repo by the GitHub Action, so git history doubles as backup."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import STATE_DIR

DB_PATH = STATE_DIR / "research.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT DEFAULT 'running',
    notes TEXT
);

-- Everything the system has already seen, so it never re-analyzes.
CREATE TABLE IF NOT EXISTS seen_items (
    id TEXT PRIMARY KEY,            -- source-specific unique id
    symbol TEXT NOT NULL,
    source TEXT NOT NULL,           -- edgar | form4 | news | price | macro
    seen_at TEXT NOT NULL
);

-- Material events that passed triage, with full analysis attached.
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    run_id INTEGER,
    symbol TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    source TEXT NOT NULL,
    category TEXT,                  -- filing|guidance|insider|news|price|risk|macro
    headline TEXT,
    materiality INTEGER,            -- 0-10 from triage
    thesis_impact TEXT,             -- strengthens|weakens|neutral
    analysis_json TEXT,             -- full structured analysis
    alerted INTEGER DEFAULT 0
);

-- Valuation snapshots per run per ticker.
CREATE TABLE IF NOT EXISTS valuations (
    id INTEGER PRIMARY KEY,
    run_id INTEGER,
    symbol TEXT NOT NULL,
    as_of TEXT NOT NULL,
    price REAL,
    fair_value_low REAL,
    fair_value_base REAL,
    fair_value_high REAL,
    upside_pct REAL,
    detail_json TEXT
);

-- Conviction / thesis strength over time.
CREATE TABLE IF NOT EXISTS conviction (
    id INTEGER PRIMARY KEY,
    run_id INTEGER,
    symbol TEXT NOT NULL,
    as_of TEXT NOT NULL,
    thesis_strength INTEGER,        -- 0-100
    conviction_score REAL,          -- 0-100 composite
    detail_json TEXT
);

CREATE TABLE IF NOT EXISTS catalysts (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    date TEXT,
    label TEXT NOT NULL,
    source TEXT,
    UNIQUE(symbol, date, label)
);

CREATE INDEX IF NOT EXISTS idx_events_symbol ON events(symbol, occurred_at);
CREATE INDEX IF NOT EXISTS idx_val_symbol ON valuations(symbol, as_of);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---- runs -------------------------------------------------------
    def start_run(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at) VALUES (?)", (now_iso(),)
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str = "ok", notes: str = "") -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, status=?, notes=? WHERE id=?",
            (now_iso(), status, notes, run_id),
        )
        self.conn.commit()

    # ---- dedupe -----------------------------------------------------
    def is_seen(self, item_id: str) -> bool:
        r = self.conn.execute(
            "SELECT 1 FROM seen_items WHERE id=?", (item_id,)
        ).fetchone()
        return r is not None

    def mark_seen(self, item_id: str, symbol: str, source: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_items (id, symbol, source, seen_at) VALUES (?,?,?,?)",
            (item_id, symbol, source, now_iso()),
        )
        self.conn.commit()

    # ---- events -----------------------------------------------------
    def add_event(self, run_id: int, symbol: str, source: str, category: str,
                  headline: str, materiality: int, thesis_impact: str,
                  analysis: dict[str, Any], alerted: bool) -> int:
        cur = self.conn.execute(
            """INSERT INTO events
               (run_id, symbol, occurred_at, source, category, headline,
                materiality, thesis_impact, analysis_json, alerted)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (run_id, symbol, now_iso(), source, category, headline,
             materiality, thesis_impact, json.dumps(analysis), int(alerted)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def recent_events(self, symbol: str, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM events WHERE symbol=? ORDER BY occurred_at DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()

    # ---- valuations -------------------------------------------------
    def add_valuation(self, run_id: int, symbol: str, price: float,
                      low: float, base: float, high: float,
                      detail: dict[str, Any]) -> None:
        upside = ((base / price) - 1) * 100 if price else 0.0
        self.conn.execute(
            """INSERT INTO valuations
               (run_id, symbol, as_of, price, fair_value_low, fair_value_base,
                fair_value_high, upside_pct, detail_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (run_id, symbol, now_iso(), price, low, base, high, upside,
             json.dumps(detail)),
        )
        self.conn.commit()

    def last_valuation(self, symbol: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM valuations WHERE symbol=? ORDER BY as_of DESC, id DESC LIMIT 1",
            (symbol,),
        ).fetchone()

    # ---- conviction -------------------------------------------------
    def add_conviction(self, run_id: int, symbol: str, thesis_strength: int,
                       conviction: float, detail: dict[str, Any]) -> None:
        self.conn.execute(
            """INSERT INTO conviction
               (run_id, symbol, as_of, thesis_strength, conviction_score, detail_json)
               VALUES (?,?,?,?,?,?)""",
            (run_id, symbol, now_iso(), thesis_strength, conviction,
             json.dumps(detail)),
        )
        self.conn.commit()

    def last_conviction(self, symbol: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM conviction WHERE symbol=? ORDER BY as_of DESC, id DESC LIMIT 1",
            (symbol,),
        ).fetchone()

    def conviction_history(self, symbol: str, limit: int = 90) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM conviction WHERE symbol=? ORDER BY as_of ASC LIMIT ?",
            (symbol, limit),
        ).fetchall()

    # ---- catalysts --------------------------------------------------
    def upsert_catalyst(self, symbol: str, date: str, label: str, source: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO catalysts (symbol, date, label, source) VALUES (?,?,?,?)",
            (symbol, date, label, source),
        )
        self.conn.commit()

    def upcoming_catalysts(self, symbol: str | None = None) -> list[sqlite3.Row]:
        today = datetime.now(timezone.utc).date().isoformat()
        if symbol:
            return self.conn.execute(
                "SELECT * FROM catalysts WHERE symbol=? AND date>=? ORDER BY date ASC",
                (symbol, today),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM catalysts WHERE date>=? ORDER BY date ASC", (today,)
        ).fetchall()

    def close(self) -> None:
        self.conn.close()
