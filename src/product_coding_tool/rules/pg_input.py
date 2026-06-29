"""Load and resolve the canonical PG feature input CSV for product coding.

Canonical CSV contract:

PG_name,features,type,allowed_values,description

The product coding batch CSV must ultimately use the same canonical PG names as
this file. The resolver is intentionally tolerant for legacy/batch aliases such
as ``ALL OTHER MISC. TOYS`` and ``TOY VEHICLES/PLAYSET`` so product rows do not
fail because of punctuation, abbreviations, casing, or singular/plural drift.
"""

from __future__ import annotations

import csv
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from ..models import FeatureRule, FeatureType

_CANONICAL_COLUMNS = ["PG_name", "features", "type", "allowed_values", "description"]
_REQUIRED_NORMALIZED = {"pg_name", "features", "type", "allowed_values", "description"}


class PGFeatureInputError(ValueError):
    """Raised when the PG feature CSV is missing required structure."""


class PGFeatureInputProvider:
    """Adapter for the 5-column PG-to-feature CSV.

    Runtime uses the canonical PG_name from this file. Batch labels are resolved
    to that canonical value before coding, and output context is rewritten to the
    canonical PG name while preserving PG_name_original separately.
    """

    def __init__(self, rows: Iterable[dict[str, Any]]) -> None:
        self.rows = [_normalize_row(row, idx + 1) for idx, row in enumerate(rows)]
        if not self.rows:
            raise PGFeatureInputError("PG feature input has no rows.")
        self._pg_names = _unique_preserve_order(str(row.get("PG_name") or "").strip() for row in self.rows)
        self._canonical_by_key = {_pg_match_key(name): name for name in self._pg_names}
        self._alias_to_canonical_key = self._build_alias_index()

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
        return list(self._pg_names)

    def resolve_pg_name(self, pg_name: str) -> str:
        """Resolve any supported batch PG label to the canonical feature CSV name.

        Examples:
        - ``TOY VEHICLES/PLAYSET`` -> ``Vehicles / Playsets``
        - ``ALL OTHER MISC. TOYS`` -> ``All Other Miscellaneous Toys``
        - ``INFANT/PRESCHOOL TOY`` -> ``Infant / Preschool Toys``
        """
        canonical = self._resolve_pg_name_or_none(pg_name)
        if canonical:
            return canonical
        available = ", ".join(self.pg_names()[:30])
        raise PGFeatureInputError(
            f"No features matched pg_name={pg_name!r}. Available PGs: {available}"
        )

    def canonicalization_audit(self, pg_names: Iterable[str]) -> list[dict[str, Any]]:
        """Return an audit table for batch PG labels against canonical PG names."""
        out: list[dict[str, Any]] = []
        for raw in pg_names:
            raw_str = str(raw or "").strip()
            canonical = self._resolve_pg_name_or_none(raw_str)
            out.append(
                {
                    "original_pg_name": raw_str,
                    "resolved_pg_name": canonical or "",
                    "matched": bool(canonical),
                    "original_key": _pg_match_key(raw_str),
                    "resolved_key": _pg_match_key(canonical) if canonical else "",
                }
            )
        return out

    def _resolve_pg_name_or_none(self, pg_name: str) -> str | None:
        target_key = _pg_match_key(pg_name)
        if not target_key:
            return None

        if target_key in self._canonical_by_key:
            return self._canonical_by_key[target_key]

        alias_key = self._alias_to_canonical_key.get(target_key) or _BUILTIN_PG_ALIASES.get(target_key)
        if alias_key and alias_key in self._canonical_by_key:
            return self._canonical_by_key[alias_key]

        # Conservative similarity fallback after normalization/abbreviation expansion.
        # This catches small punctuation/name variations without accepting unrelated PGs.
        best_key = ""
        best_score = 0.0
        for cand_key in self._canonical_by_key:
            score = _pg_similarity(target_key, cand_key)
            if score > best_score:
                best_score = score
                best_key = cand_key
        if best_key and best_score >= 0.88:
            return self._canonical_by_key[best_key]
        return None

    def _build_alias_index(self) -> dict[str, str]:
        alias_to_key: dict[str, str] = {}
        for canonical in self._pg_names:
            key = _pg_match_key(canonical)
            variants = _pg_alias_variants(canonical)
            for variant in variants:
                alias_to_key[_pg_match_key(variant)] = key
        # Explicit historical/batch aliases seen in the validation input.
        for alias, canonical_like in _EXPLICIT_CANONICAL_ALIAS_TEXT.items():
            canonical_key = _pg_match_key(canonical_like)
            if canonical_key in self._canonical_by_key:
                alias_to_key[_pg_match_key(alias)] = canonical_key
        return alias_to_key

    def _match_rows_for_pg(self, pg_name: str) -> list[dict[str, Any]]:
        canonical = self.resolve_pg_name(pg_name)
        canonical_key = _pg_match_key(canonical)
        return [row for row in self.rows if _pg_match_key(row.get("PG_name")) == canonical_key]

    def filter_rows(
        self,
        *,
        pg_name: str | None = None,
        feature_names: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        rows = list(self.rows)
        if pg_name:
            rows = self._match_rows_for_pg(pg_name)
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


def _pg_similarity(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence = SequenceMatcher(None, left, right).ratio()
    return max(overlap, sequence)


_STOPWORDS = {"pg", "product", "group", "toy", "toys"}
_TOKEN_REPLACEMENTS = {
    "misc": "miscellaneous",
    "miscellaneous": "miscellaneous",
    "educat": "educat",
    "electr": "electr",
    "leis": "leis",
    "vehicle": "vehicle",
    "vehicles": "vehicle",
    "playset": "playset",
    "playsets": "playset",
    "figure": "figure",
    "figures": "figure",
    "game": "game",
    "games": "game",
    "puzzle": "puzzle",
    "puzzles": "puzzle",
    "doll": "doll",
    "dolls": "doll",
    "craft": "craft",
    "crafts": "craft",
    "puppet": "puppet",
    "puppets": "puppet",
    "sport": "sport",
    "sports": "sport",
}


def _pg_match_key(value: Any) -> str:
    raw = str(value or "").lower()
    # Normalize common abbreviations before token extraction.
    raw = raw.replace("misc.", "miscellaneous")
    raw = raw.replace("misc ", "miscellaneous ")
    raw = raw.replace("misc/", "miscellaneous/")
    tokens = re.findall(r"[a-z0-9]+", raw)
    normalized: list[str] = []
    for token in tokens:
        if token in _STOPWORDS:
            continue
        token = _TOKEN_REPLACEMENTS.get(token, token)
        token = _singularize_token(token)
        if token and token not in _STOPWORDS:
            normalized.append(token)
    return " ".join(normalized)


def _singularize_token(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "ous")):
        return token[:-1]
    return token


_EXPLICIT_CANONICAL_ALIAS_TEXT = {
    "ALL OTHER MISC. TOYS": "All Other Miscellaneous Toys",
    "ALL OTHER MISC TOYS": "All Other Miscellaneous Toys",
    "ALL OTHER MISCELLANEOUS TOYS": "All Other Miscellaneous Toys",
    "TOY VEHICLES/PLAYSET": "Vehicles / Playsets",
    "TOY VEHICLES PLAYSET": "Vehicles / Playsets",
    "TOY VEHICLES/PLAYSETS": "Vehicles / Playsets",
    "VEHICLES/PLAYSET": "Vehicles / Playsets",
    "VEHICLES PLAYSET": "Vehicles / Playsets",
    "INFANT/PRESCHOOL TOY": "Infant / Preschool Toys",
    "INFANT PRESCHOOL TOY": "Infant / Preschool Toys",
    "INFANT/PRESCHOOL TOYS": "Infant / Preschool Toys",
    "FIGURES/BUILD SETS": "Figures/Build Sets",
    "FIGURES BUILD SETS": "Figures/Build Sets",
    "GAMES/PUZZLES": "Games/Puzzles",
    "GAMES PUZZLES": "Games/Puzzles",
    "DOLLS/FASHION TOYS": "Dolls/Fashion Toys",
    "DOLLS FASHION TOYS": "Dolls/Fashion Toys",
    "ELECTR/EDUCAT TOYS": "Electr/Educat Toys",
    "ELECTR EDUCAT TOYS": "Electr/Educat Toys",
    "PRETEND PLAY": "Pretend Play",
    "ARTS/CRAFTS TOYS": "ARTS/CRAFTS TOYS",
    "ARTS CRAFTS TOYS": "ARTS/CRAFTS TOYS",
    "PLUSH/PUPPETS TOYS": "PLUSH/PUPPETS TOYS",
    "PLUSH PUPPETS TOYS": "PLUSH/PUPPETS TOYS",
    "SPORTS/LEIS. TOYS": "SPORTS/LEIS. TOYS",
    "SPORTS LEIS. TOYS": "SPORTS/LEIS. TOYS",
}

_BUILTIN_PG_ALIASES = {
    _pg_match_key(alias): _pg_match_key(canonical)
    for alias, canonical in _EXPLICIT_CANONICAL_ALIAS_TEXT.items()
}


def _pg_alias_variants(canonical_name: str) -> list[str]:
    """Generate likely legacy aliases from a canonical PG name."""
    name = canonical_name.strip()
    no_slash = re.sub(r"[/]+", " ", name)
    no_punct = re.sub(r"[^A-Za-z0-9]+", " ", name)
    variants = {name, no_slash, no_punct, no_punct.upper()}
    if "Miscellaneous" in name:
        variants.add(name.replace("Miscellaneous", "Misc."))
        variants.add(name.replace("Miscellaneous", "Misc"))
    if "Vehicles" in name:
        variants.add("TOY VEHICLES/PLAYSET")
        variants.add("TOY VEHICLES/PLAYSETS")
    if "Infant" in name and "Preschool" in name:
        variants.add("INFANT/PRESCHOOL TOY")
        variants.add("INFANT/PRESCHOOL TOYS")
    return list(variants)


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


def _unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = _pg_match_key(value)
        if value and key not in seen:
            out.append(value)
            seen.add(key)
    return out


__all__ = ["PGFeatureInputError", "PGFeatureInputProvider", "row_to_feature_rule"]
