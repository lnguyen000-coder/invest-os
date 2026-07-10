#!/usr/bin/env python3
"""Log YOUR buy/sell/trim/pass decisions with contemporaneous reasoning.

Usage:
  python scripts/journal_decision.py MSFT buy "Thesis intact, 20% below fair value" --price 410.50

Run it the moment you act. Future-you reviews these against outcomes.
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.output.journal import log_decision

p = argparse.ArgumentParser()
p.add_argument("symbol")
p.add_argument("action", choices=["buy", "sell", "trim", "add", "pass", "hold"])
p.add_argument("reasoning")
p.add_argument("--price", type=float, default=None)
a = p.parse_args()
log_decision(a.symbol.upper(), a.action, a.reasoning, a.price)
print(f"Logged: {a.action} {a.symbol.upper()} — remember to git commit journal/")
