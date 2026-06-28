"""Safe readers for scrape artifact files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..log import logger
from .navigator import ArtifactNavigator


class ArtifactReader:
    def __init__(self, navigator: ArtifactNavigator) -> None:
        self.navigator = navigator

    def exists(self, relative_path: str) -> bool:
        return self.navigator.abs(relative_path).is_file()

    def read_text(self, relative_path: str, *, max_chars: int | None = None) -> str:
        path = self.navigator.abs(relative_path)
        if not path.exists():
            raise FileNotFoundError(relative_path)
        text = path.read_text(encoding="utf-8", errors="replace")
        if max_chars and len(text) > max_chars:
            return text[:max_chars] + "\n...[truncated]"
        return text

    def read_json(self, relative_path: str, *, max_chars: int | None = None) -> dict[str, Any] | list[Any]:
        text = self.read_text(relative_path, max_chars=max_chars)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in {}. Returning text wrapper.", relative_path)
            return {"_invalid_json_text": text}

    def read_any_as_text(self, relative_path: str, *, max_chars: int | None = None) -> str:
        path = self.navigator.abs(relative_path)
        if path.suffix.lower() == ".json":
            obj = self.read_json(relative_path, max_chars=max_chars)
            text = json.dumps(obj, ensure_ascii=False, indent=2)
            if max_chars and len(text) > max_chars:
                return text[:max_chars] + "\n...[truncated]"
            return text
        return self.read_text(relative_path, max_chars=max_chars)

    def read_tables(self, *, max_chars_per_table: int = 12_000) -> dict[str, str]:
        out: dict[str, str] = {}
        for path in self.navigator.glob("retailer/tables/*.md"):
            rel = self.navigator.rel(path)
            out[rel] = self.read_text(rel, max_chars=max_chars_per_table)
        return out

    def read_product_context(self, *, max_chars: int = 20_000) -> dict[str, Any]:
        context: dict[str, Any] = {}
        for rel in ["request.json", "scrape_result.json", "retailer/metadata.json", "retailer/product_evidence.json"]:
            if self.exists(rel):
                try:
                    context[rel] = self.read_json(rel, max_chars=max_chars)
                except Exception as exc:
                    context[rel] = {"_read_error": str(exc)}
        return context

    def read_quality_signals(self, *, max_chars: int = 12_000) -> dict[str, Any]:
        signals: dict[str, Any] = {}
        for rel in [
            "retailer/quality_report.json",
            "retailer/noise_report.json",
            "retailer/evidence_recovery_report.json",
            "retailer/manifests/agent_trace.json",
        ]:
            if self.exists(rel):
                try:
                    signals[rel] = self.read_json(rel, max_chars=max_chars)
                except Exception as exc:
                    signals[rel] = {"_read_error": str(exc)}
        return signals


__all__ = ["ArtifactReader"]
