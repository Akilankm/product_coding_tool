"""Manual-review gate and loop convergence policy."""

from __future__ import annotations

from ..config import get_config
from ..models import EvidencePacket, FeatureCodingResult, FeatureRule


class ReviewGate:
    def __init__(self) -> None:
        self.cfg = get_config()

    def should_collect_more(
        self,
        feature: FeatureRule,
        packet: EvidencePacket,
        result: FeatureCodingResult,
        *,
        iteration: int,
        max_iterations: int | None = None,
    ) -> bool:
        limit = max(1, max_iterations or self.cfg.coding_max_iterations)
        if iteration >= limit:
            return False
        if not result.manual_review:
            return False
        if not packet.evidence:
            return False
        # Loop once more for weak evidence, invalid closed-set mapping, or conflicts.
        if result.conflicts:
            return True
        if feature.feature_type == "closed_set" and result.validation_status != "valid":
            return True
        if result.confidence < self.cfg.coding_min_confidence and len(packet.evidence) < self.cfg.coding_max_evidence_items:
            return True
        return False

    def strengthen_plan_queries(self, feature: FeatureRule, result: FeatureCodingResult) -> list[str]:
        queries = list(feature.evidence_terms)
        queries.extend(feature.allowed_values)
        if result.coded_value:
            queries.append(result.coded_value)
        for conflict in result.conflicts:
            queries.extend(conflict.split()[:6])
        for missing in result.missing_evidence:
            queries.extend(missing.split()[:6])
        return _dedupe([q for q in queries if q])


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        cleaned = (value or "").strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            out.append(cleaned)
            seen.add(key)
    return out


__all__ = ["ReviewGate"]
