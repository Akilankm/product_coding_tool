#!/usr/bin/env python
"""Register the Product Coding Tool Jupyter kernel and disable Jedi completion."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from product_coding_tool.kernel import main


if __name__ == "__main__":
    main()
