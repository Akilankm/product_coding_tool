"""Safe, cached readers for scrape artifact files.

The scrape artifacts are produced by a different tool, so the product-coding
agent must be tolerant of imperfect files. In practice some artifacts have a
`.json` suffix but contain markdown, an HTML/error body, a Python-dict string,
or a partially-written JSON payload. This reader therefore:

* reads each artifact file at most once per product run;
* attempts strict JSON, then a small set of safe lenient JSON repairs;
* falls back to text for malformed JSON without failing feature coding;
* records artifact-quality warnings once per file for clean audit output.
"""

from __future__ import annotations

import ast
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..log import logger
from .navigator import ArtifactNavigator


@dataclass
class ArtifactQualityWarning:
    """One non-fatal quality finding discovered while reading an artifact file."""

    relative_path: str
    issue_type: str
    message: str
    bytes_size: int = 0
    recovered: bool = False
    fallback_mode: str = ""
    parse_error: str = ""


@dataclass
class ArtifactReadQualityReport:
    """Summary of reader-level artifact quality for one product artifact."""

    artifact_id: str
    malformed_json_files: list[dict[str, Any]] = field(default_factory=list)
    recovered_json_files: list[dict[str, Any]] = field(default_factory=list)
    read_error_files: list[dict[str, Any]] = field(default_factory=list)

    @property
    def warning_count(self) -> int:
        return len(self.malformed_json_files) + len(self.recovered_json_files) + len(self.read_error_files)

    @property
    def has_warnings(self) -> bool:
        return self.warning_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "has_warnings": self.has_warnings,
            "warning_count": self.warning_count,
            "malformed_json_files": self.malformed_json_files,
            "recovered_json_files": self.recovered_json_files,
            "read_error_files": self.read_error_files,
        }


