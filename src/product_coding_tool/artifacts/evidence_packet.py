"""Evidence packet builder for feature-specific coding."""

from __future__ import annotations

import fnmatch
from typing import Iterable

from ..config import get_config
from ..log import logger
from ..models import ArtifactInventory, EvidenceItem, EvidencePacket, EvidencePlan, FeatureRule
from .locator import ArtifactEvidenceLocator, compact_snippet
from .navigator import ArtifactNavigator
from .reader import ArtifactReader


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
                raw_text = self.reader.read_any_as_text(rel, max_chars=self.cfg.coding_read_file_chars)
                text = self._compact_file_text(rel, raw_text, feature, plan)
            except Exception as exc:  # noqa: BLE001 - keep product/feature isolation.
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
                    metadata={"compacted": len(text) < len(raw_text), "raw_chars": len(raw_text), "sent_chars": len(text)},
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
                        raw_text = self.reader.read_any_as_text(rel, max_chars=self.cfg.coding_read_file_chars)
                        text = self._compact_file_text(rel, raw_text, feature, plan)
                        evidence.append(
                            EvidenceItem(
                                evidence_id=f"E{len(evidence)+1:03d}",
                                source_file=rel,
                                evidence_type="vision" if rel.endswith(".md") else "image_manifest",
                                text=text,
                                score=25.0,
                                strength="medium",
                                metadata={"compacted": len(text) < len(raw_text), "raw_chars": len(raw_text), "sent_chars": len(text)},
                            )
                        )
                        files_checked.append(rel)
                    except Exception as exc:  # noqa: BLE001
                        missing_files.append(f"{rel} ({exc})")

        evidence = self._trim_evidence(evidence)
        product_context = self.reader.read_product_context()
        quality_signals = self.reader.read_quality_signals()

        if not evidence:
            missing = [f"No artifact evidence found for feature '{feature.feature_name}'."]
        else:
            missing = []

        total_chars = sum(len(e.text or "") for e in evidence)
        logger.info(
            "Evidence packet feature={} evidence_items={} files_checked={} evidence_chars={} artifact_warnings={}",
            feature.feature_name,
            len(evidence),
            len(files_checked),
            total_chars,
            self.reader.quality_report().warning_count,
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

    def _compact_file_text(self, rel: str, text: str, feature: FeatureRule, plan: EvidencePlan) -> str:
        """Send feature-relevant snippets instead of whole artifact files.

        Full source/metadata files are useful for retrieval, but sending them
        wholesale to every feature causes 25k-30k-token prompts. This keeps a
        small header plus matched snippets around feature/allowed-value terms.
        """
        if not text:
            return ""
        hard_cap = max(900, min(self.cfg.coding_read_file_chars, self.cfg.coding_evidence_context_chars * 3))
        if len(text) <= hard_cap:
            return text
        terms = _evidence_terms(feature, plan)
        snippets: list[str] = []
        header = text[: min(500, hard_cap // 3)].strip()
        if header:
            snippets.append(f"[file_start]\n{header}")
        lowered = text.lower()
        for term in terms:
            if not term or term.lower() not in lowered:
                continue
            snippet = compact_snippet(text, [term], context_chars=self.cfg.coding_evidence_context_chars)
            if snippet and all(snippet[:160] not in existing for existing in snippets):
                snippets.append(f"[matched_term={term}]\n{snippet}")
            if sum(len(s) for s in snippets) >= hard_cap:
                break
        if len(snippets) == 1:
            # No term hit. Preserve leading content only.
            return text[:hard_cap].strip() + "\n...[truncated: no feature-specific term hit]"
        compacted = "\n\n".join(snippets)
        if len(compacted) > hard_cap:
            compacted = compacted[:hard_cap] + "\n...[truncated: compact evidence cap]"
        return compacted

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
        return any(
            rel.endswith(x)
            for x in [
                "source.md",
                "product_evidence.json",
                "product_evidence.md",
                "claims.md",
            ]
        ) or "/tables/" in rel

    @staticmethod
    def _evidence_type_for(rel: str) -> str:
        if "/tables/" in rel:
            return "table"
        if rel.endswith(".json"):
            return "json"
        if rel.endswith("vision.md"):
            return "vision"
        return "text"


def _evidence_terms(feature: FeatureRule, plan: EvidencePlan) -> list[str]:
    terms = [feature.feature_name, *feature.evidence_terms, *(plan.evidence_queries or [])]
    terms.extend(feature.allowed_values or [])
    # Keep only useful non-trivial terms, longest first for better snippets.
    seen: set[str] = set()
    out: list[str] = []
    for term in sorted(terms, key=lambda x: len(str(x or "")), reverse=True):
        cleaned = " ".join(str(term or "").strip().split())
        key = cleaned.lower()
        if len(key) >= 2 and key not in seen:
            out.append(cleaned)
            seen.add(key)
    return out[:40]


__all__ = ["EvidencePacketBuilder"]
