#!/usr/bin/env python
"""Run the artifact-grounded product coding agent.

Batch example:
    python scripts/run_product_coding.py \
      --batch-input examples/product_batch_input_canonical_pg_names.csv \
      --scraped-root data/scraped \
      --pg-feature-input examples/pg_feature_coding_input.csv \
      --output-dir data/coded/batch_run \
      --max-parallel-features 4

Single-product debug example:
    python scripts/run_product_coding.py \
      --artifact-dir data/scraped/ROW_0001 \
      --pg-name "TOY VEHICLES/PLAYSET" \
      --pg-feature-input examples/pg_feature_coding_input.csv
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
