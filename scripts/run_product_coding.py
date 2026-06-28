#!/usr/bin/env python
"""Run the artifact-grounded product coding agent.

Example:
    python scripts/run_product_coding.py \
      --artifact-dir data/scraped/scrape_20260628_190357_25c16d76 \
      --features-json examples/features.json \
      --output-dir data/coded/demo
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from product_coding_tool.cli import main


if __name__ == "__main__":
    main()
