"""Load product batch input CSV for artifact-grounded product coding.

Canonical product batch input contract:

- `input_id`: required. Must match a folder name under the scrape artifact root,
  for example `data/scraped/ROW_0001`.
- `PG_name`: required. Used to select the feature list from the PG feature CSV.
- Any other columns are preserved as product context and copied into audit/output.

The product coding runtime takes three inputs:

1. product batch CSV with `input_id` and `PG_name`
2. scrape artifact root where each `input_id` is a folder name
3. PG feature CSV with `PG_name,features,type,allowed_values,description`
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

from ..models import ProductInputRow

_REQUIRED_NORMALIZED = {"input_id", "pg_name"}


class ProductBatchInputError(ValueError):
    """Raised when product batch input is malformed."""


class ProductBatchInputProvider:
    """Adapter for the product batch input CSV."""

    def __init__(self, rows: Iterable[dict[str, Any]]) -> None:
        self.rows = [_normalize_row(row, idx + 1) for idx, row in enumerate(rows)]
        if not self.rows:
            raise ProductBatchInputError("Product batch input has no rows.")

    @classmethod
    def from_file(cls, path: str | Path) -> "ProductBatchInputProvider":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Product batch input file does not exist: {path}")
        if path.suffix.lower() != ".csv":
            raise ProductBatchInputError("Product batch input must be a CSV containing input_id and PG_name columns.")
        return cls(_read_csv(path))

    def input_ids(self) -> list[str]:
        return [row.input_id for row in self.rows]

    def filter_rows(
        self,
        *,
        input_ids: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> list[ProductInputRow]:
        rows = list(self.rows)
        if input_ids:
            allowed = {_clean_key(value) for value in input_ids if str(value).strip()}
            rows = [row for row in rows if _clean_key(row.input_id) in allowed]
        if limit is not None:
            rows = rows[: max(0, int(limit))]
        return rows


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _normalize_row(row: dict[str, Any], row_order: int) -> ProductInputRow:
    if not row:
        raise ProductBatchInputError(f"Row {row_order} is empty.")
    normalized_columns = {_normalize_col(k): k for k in row.keys()}
    missing = sorted(_REQUIRED_NORMALIZED - set(normalized_columns))
    if missing:
        raise ProductBatchInputError(
            "Product batch input is missing required columns: "
            + ", ".join(missing)
            + ". Required columns: input_id, PG_name"
        )

    input_id_key = normalized_columns["input_id"]
    pg_name_key = normalized_columns["pg_name"]
    input_id = str(row.get(input_id_key) or "").strip()
    pg_name = str(row.get(pg_name_key) or "").strip()
    if not input_id:
        raise ProductBatchInputError(f"Row {row_order} has blank input_id.")
    if not pg_name:
        raise ProductBatchInputError(f"Row {row_order} has blank PG_name.")

    fields = {str(k): ("" if v is None else v) for k, v in row.items()}
    # Preserve canonical keys even if the uploaded file used aliases/case variants.
    fields["input_id"] = input_id
    fields["PG_name"] = pg_name
    return ProductInputRow(input_id=input_id, pg_name=pg_name, row_order=row_order, fields=fields)


def _normalize_col(name: Any) -> str:
    cleaned = str(name or "").strip().lower().replace(" ", "_")
    aliases = {
        "id": "input_id",
        "row_id": "input_id",
        "scrape_id": "input_id",
        "artifact_id": "input_id",
        "pg": "pg_name",
        "product_group": "pg_name",
        "product_group_name": "pg_name",
    }
    return aliases.get(cleaned, cleaned)


def _clean_key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


__all__ = ["ProductBatchInputError", "ProductBatchInputProvider"]
