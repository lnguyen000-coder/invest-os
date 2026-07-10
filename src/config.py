"""Central configuration loading. Everything reads config through here."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
RESEARCH_DIR = ROOT / "research"
JOURNAL_DIR = ROOT / "journal"
STATE_DIR = ROOT / "state"
DOCS_DIR = ROOT / "docs"


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Ticker:
    symbol: str
    name: str
    position: str = "watch"
    shares: float = 0.0
    cost_basis: float = 0.0

    @property
    def research_dir(self) -> Path:
        return RESEARCH_DIR / self.symbol


@dataclass
class Settings:
    raw: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.raw
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node


def load_settings() -> Settings:
    return Settings(raw=_load_yaml(CONFIG_DIR / "settings.yaml"))


def load_watchlist() -> list[Ticker]:
    data = _load_yaml(CONFIG_DIR / "watchlist.yaml")
    out = []
    for t in data.get("tickers", []):
        out.append(
            Ticker(
                symbol=t["symbol"].upper().strip(),
                name=t.get("name", t["symbol"]),
                position=t.get("position", "watch"),
                shares=float(t.get("shares", 0) or 0),
                cost_basis=float(t.get("cost_basis", 0) or 0),
            )
        )
    return out


def load_philosophy() -> str:
    return (CONFIG_DIR / "philosophy.md").read_text(encoding="utf-8")


def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name, default)
    return v if v else default
