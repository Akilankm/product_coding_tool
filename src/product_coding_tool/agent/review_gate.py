"""Manual-review gate and loop convergence policy."""

from __future__ import annotations

from ..config import get_config
from ..models import EvidencePacket, FeatureCodingResult, FeatureRule


class ReviewGate:
    def __init__(self) -> None:
        self.cfg = get_config()

    def evaluate(
        self,
        feature: FeatureRule,
        packet: EvidencePacket,
        result: FeatureCodingResult,
        *,
        iteration: int,
        max_iterations: int | None = None,
    ) -> tuple[bool, str]:
        """Return whether another evidence/coding pass is justified and why.

        The previous behavior retried too aggressively, especially when a
        closed-set value was simply outside the allowed list. That duplicated
        large LLM calls without adding new evidence. This gate retries only when
        there is a plausible path to stronger evidence.
        """
        limit = max(1, max_iterations or self.cfg.coding_max_iterations)
        if iteration >= limit:
            return False, "max_iterations_reached"
        if not result.manual_review:
            return False, "accepted_no_manual_review"
        if not packet.evidence:
            return False, "no_evidence_available_for_retry"

        evidence_capacity_available = len(packet.evidence) < self.cfg.coding_max_evidence_items
        closed_set_allowed_value_conflict = feature.feature_type == "closed_set" and any(
            "not in allowed_values" in c for c in (result.conflicts or [])
        )
        if closed_set_allowed_value_conflict:
            return False, "closed_set_value_not_allowed_mark_manual_review_no_retry"

        if result.conflicts:
            if evidence_capacity_available:
                return True, "conflicts_present_collect_more_evidence"
            return False, "conflicts_present_but_evidence_capacity_reached"

        if feature.feature_type == "closed_set" and result.validation_status != "valid":
            if evidence_capacity_available and result.missing_evidence:
                return True, "closed_set_needs_review_and_missing_evidence"
            return False, "closed_set_needs_review_no_productive_retry"

        if result.confidence < self.cfg.coding_min_confidence:
            if evidence_capacity_available and result.missing_evidence:
                return True, "low_confidence_collect_more_evidence"
            return False, "low_confidence_no_productive_retry"

        return False, "review_gate_converged"

    def should_collect_more(
        self,
        feature: FeatureRule,
        packet: EvidencePacket,
        result: FeatureCodingResult,
        *,
        iteration: int,
        max_iterations: int | None = None,
    ) -> bool:
        should_retry, _reason = self.evaluate(feature, packet, result, iteration=iteration, max_iterations=max_iterations)
        return should_retry

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
