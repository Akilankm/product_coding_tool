"""Product-level artifact context index.

The coding agent may code many features for the same product artifact. Reading and
scanning the same source/claims/metadata files for every feature is wasteful even
when file contents are cached. This module builds one product-level in-memory
context index, then feature evidence lookup reuses that index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import get_config
from ..log import logger
from ..models import ArtifactInventory
from .contract import priority_for
from .navigator import ArtifactNavigator
from .reader import ArtifactReader


@dataclass(frozen=True)
class ProductArtifactContext:
    artifact_id: str
    locatable_files: list[str] = field(default_factory=list)
    file_texts: dict[str, str] = field(default_factory=dict)
    product_context: dict[str, Any] = field(default_factory=dict)
    quality_signals: dict[str, Any] = field(default_factory=dict)
    artifact_quality_report: dict[str, Any] = field(default_factory=dict)
    missing_expected_files: list[str] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.file_texts)

    @property
    def total_text_chars(self) -> int:
        return sum(len(v or "") for v in self.file_texts.values())

    def read_text(self, relative_path: str, *, max_chars: int | None = None) -> str:
        rel = (relative_path or "").replace("\\", "/").strip()
        text = self.file_texts.get(rel, "")
        if max_chars and len(text) > max_chars:
            return text[:max_chars] + "\n...[truncated]"
        return text


class ProductArtifactContextBuilder:
    """Build a reusable per-product context packet from local scrape artifacts."""

    def __init__(self, navigator: ArtifactNavigator, reader: ArtifactReader | None = None) -> None:
        self.navigator = navigator
        self.reader = reader or ArtifactReader(navigator)
        self.cfg = get_config()

    def build(self, inventory: ArtifactInventory) -> ProductArtifactContext:
        locatable = self._locatable_files(inventory)
        file_texts: dict[str, str] = {}
        for rel in locatable:
            try:
                text = self.reader.read_any_as_text(rel, max_chars=self.cfg.coding_context_index_file_chars)
            except Exception as exc:  # noqa: BLE001 - keep one bad file from breaking a product.
                logger.warning("Context index skipped unreadable file artifact={} file={} error={}", inventory.artifact_id, rel, exc)
                continue
            if text.strip():
                file_texts[rel] = text

        product_context = self.reader.read_product_context()
        quality_signals = self.reader.read_quality_signals()
        artifact_quality_report = self.reader.quality_report().to_dict()
        context = ProductArtifactContext(
            artifact_id=inventory.artifact_id,
            locatable_files=[rel for rel in locatable if rel in file_texts],
            file_texts=file_texts,
            product_context=product_context,
            quality_signals=quality_signals,
            artifact_quality_report=artifact_quality_report,
            missing_expected_files=list(inventory.missing_expected_files),
        )
        logger.info(
            "Product artifact context built artifact={} files={} chars={} warnings={} missing_expected={}",
            context.artifact_id,
            context.file_count,
            context.total_text_chars,
            artifact_quality_report.get("warning_count", 0),
            len(context.missing_expected_files),
        )
        return context

    @staticmethod
    def _locatable_files(inventory: ArtifactInventory) -> list[str]:
        allowed_types = {"markdown", "json"}
        files = [f for f in inventory.files if f.file_type in allowed_types]
        files.sort(key=lambda f: (priority_for(f.relative_path), f.relative_path))
        seen: set[str] = set()
        out: list[str] = []
        for file in files:
            rel = file.relative_path.replace("\\", "/")
            if rel not in seen:
                out.append(rel)
                seen.add(rel)
        return out


__all__ = ["ProductArtifactContext", "ProductArtifactContextBuilder"]
