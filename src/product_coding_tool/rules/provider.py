"""Load feature rules from JSON/CSV/inline Python objects."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from ..models import FeatureRule
from .pg_input import PGFeatureInputProvider


class FeatureRuleProvider:
    """Small adapter around rulebook-derived feature definitions."""

    def __init__(self, rules: Iterable[FeatureRule] | None = None) -> None:
        self._rules: dict[str, FeatureRule] = {}
        for rule in rules or []:
            self.add(rule)

    def add(self, rule: FeatureRule) -> None:
        self._rules[rule.feature_id] = rule
        self._rules[rule.feature_name.lower()] = rule
        for alias in rule.aliases:
            self._rules[alias.lower()] = rule

    def get(self, key: str) -> FeatureRule:
        cleaned = (key or "").strip()
        if cleaned in self._rules:
            return self._rules[cleaned]
        lowered = cleaned.lower()
        if lowered in self._rules:
            return self._rules[lowered]
        raise KeyError(f"Feature rule not found: {key}")

    def all(self) -> list[FeatureRule]:
        seen: dict[str, FeatureRule] = {}
        for rule in self._rules.values():
            seen[rule.feature_id] = rule
        return list(seen.values())

    @classmethod
    def from_json(cls, path: str | Path) -> "FeatureRuleProvider":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict) and "features" in data:
            rows = data["features"]
        elif isinstance(data, list):
            rows = data
        else:
            raise ValueError("Rules JSON must be a list or an object with `features`.")
        return cls(FeatureRule.model_validate(row) for row in rows)

    @classmethod
    def from_csv(cls, path: str | Path) -> "FeatureRuleProvider":
        rules: list[FeatureRule] = []
        with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                allowed = _split_list(row.get("allowed_values", ""))
                aliases = _split_list(row.get("aliases", ""))
                hints = _split_list(row.get("evidence_hints", ""))
                rules.append(
                    FeatureRule(
                        feature_id=row.get("feature_id") or row.get("id") or row.get("feature_name") or "",
                        feature_name=row.get("feature_name") or row.get("name") or "",
                        feature_type=(row.get("feature_type") or row.get("type") or "open_set").strip(),
                        definition=row.get("definition", ""),
                        allowed_values=allowed,
                        aliases=aliases,
                        evidence_hints=hints,
                        requires_visual=str(row.get("requires_visual", "")).lower() in {"1", "true", "yes", "y"},
                    )
                )
        return cls(rules)

    @classmethod
    def from_pg_input(
        cls,
        path: str | Path,
        *,
        pg_name: str | None = None,
        feature_names: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> "FeatureRuleProvider":
        provider = PGFeatureInputProvider.from_file(path)
        return cls(
            provider.features_for_pg(
                pg_name=pg_name,
                feature_names=feature_names,
                limit=limit,
            )
        )


def _split_list(value: str) -> list[str]:
    if not value:
        return []
    # Support both semicolon and pipe from Excel-friendly CSVs.
    raw = value.replace("|", ";").split(";")
    return [x.strip() for x in raw if x.strip()]


__all__ = ["FeatureRuleProvider"]