class ArtifactReader:
    def __init__(self, navigator: ArtifactNavigator) -> None:
        self.navigator = navigator
        self._text_cache: dict[str, str] = {}
        self._json_cache: dict[str, Any] = {}
        self._warnings: dict[tuple[str, str], ArtifactQualityWarning] = {}
        self._lock = threading.RLock()

    def exists(self, relative_path: str) -> bool:
        return self.navigator.abs(relative_path).is_file()

    def read_text(self, relative_path: str, *, max_chars: int | None = None) -> str:
        rel = _clean_rel(relative_path)
        with self._lock:
            if rel in self._text_cache:
                text = self._text_cache[rel]
            else:
                path = self.navigator.abs(rel)
                if not path.exists():
                    raise FileNotFoundError(rel)
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    self._text_cache[rel] = text
                except Exception as exc:  # noqa: BLE001 - keep artifact runs isolated and auditable.
                    self._record_warning(
                        rel,
                        issue_type="read_error",
                        message=f"Could not read artifact file: {exc}",
                        recovered=False,
                        fallback_mode="unavailable",
                        parse_error=str(exc),
                    )
                    raise
        return _truncate(text, max_chars)

    def read_json(self, relative_path: str, *, max_chars: int | None = None) -> dict[str, Any] | list[Any]:
        """Read JSON with strict parse, lenient recovery, then text fallback.

        The returned fallback wrapper is intentionally explicit so downstream
        audits can tell this was not structured JSON. `read_any_as_text` unwraps
        this back to raw text to avoid token bloat in LLM prompts.
        """
        rel = _clean_rel(relative_path)
        cache_key = f"{rel}::{max_chars or 'full'}"
        with self._lock:
            if cache_key in self._json_cache:
                return self._json_cache[cache_key]

        text = self.read_text(rel, max_chars=max_chars)
        try:
            parsed = json.loads(text)
            with self._lock:
                self._json_cache[cache_key] = parsed
            return parsed
        except json.JSONDecodeError as strict_exc:
            recovered = _try_recover_json(text)
            if recovered is not None:
                self._record_warning(
                    rel,
                    issue_type="recovered_json",
                    message="Non-standard JSON was recovered with safe lenient parsing.",
                    recovered=True,
                    fallback_mode="lenient_json",
                    parse_error=str(strict_exc),
                )
                with self._lock:
                    self._json_cache[cache_key] = recovered
                return recovered

            wrapper = {
                "_artifact_reader_status": "malformed_json_fallback_text",
                "_source_file": rel,
                "_parse_error": str(strict_exc),
                "_invalid_json_text": text,
            }
            self._record_warning(
                rel,
                issue_type="malformed_json",
                message="File has .json suffix but is not valid JSON; product coding used text fallback.",
                recovered=True,
                fallback_mode="text_wrapper",
                parse_error=str(strict_exc),
            )
            with self._lock:
                self._json_cache[cache_key] = wrapper
            return wrapper

    def read_any_as_text(self, relative_path: str, *, max_chars: int | None = None) -> str:
        rel = _clean_rel(relative_path)
        path = self.navigator.abs(rel)
        if path.suffix.lower() == ".json":
            obj = self.read_json(rel, max_chars=max_chars)
            # Avoid serializing a whole fallback wrapper into LLM prompts. The raw
            # file text is the useful evidence; the quality report stores the defect.
            if isinstance(obj, dict) and obj.get("_artifact_reader_status") == "malformed_json_fallback_text":
                return _truncate(str(obj.get("_invalid_json_text") or ""), max_chars)
            text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            return _truncate(text, max_chars)
        return self.read_text(rel, max_chars=max_chars)

    def read_tables(self, *, max_chars_per_table: int = 12_000) -> dict[str, str]:
        out: dict[str, str] = {}
        for path in self.navigator.glob("retailer/tables/*.md"):
            rel = self.navigator.rel(path)
            out[rel] = self.read_text(rel, max_chars=max_chars_per_table)
        return out

    def read_product_context(self, *, max_chars: int = 6_000) -> dict[str, Any]:
        context: dict[str, Any] = {}
        for rel in ["request.json", "scrape_result.json", "retailer/metadata.json", "retailer/product_evidence.json"]:
            if self.exists(rel):
                try:
                    context[rel] = self.read_json(rel, max_chars=max_chars)
                except Exception as exc:  # noqa: BLE001 - non-fatal artifact issue.
                    self._record_warning(
                        rel,
                        issue_type="read_error",
                        message=f"Could not read product context file: {exc}",
                        recovered=False,
                        fallback_mode="unavailable",
                        parse_error=str(exc),
                    )
                    context[rel] = {"_read_error": str(exc)}
        return context

    def read_quality_signals(self, *, max_chars: int = 4_000) -> dict[str, Any]:
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
                except Exception as exc:  # noqa: BLE001 - non-fatal artifact issue.
                    self._record_warning(
                        rel,
                        issue_type="read_error",
                        message=f"Could not read quality signal file: {exc}",
                        recovered=False,
                        fallback_mode="unavailable",
                        parse_error=str(exc),
                    )
                    signals[rel] = {"_read_error": str(exc)}
        report = self.quality_report().to_dict()
        if report["has_warnings"]:
            signals["_artifact_reader_quality"] = report
        return signals

    def quality_report(self) -> ArtifactReadQualityReport:
        with self._lock:
            warnings = list(self._warnings.values())
        report = ArtifactReadQualityReport(artifact_id=self.navigator.artifact_id)
        for warning in sorted(warnings, key=lambda w: (w.relative_path, w.issue_type)):
            row = {
                "relative_path": warning.relative_path,
                "issue_type": warning.issue_type,
                "message": warning.message,
                "bytes_size": warning.bytes_size,
                "recovered": warning.recovered,
                "fallback_mode": warning.fallback_mode,
                "parse_error": warning.parse_error,
            }
            if warning.issue_type == "recovered_json":
                report.recovered_json_files.append(row)
            elif warning.issue_type == "read_error":
                report.read_error_files.append(row)
            else:
                report.malformed_json_files.append(row)
        return report

    def _record_warning(
        self,
        relative_path: str,
        *,
        issue_type: str,
        message: str,
        recovered: bool,
        fallback_mode: str,
        parse_error: str,
    ) -> None:
        rel = _clean_rel(relative_path)
        key = (rel, issue_type)
        path = self.navigator.abs(rel)
        bytes_size = path.stat().st_size if path.exists() else 0
        warning = ArtifactQualityWarning(
            relative_path=rel,
            issue_type=issue_type,
            message=message,
            bytes_size=bytes_size,
            recovered=recovered,
            fallback_mode=fallback_mode,
            parse_error=parse_error,
        )
        with self._lock:
            first = key not in self._warnings
            self._warnings.setdefault(key, warning)
        if first:
            if issue_type == "malformed_json":
                logger.warning("Invalid JSON in {}. Using text fallback once for this artifact.", rel)
            elif issue_type == "recovered_json":
                logger.info("Recovered non-standard JSON in {} using lenient parser.", rel)
            else:
                logger.warning("Artifact read issue in {}: {}", rel, message)


def _clean_rel(relative_path: str) -> str:
    return (relative_path or "").replace("\\", "/").strip()


def _truncate(text: str, max_chars: int | None) -> str:
    if max_chars and len(text) > max_chars:
        return text[:max_chars] + "\n...[truncated]"
    return text


def _try_recover_json(text: str) -> Any | None:
    cleaned = (text or "").strip().lstrip("\ufeff")
    if not cleaned:
        return {}
    # Some producers write fenced JSON blocks.
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
            inner = "\n".join(lines[1:-1]).strip()
            if inner.lower().startswith("json"):
                inner = inner[4:].strip()
            try:
                return json.loads(inner)
            except Exception:
                pass
    # Some buggy writers persist Python dict/list repr instead of JSON. ast.literal_eval
    # is safe for literals and does not execute code.
    if cleaned[:1] in {"{", "["}:
        try:
            value = ast.literal_eval(cleaned)
            if isinstance(value, (dict, list)):
                return value
        except Exception:
            pass
    # Some files contain log prelude/postlude around a JSON object. Recover only
    # unambiguous object/list boundaries.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = cleaned.find(open_ch)
        end = cleaned.rfind(close_ch)
        if 0 <= start < end:
            candidate = cleaned[start : end + 1]
            try:
                return json.loads(candidate)
            except Exception:
                pass
    return None


__all__ = ["ArtifactReader", "ArtifactReadQualityReport", "ArtifactQualityWarning"]
