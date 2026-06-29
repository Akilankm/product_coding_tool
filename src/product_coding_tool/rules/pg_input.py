"""Load the canonical PG feature input CSV for product coding.

Canonical CSV contract (exactly the contract expected by the notebook/CLI):

PG_name,features,type,allowed_values,description

- PG_name: Product group name, e.g. "Figures/Build Sets"
- features: Feature name to code, e.g. "BRAND" or "TYPE TOY"
- type: "open_set" or "closed_set"
- allowed_values: semicolon-separated values for closed_set features; blank for open_set
- description: concise rulebook definition / coding hint

The product coding tool takes two runtime inputs:
1. an existing scrape artifact folder
2. this 5-column PG feature CSV

It does not perform web search or scraping.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Iterable

from ..models import FeatureRule, FeatureType

_CANONICAL_COLUMNS = ["PG_name", "features", "type", "allowed_values", "description"]
_REQUIRED_NORMALIZED = {"pg_name", "features", "type", "allowed_values", "description"}


class PGFeatureInputError(ValueError):
    """Raised when the PG feature CSV is missing required structure."""


class PGFeatureInputProvider:
    """Adapter for the 5-column PG-to-feature CSV.

    The file can contain all PGs. At runtime, select one PG with `pg_name` and
    the provider returns `FeatureRule` objects consumed by ProductCodingAgent.
    """

    def __init__(self, rows: Iterable[dict[str, Any]]) -> None:
        self.rows = [_normalize_row(row, idx + 1) for idx, row in enumerate(rows)]
        if not self.rows:
            raise PGFeatureInputError("PG feature input has no rows.")

    @classmethod
    def from_file(cls, path: str | Path) -> "PGFeatureInputProvider":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"PG feature input file does not exist: {path}")
        if path.suffix.lower() != ".csv":
            raise PGFeatureInputError(
                "PG feature input must be a CSV with columns: " + ", ".join(_CANONICAL_COLUMNS)
            )
        return cls(_read_csv(path))

    def pg_names(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for row in self.rows:
            name = str(row.get("PG_name") or "").strip()
            key = _clean_key(name)
            if name and key not in seen:
                out.append(name)
                seen.add(key)
        return out

    def filter_rows(
        self,
        *,
        pg_name: str | None = None,
        feature_names: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        rows = list(self.rows)
        if pg_name:
            target = _clean_key(pg_name)
            rows = [row for row in rows if _clean_key(row.get("PG_name")) == target]
        elif len(self.pg_names()) > 1:
            raise PGFeatureInputError(
                "PG feature CSV contains multiple PGs. Provide pg_name. Available PGs: "
                + ", ".join(self.pg_names()[:30])
            )

        if feature_names:
            allowed_names = {_clean_key(x) for x in feature_names if str(x).strip()}
            rows = [row for row in rows if _clean_key(row.get("features")) in allowed_names]
        return rows

    def features_for_pg(
        self,
        *,
        pg_name: str | None = None,
        feature_names: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> list[FeatureRule]:
        rows = self.filter_rows(pg_name=pg_name, feature_names=feature_names)
        if not rows:
            available = ", ".join(self.pg_names()[:20])
            raise PGFeatureInputError(
                f"No features matched pg_name={pg_name!r}. Available PGs: {available}"
            )
        rows = sorted(rows, key=lambda row: int(row["_row_order"]))
        if limit is not None:
            rows = rows[: max(0, int(limit))]
        return [row_to_feature_rule(row) for row in rows]


def row_to_feature_rule(row: dict[str, Any]) -> FeatureRule:
    pg_name = str(row.get("PG_name") or "").strip()
    feature_name = str(row.get("features") or "").strip()
    feature_type = _normalize_feature_type(row.get("type"))
    allowed_values = _split_list(row.get("allowed_values") or "")
    description = str(row.get("description") or "").strip()

    # User-facing CSV intentionally does not carry feature_id. Generate a stable
    # internal ID from PG + feature so outputs and audits still have a non-blank identifier.
    feature_id = _feature_id(pg_name, feature_name)

    return FeatureRule(
        feature_id=feature_id,
        feature_name=feature_name,
        feature_type=feature_type,
        definition=description,
        allowed_values=allowed_values,
        evidence_hints=[description] if description else [],
        pg_name=pg_name,
        feature_order=int(row.get("_row_order") or 0),
        classification_reason=(
            "closed_set with explicit allowed values"
            if feature_type == "closed_set" and allowed_values
            else "open_set dynamic/free-text value"
        ),
    )


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _normalize_row(row: dict[str, Any], row_order: int) -> dict[str, Any]:
    # Normalize by case/spacing while preserving canonical output keys.
    by_norm = {_normalize_col(k): ("" if v is None else v) for k, v in row.items()}
    missing = sorted(_REQUIRED_NORMALIZED - set(by_norm))
    if missing:
        raise PGFeatureInputError(
            "PG feature CSV is missing required columns: "
            + ", ".join(missing)
            + ". Expected columns: "
            + ", ".join(_CANONICAL_COLUMNS)
        )

    normalized = {
        "PG_name": str(by_norm["pg_name"]).strip(),
        "features": str(by_norm["features"]).strip(),
        "type": _normalize_feature_type(by_norm["type"]),
        "allowed_values": str(by_norm["allowed_values"] or "").strip(),
        "description": str(by_norm["description"] or "").strip(),
        "_row_order": row_order,
    }

    if not normalized["PG_name"]:
        raise PGFeatureInputError(f"Row {row_order} has blank PG_name.")
    if not normalized["features"]:
        raise PGFeatureInputError(f"Row {row_order} has blank features.")
    if normalized["type"] == "closed_set" and not normalized["allowed_values"]:
        raise PGFeatureInputError(
            f"Row {row_order} feature={normalized['features']!r} is closed_set but allowed_values is blank."
        )
    if normalized["type"] == "open_set":
        # Keep open-set allowed values empty even if a user accidentally puts whitespace.
        normalized["allowed_values"] = ""
    return normalized


def _normalize_feature_type(value: Any) -> FeatureType:
    cleaned = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned in {"closed", "closedset", "closed_set", "classification", "categorical"}:
        return "closed_set"
    if cleaned in {"open", "openset", "open_set", "free_text", "dynamic"}:
        return "open_set"
    raise PGFeatureInputError(f"Unsupported type={value!r}. Expected open_set or closed_set.")


def _split_list(value: Any) -> list[str]:
    raw = str(value or "").replace("|", ";").split(";")
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        cleaned = " ".join(item.strip().split())
        key = cleaned.lower()
        if cleaned and key not in seen:
            out.append(cleaned)
            seen.add(key)
    return out


def _clean_key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalize_col(name: Any) -> str:
    cleaned = str(name or "").strip().lower().replace(" ", "_")
    aliases = {
        "pg": "pg_name",
        "product_group": "pg_name",
        "product_group_name": "pg_name",
        "feature": "features",
        "feature_name": "features",
        "feature_to_code": "features",
        "feature_type": "type",
        "allowed_value": "allowed_values",
        "values": "allowed_values",
        "definition": "description",
        "feature_description": "description",
    }
    return aliases.get(cleaned, cleaned)


def _feature_id(pg_name: str, feature_name: str) -> str:
    raw = f"{pg_name}__{feature_name}"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").upper()
    return slug or "FEATURE"


__all__ = ["PGFeatureInputError", "PGFeatureInputProvider", "row_to_feature_rule"]
