"""Fast product-level coding agent.

This agent targets high-throughput production runs: one bulk LLM call codes all
features for one product, deterministic validation checks every value, and only
weak/invalid features are selectively escalated to the existing per-feature loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifacts.context import ProductArtifactContextBuilder
from ..artifacts.navigator import ArtifactNavigator
from ..artifacts.reader import ArtifactReader
from ..config import get_config
from ..log import logger
from ..models import BatchCodingResult, CodingRequest, FeatureCodingResult, FeatureRule
from ..outputs.writer import ResultWriter
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
        self.planner = EvidencePlanner()
        self.coder = FeatureCoder()
        self.review_gate = ReviewGate()

    def run(self, request: CodingRequest) -> BatchCodingResult:
        navigator = ArtifactNavigator(request.artifact_dir)
        inventory = navigator.inventory()
        reader = ArtifactReader(navigator)
        product_context_index = ProductArtifactContextBuilder(navigator, reader).build(inventory)
        product_id = request.product_id or str(request.product_context.get("input_id") or inventory.artifact_id)
        logger.info(
            "ProductLevelCodingAgent start artifact={} product_id={} features={} context_files={} context_chars={} fallback_enabled={} fallback_limit={}",
            inventory.artifact_id,
            product_id,
            len(request.features),
            product_context_index.file_count,
            product_context_index.total_text_chars,
            self.cfg.coding_bulk_fallback_enabled,
            self.cfg.coding_bulk_max_fallback_features,
        )

        results = self.bulk_coder.code_many(
            artifact_id=inventory.artifact_id,
            features=request.features,
            product_context=request.product_context,
            context=product_context_index,
        )
        results = self._fallback_weak_features(
            results,
            request=request,
            inventory=inventory,
            retriever=EvidenceRetriever(navigator, reader, context=product_context_index),
        )
        self._apply_request_metadata(results, request=request, product_id=product_id)
        artifact_quality_report = product_context_index.artifact_quality_report or reader.quality_report().to_dict()
        self._attach_artifact_quality(results, artifact_quality_report)
        out = BatchCodingResult(
            artifact_id=inventory.artifact_id,
            artifact_dir=navigator.artifact_root,
            results=results,
            output_dir=request.output_dir,
            product_id=product_id,
            product_context=request.product_context,
            artifact_quality_report=artifact_quality_report,
        )
        ResultWriter().write(out, output_dir=request.output_dir)
        logger.info(
            "ProductLevelCodingAgent complete artifact={} results={} fallback_count={} manual_review_count={}",
            inventory.artifact_id,
            len(results),
            sum(1 for r in results if r.audit.get("fallback_from_bulk")),
            sum(1 for r in results if r.manual_review),
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
        # Highest-risk outputs are corrected first. Remaining weak values stay audited/manual-review.
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

    def _needs_fallback(self, result: FeatureCodingResult) -> bool:
        return (
            result.validation_status != "valid"
            or result.identity_status in {"unsupported", "conflicting"}
            or not result.coded_value.strip()
            or result.confidence < self.cfg.coding_min_confidence
        )

    @staticmethod
    def _attach_artifact_quality(results: list[FeatureCodingResult], artifact_quality_report: dict[str, Any]) -> None:
        if not artifact_quality_report:
            return
        for result in results:
            result.audit.setdefault("artifact_quality_report", artifact_quality_report)
            result.audit.setdefault("artifact_quality_warning_count", artifact_quality_report.get("warning_count", 0))

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
