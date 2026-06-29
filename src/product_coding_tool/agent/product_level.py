"""Fast product-level coding agent.

This agent targets high-throughput production runs: one bulk LLM call codes all
features for one product, deterministic validation checks every value, and only
weak/invalid features are selectively escalated to the existing per-feature loop.
"""

from __future__ import annotations

from typing import Any

from ..artifacts.context import ProductArtifactContextBuilder
from ..artifacts.navigator import ArtifactNavigator
from ..artifacts.reader import ArtifactReader
from ..config import get_config
from ..log import logger
from ..models import BatchCodingResult, CodingRequest, FeatureCodingResult, FeatureRule
from ..outputs.writer import ResultWriter
from .artifact_quality_gate import ArtifactQualityDecision, ArtifactQualityGate
from .coder import FeatureCoder
from .planner import EvidencePlanner
from .product_bulk_coder import ProductBulkCoder
from .retriever import EvidenceRetriever
from .review_gate import ReviewGate


class ProductLevelCodingAgent:
    """Code all product features using the fast one-call product-level path."""

    def __init__(self) -> None:
        self.cfg = get_config()
        self.bulk_coder = ProductBulkCoder()
        self.quality_gate = ArtifactQualityGate()
        self.planner = EvidencePlanner()
        self.coder = FeatureCoder()
        self.review_gate = ReviewGate()

    def run(self, request: CodingRequest) -> BatchCodingResult:
        navigator = ArtifactNavigator(request.artifact_dir)
        inventory = navigator.inventory()
        reader = ArtifactReader(navigator)
        product_context_index = ProductArtifactContextBuilder(navigator, reader).build(inventory)
        quality_decision = self.quality_gate.evaluate(product_context_index, request.features)
        product_id = request.product_id or str(request.product_context.get("input_id") or inventory.artifact_id)
        logger.info(
            "ProductLevelCodingAgent start artifact={} product_id={} features={} context_files={} context_chars={} quality_decision={} quality_score={} fallback_enabled={} fallback_limit={}",
            inventory.artifact_id,
            product_id,
            len(request.features),
            product_context_index.file_count,
            product_context_index.total_text_chars,
            quality_decision.decision,
            f"{quality_decision.score:.3f}",
            self.cfg.coding_bulk_fallback_enabled,
            self.cfg.coding_bulk_max_fallback_features,
        )

        retriever = EvidenceRetriever(navigator, reader, context=product_context_index)
        if not quality_decision.bulk_allowed:
            if quality_decision.full_product_fallback_required and self.cfg.coding_bulk_fallback_enabled:
                results = self._fallback_all_features(
                    request=request,
                    inventory=inventory,
                    retriever=retriever,
                    reason="artifact_quality_gate_full_product_fallback",
                )
            else:
                results = self._manual_review_results(
                    artifact_id=inventory.artifact_id,
                    features=request.features,
                    reason="artifact_quality_gate_blocked_bulk_coding",
                    quality_decision=quality_decision,
                )
        else:
            results = self.bulk_coder.code_many(
                artifact_id=inventory.artifact_id,
                features=request.features,
                product_context=request.product_context,
                context=product_context_index,
            )
            if self._is_systemic_bulk_failure(results, request.features):
                results = self._fallback_all_features(
                    request=request,
                    inventory=inventory,
                    retriever=retriever,
                    reason="systemic_bulk_failure_full_product_fallback",
                )
            else:
                results = self._fallback_weak_features(
                    results,
                    request=request,
                    inventory=inventory,
                    retriever=retriever,
                )

        self._apply_request_metadata(results, request=request, product_id=product_id)
        artifact_quality_report = product_context_index.artifact_quality_report or reader.quality_report().to_dict()
        self._attach_artifact_quality(results, artifact_quality_report)
        self._attach_quality_gate(results, quality_decision)
        out = BatchCodingResult(
            artifact_id=inventory.artifact_id,
            artifact_dir=navigator.artifact_root,
            results=results,
            output_dir=request.output_dir,
            product_id=product_id,
            product_context=request.product_context,
            artifact_quality_report={**artifact_quality_report, "quality_gate": quality_decision.to_dict()},
        )
        ResultWriter().write(out, output_dir=request.output_dir)
        logger.info(
            "ProductLevelCodingAgent complete artifact={} results={} fallback_count={} manual_review_count={} quality_decision={}",
            inventory.artifact_id,
            len(results),
            sum(1 for r in results if r.audit.get("fallback_from_bulk") or r.audit.get("full_product_fallback")),
            sum(1 for r in results if r.manual_review),
            quality_decision.decision,
        )
        return out

    def _fallback_weak_features(
        self,
        results: list[FeatureCodingResult],
        *,
        request: CodingRequest,
        inventory: Any,
        retriever: EvidenceRetriever,
    ) -> list[FeatureCodingResult]:
        if not self.cfg.coding_bulk_fallback_enabled or self.cfg.coding_bulk_max_fallback_features <= 0:
            return results
        feature_by_id = {f.feature_id: f for f in request.features}
        fallback_candidates = [r for r in results if self._needs_fallback(r)]
        fallback_candidates.sort(key=_fallback_priority)
        selected = fallback_candidates[: self.cfg.coding_bulk_max_fallback_features]
        if not selected:
            return results
        logger.info(
            "Product bulk fallback selected artifact={} selected={} candidates={} limit={}",
            inventory.artifact_id,
            [r.feature_name for r in selected],
            len(fallback_candidates),
            self.cfg.coding_bulk_max_fallback_features,
        )
        replacement_by_id: dict[str, FeatureCodingResult] = {}
        for weak in selected:
            feature = feature_by_id.get(weak.feature_id)
            if feature is None:
                continue
            try:
                fallback = self._code_feature_loop(feature, inventory, retriever, max_iterations=max(1, request.max_iterations))
                fallback.audit["fallback_from_bulk"] = True
                fallback.audit["bulk_result_before_fallback"] = weak.model_dump(mode="json")
                replacement_by_id[feature.feature_id] = fallback
            except Exception as exc:  # noqa: BLE001 - do not let fallback break product output.
                logger.exception("Per-feature fallback failed artifact={} feature={}", inventory.artifact_id, weak.feature_name)
                weak.audit["fallback_from_bulk_attempted"] = True
                weak.audit["fallback_from_bulk_error"] = str(exc)
        return [replacement_by_id.get(r.feature_id, r) for r in results]

    def _fallback_all_features(
        self,
        *,
        request: CodingRequest,
        inventory: Any,
        retriever: EvidenceRetriever,
        reason: str,
    ) -> list[FeatureCodingResult]:
        logger.warning(
            "Full-product per-feature fallback start artifact={} features={} reason={}",
            inventory.artifact_id,
            len(request.features),
            reason,
        )
        out: list[FeatureCodingResult] = []
        for feature in request.features:
            try:
                result = self._code_feature_loop(feature, inventory, retriever, max_iterations=max(1, request.max_iterations))
                result.audit["full_product_fallback"] = True
                result.audit["full_product_fallback_reason"] = reason
                out.append(result)
            except Exception as exc:  # noqa: BLE001 - keep one feature failure isolated.
                logger.exception("Full-product fallback feature failed artifact={} feature={}", inventory.artifact_id, feature.feature_name)
                out.append(self._manual_review_result(inventory.artifact_id, feature, f"{reason}: fallback feature failed: {exc}"))
        return out

    def _code_feature_loop(
        self,
        feature: FeatureRule,
        inventory: Any,
        retriever: EvidenceRetriever,
        *,
        max_iterations: int,
    ) -> FeatureCodingResult:
        plan = self.planner.plan(feature, inventory)
        iteration = 1
        iteration_trace: list[dict[str, Any]] = []
        while True:
            packet = retriever.retrieve(feature, inventory, plan)
            result = self.coder.code(feature, packet, iteration=iteration)
            should_retry, retry_reason = self.review_gate.evaluate(
                feature,
                packet,
                result,
                iteration=iteration,
                max_iterations=max_iterations,
            )
            iteration_trace.append(
                {
                    "iteration": iteration,
                    "retry": should_retry,
                    "retry_reason": retry_reason,
                    "confidence": result.confidence,
                    "manual_review": result.manual_review,
                    "validation_status": result.validation_status,
                    "identity_status": result.identity_status,
                    "evidence_items": len(packet.evidence),
                    "evidence_chars": sum(len(e.text or "") for e in packet.evidence),
                    "files_checked": list(packet.files_checked),
                    "missing_files": list(packet.missing_files),
                }
            )
            result.audit["iterations"] = iteration
            result.audit["iteration_trace"] = list(iteration_trace)
            result.audit["final_retry_reason"] = retry_reason
            result.audit["coding_mode"] = "per_feature_fallback"
            result.audit.update(_feature_audit_metadata(feature))
            if not should_retry:
                return result
            iteration += 1
            plan = plan.model_copy(
                update={
                    "evidence_queries": self.review_gate.strengthen_plan_queries(feature, result),
                    "files_to_read": _dedupe([*plan.files_to_read, "retailer/source.md", "retailer/tables/*.md", "retailer/vision.md"]),
                    "needs_vision": plan.needs_vision or feature.requires_visual,
                    "reason": f"Fallback evidence collection after review gate: {retry_reason}",
                }
            )

    def _is_systemic_bulk_failure(self, results: list[FeatureCodingResult], features: list[FeatureRule]) -> bool:
        if len(results) != len(features):
            return True
        if not results:
            return True
        fallback_placeholders = sum(1 for r in results if r.audit.get("bulk_fallback_result") or r.audit.get("bulk_missing_feature_result"))
        empty_or_unsupported = sum(1 for r in results if not r.coded_value.strip() or r.identity_status == "unsupported")
        parse_errors = sum(1 for r in results if r.audit.get("bulk_raw_llm_parse_error"))
        threshold = max(1, len(features) // 2)
        return fallback_placeholders >= threshold or empty_or_unsupported >= threshold or parse_errors >= threshold

    def _needs_fallback(self, result: FeatureCodingResult) -> bool:
        return (
            result.validation_status != "valid"
            or result.identity_status in {"unsupported", "conflicting"}
            or not result.coded_value.strip()
            or result.confidence < self.cfg.coding_min_confidence
        )

    def _manual_review_results(
        self,
        *,
        artifact_id: str,
        features: list[FeatureRule],
        reason: str,
        quality_decision: ArtifactQualityDecision,
    ) -> list[FeatureCodingResult]:
        return [
            self._manual_review_result(
                artifact_id,
                feature,
                reason,
                extra_audit={"artifact_quality_gate": quality_decision.to_dict(), "rescrape_needed": quality_decision.rescrape_needed},
            )
            for feature in features
        ]

    @staticmethod
    def _manual_review_result(
        artifact_id: str,
        feature: FeatureRule,
        reason: str,
        *,
        extra_audit: dict[str, Any] | None = None,
    ) -> FeatureCodingResult:
        return FeatureCodingResult(
            artifact_id=artifact_id,
            feature_id=feature.feature_id,
            feature_name=feature.feature_name,
            feature_type=feature.feature_type,
            coded_value="",
            confidence=0.0,
            manual_review=True,
            validation_status="needs_review",
            identity_status="unsupported",
            evidence=[],
            justification=reason,
            conflicts=[],
            missing_evidence=[reason],
            audit={"coding_mode": "manual_review_quality_gate", "iterations": 0, **_feature_audit_metadata(feature), **(extra_audit or {})},
        )

    @staticmethod
    def _attach_artifact_quality(results: list[FeatureCodingResult], artifact_quality_report: dict[str, Any]) -> None:
        if not artifact_quality_report:
            return
        for result in results:
            result.audit.setdefault("artifact_quality_report", artifact_quality_report)
            result.audit.setdefault("artifact_quality_warning_count", artifact_quality_report.get("warning_count", 0))

    @staticmethod
    def _attach_quality_gate(results: list[FeatureCodingResult], quality_decision: ArtifactQualityDecision) -> None:
        payload = quality_decision.to_dict()
        for result in results:
            result.audit.setdefault("artifact_quality_gate", payload)
            result.audit.setdefault("artifact_quality_decision", quality_decision.decision)
            result.audit.setdefault("rescrape_needed", quality_decision.rescrape_needed)

    @staticmethod
    def _apply_request_metadata(results: list[FeatureCodingResult], *, request: CodingRequest, product_id: str) -> None:
        context = dict(request.product_context or {})
        context.setdefault("input_id", product_id)
        for result in results:
            result.audit.setdefault("input_id", product_id)
            result.audit.setdefault("product_context", context)
            result.audit.setdefault("product_level_bulk_enabled", True)
            for key in (
                "product_url",
                "main_text",
                "ean",
                "retailer_name",
                "country_code",
                "requested_retailer_name",
                "requested_country_code",
                "best_url_present",
                "categorical_decision",
                "source_row",
                "batch_row_order",
            ):
                if key in context:
                    result.audit.setdefault(key, context.get(key))


def _fallback_priority(result: FeatureCodingResult) -> tuple[int, float]:
    if not result.coded_value.strip():
        return (0, result.confidence)
    if result.validation_status == "invalid":
        return (1, result.confidence)
    if result.identity_status in {"unsupported", "conflicting"}:
        return (2, result.confidence)
    if result.validation_status == "needs_review":
        return (3, result.confidence)
    return (4, result.confidence)


def _feature_audit_metadata(feature: FeatureRule) -> dict[str, Any]:
    return {
        "pg_name": feature.pg_name,
        "pg_no": feature.pg_no,
        "rulebook_pdf": feature.rulebook_pdf,
        "feature_order": feature.feature_order,
        "feature_section": feature.feature_section,
        "source_page": feature.source_page,
        "classification_reason": feature.classification_reason,
        "allowed_values": feature.allowed_values,
    }


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


__all__ = ["ProductLevelCodingAgent"]
