#!/usr/bin/env bash
# Local run for testing. Reads secrets from .env if present.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; source .env; set +a; fi
python -m src.main
