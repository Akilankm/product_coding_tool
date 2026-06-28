"""Evidence packet builder for feature-specific coding."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Iterable

from ..config import get_config
from ..log import logger
from ..models import ArtifactInventory, EvidenceItem, EvidencePacket, EvidencePlan, FeatureRule
from .navigator import ArtifactNavigator
from .reader import ArtifactReader
from .locator import ArtifactEvidenceLocator


class EvidencePacketBuilder:
    def __init__(self, navigator: ArtifactNavigator, reader: ArtifactReader | None = None) -> None:
        self.navigator = navigator
        self.reader = reader or ArtifactReader(navigator)
        self.locator = ArtifactEvidenceLocator(navigator, self.reader)
        self.cfg = get_config()

    def build(self, feature: FeatureRule, inventory: ArtifactInventory, plan: EvidencePlan) -> EvidencePacket:
        files_checked: list[str] = []
        missing_files: list[str] = []
        evidence: list[EvidenceItem] = []
        evidence_id = 1

        for rel in self._expand_files(plan.files_to_read, inventory):
            if rel in files_checked:
                continue
            if not self.reader.exists(rel):
                missing_files.append(rel)
                continue
            files_checked.append(rel)
            try:
                text = self.reader.read_any_as_text(rel, max_chars=self.cfg.coding_read_file_chars)
            except Exception as exc:
                missing_files.append(f"{rel} ({exc})")
                continue
            if not text.strip():
                continue
            evidence.append(
                EvidenceItem(
                    evidence_id=f"E{evidence_id:03d}",
                    source_file=rel,
                    evidence_type=self._evidence_type_for(rel),
                    text=text,
                    score=100.0 / max(1, len(files_checked)),
                    strength="strong" if self._strong_source(rel) else "medium",
                )
            )
            evidence_id += 1

        # Add targeted artifact snippets from all artifact docs.
        queries = plan.evidence_queries or feature.evidence_terms
        located_items = self.locator.locate_as_evidence(
            queries,
            inventory=inventory,
            start_index=evidence_id,
            max_hits=max(4, self.cfg.coding_max_evidence_items - len(evidence)),
        )
        for item in located_items:
            key = (item.source_file, item.text[:200])
            if any((e.source_file, e.text[:200]) == key for e in evidence):
                continue
            evidence.append(item)

        # Add vision markdown/image manifest when requested or feature rule hints visual need.
        if plan.needs_vision or feature.requires_visual:
            for rel in ["retailer/vision.md", "retailer/manifests/image_manifest.json"]:
                if self.reader.exists(rel) and rel not in files_checked:
                    try:
                        text = self.reader.read_any_as_text(rel, max_chars=self.cfg.coding_read_file_chars)
                        evidence.append(
                            EvidenceItem(
                                evidence_id=f"E{len(evidence)+1:03d}",
                                source_file=rel,
                                evidence_type="vision" if rel.endswith(".md") else "image_manifest",
                                text=text,
                                score=25.0,
                                strength="medium",
                            )
                        )
                        files_checked.append(rel)
                    except Exception as exc:
                        missing_files.append(f"{rel} ({exc})")

        evidence = self._trim_evidence(evidence)
        product_context = self.reader.read_product_context()
        quality_signals = self.reader.read_quality_signals()

        if not evidence:
            missing = [f"No artifact evidence found for feature '{feature.feature_name}'."]
        else:
            missing = []

        logger.info(
            "Evidence packet feature={} evidence_items={} files_checked={}",
            feature.feature_name,
            len(evidence),
            len(files_checked),
        )
        return EvidencePacket(
            artifact_id=self.navigator.artifact_id,
            feature_id=feature.feature_id,
            feature_name=feature.feature_name,
            plan=plan,
            product_context=product_context,
            evidence=evidence,
            files_checked=files_checked,
            missing_files=missing_files,
            missing_evidence=missing,
            quality_signals=quality_signals,
        )

    def _expand_files(self, patterns: Iterable[str], inventory: ArtifactInventory) -> list[str]:
        out: list[str] = []
        available = [f.relative_path for f in inventory.files]
        for pattern in patterns:
            rel = (pattern or "").replace("\\", "/").strip()
            if not rel:
                continue
            if any(ch in rel for ch in "*?["):
                out.extend([p for p in available if fnmatch.fnmatch(p, rel)])
            else:
                out.append(rel)
        # Default strong sources even if LLM planner omitted them.
        defaults = [
            "retailer/source.md",
            "retailer/tables/*.md",
            "retailer/metadata.json",
            "retailer/product_evidence.json",
            "retailer/claims.md",
        ]
        for pattern in defaults:
            if any(ch in pattern for ch in "*?["):
                out.extend([p for p in available if fnmatch.fnmatch(p, pattern)])
            else:
                out.append(pattern)
        seen: set[str] = set()
        deduped: list[str] = []
        for rel in out:
            if rel not in seen:
                deduped.append(rel)
                seen.add(rel)
        return deduped

    def _trim_evidence(self, evidence: list[EvidenceItem]) -> list[EvidenceItem]:
        evidence.sort(key=lambda e: (-e.score, e.source_file, e.evidence_id))
        max_items = self.cfg.coding_max_evidence_items
        max_chars = self.cfg.coding_max_evidence_chars
        out: list[EvidenceItem] = []
        total = 0
        for idx, item in enumerate(evidence[: max_items * 2], start=1):
            text = item.text
            if total + len(text) > max_chars:
                remaining = max_chars - total
                if remaining < 500:
                    break
                text = text[:remaining] + "\n...[truncated]"
            out.append(item.model_copy(update={"evidence_id": f"E{idx:03d}", "text": text}))
            total += len(text)
            if len(out) >= max_items:
                break
        return out

    @staticmethod
    def _strong_source(rel: str) -> bool:
        return rel in {"retailer/source.md", "retailer/metadata.json"} or rel.startswith("retailer/tables/")

    @staticmethod
    def _evidence_type_for(rel: str) -> str:
        if rel.startswith("retailer/tables/"):
            return "table"
        if rel.endswith(".json"):
            return "json"
        if rel.endswith("vision.md"):
            return "vision"
        if rel.endswith("claims.md"):
            return "claims"
        if rel.endswith("source.md"):
            return "source_text"
        return "text"


__all__ = ["EvidencePacketBuilder"]
