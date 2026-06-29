"""Top-level loop-engineered Product Coding Agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import threading

from ..config import get_config
from ..log import logger
from ..models import BatchCodingResult, CodingRequest, FeatureCodingResult, FeatureRule
from ..outputs.writer import ResultWriter
from ..artifacts.context import ProductArtifactContextBuilder
from ..artifacts.navigator import ArtifactNavigator
from ..artifacts.reader import ArtifactReader
from .coder import FeatureCoder
from .planner import EvidencePlanner
from .retriever import EvidenceRetriever
from .review_gate import ReviewGate
from .worker_pool import FeatureWorkerPool, WorkerPoolConfig


class ProductCodingAgent:
    """LLM-centered feature coding agent over one scrape artifact folder.

    Features are independent units of work over the same immutable scrape artifact.
    The agent therefore supports feature-level parallelism while keeping each
    feature's internal evidence loop sequential and auditable.
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self.planner = EvidencePlanner()
        self.coder = FeatureCoder()
        self.review_gate = ReviewGate()

    def code_feature(self, artifact_dir: str | Path, feature: FeatureRule, *, output_dir: str | Path | None = None) -> FeatureCodingResult:
        request = CodingRequest(
            artifact_dir=Path(artifact_dir),
            features=[feature],
            output_dir=Path(output_dir) if output_dir else None,
            max_parallel_features=1,
        )
        return self.run(request).results[0]

    def run(self, request: CodingRequest) -> BatchCodingResult:
        navigator = ArtifactNavigator(request.artifact_dir)
        inventory = navigator.inventory()
        reader = ArtifactReader(navigator)
        product_context_index = ProductArtifactContextBuilder(navigator, reader).build(inventory)
        retriever = EvidenceRetriever(navigator, reader, context=product_context_index)

        max_workers = self._resolve_max_workers(request)
        logger.info(
            "ProductCodingAgent start artifact={} features={} max_parallel_features={} context_files={} context_chars={}",
            inventory.artifact_id,
            len(request.features),
            max_workers,
            product_context_index.file_count,
            product_context_index.total_text_chars,
        )

        if max_workers <= 1 or len(request.features) <= 1:
            results = [
                self._code_feature_loop(feature, inventory, retriever, request.max_iterations)
                for feature in request.features
            ]
        else:
            results = self._run_features_parallel(
                request.features,
                inventory=inventory,
                retriever=retriever,
                max_iterations=request.max_iterations,
                max_workers=max_workers,
            )

        product_id = request.product_id or str(request.product_context.get("input_id") or inventory.artifact_id)
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
        writer = ResultWriter()
        writer.write(out, output_dir=request.output_dir)
        logger.info("ProductCodingAgent complete artifact={} results={}", inventory.artifact_id, len(results))
        return out

    def _resolve_max_workers(self, request: CodingRequest) -> int:
        requested = request.max_parallel_features
        if requested is None:
            requested = self.cfg.coding_max_parallel_features
        return max(1, min(int(requested), len(request.features)))

    def _run_features_parallel(
        self,
        features: list[FeatureRule],
        *,
        inventory: Any,
        retriever: EvidenceRetriever,
        max_iterations: int,
        max_workers: int,
    ) -> list[FeatureCodingResult]:
        """Run independent feature coding loops through a dynamic worker pool."""
        pool = FeatureWorkerPool(WorkerPoolConfig(max_workers=max_workers))

        def work(feature: FeatureRule) -> FeatureCodingResult:
            return self._code_feature_loop(feature, inventory, retriever, max_iterations)

        def crash(feature: FeatureRule, exc: Exception) -> FeatureCodingResult:
            return self._crash_result(feature, inventory.artifact_id, exc)

        return pool.run(features, work, crash)

    def _code_feature_loop(
        self,
        feature: FeatureRule,
        inventory: Any,
        retriever: EvidenceRetriever,
        max_iterations: int,
    ) -> FeatureCodingResult:
        worker_thread = threading.current_thread().name
        logger.info("Coding feature: {} ({}) worker_thread={}", feature.feature_name, feature.feature_id, worker_thread)
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
            iteration_record = {
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
                "conflicts": list(result.conflicts),
                "missing_evidence": list(result.missing_evidence),
            }
            iteration_trace.append(iteration_record)
            logger.info(
                "Feature iteration feature={} iteration={} retry={} reason={} confidence={} validation={} evidence_items={}",
                feature.feature_name,
                iteration,
                should_retry,
                retry_reason,
                f"{result.confidence:.3f}",
                result.validation_status,
                len(packet.evidence),
            )
            result.audit["iterations"] = iteration
            result.audit["iteration_trace"] = list(iteration_trace)
            result.audit["final_retry_reason"] = retry_reason
            result.audit["parallel_safe"] = True
            result.audit["worker_thread"] = worker_thread
            result.audit["worker_pool"] = "feature_worker_pool"
            result.audit["product_context_indexed"] = True
            result.audit.update(_feature_audit_metadata(feature))
            if not should_retry:
                return result
            iteration += 1
            plan = plan.model_copy(
                update={
                    "evidence_queries": self.review_gate.strengthen_plan_queries(feature, result),
                    "files_to_read": _dedupe([*plan.files_to_read, "retailer/source.md", "retailer/tables/*.md", "retailer/vision.md"]),
                    "needs_vision": plan.needs_vision or feature.requires_visual,
                    "reason": f"Follow-up evidence collection after review gate: {retry_reason}; details={result.missing_evidence or result.conflicts}",
                }
            )

    @staticmethod
    def _attach_artifact_quality(results: list[FeatureCodingResult], artifact_quality_report: dict[str, Any]) -> None:
        if not artifact_quality_report:
            return
        for result in results:
            result.audit.setdefault("artifact_quality_report", artifact_quality_report)
            result.audit.setdefault("artifact_quality_warning_count", artifact_quality_report.get("warning_count", 0))

    @staticmethod
    def _apply_request_metadata(
        results: list[FeatureCodingResult],
        *,
        request: CodingRequest,
        product_id: str,
    ) -> None:
        context = dict(request.product_context or {})
        context.setdefault("input_id", product_id)
        for result in results:
            result.audit.setdefault("input_id", product_id)
            result.audit.setdefault("product_context", context)
            # Keep frequently used product input fields top-level in audit for CSV/reporting.
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
            ):
                if key in context:
                    result.audit.setdefault(key, context.get(key))

    @staticmethod
    def _crash_result(feature: FeatureRule, artifact_id: str, exc: Exception) -> FeatureCodingResult:
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
            justification=f"Feature crashed during coding loop: {exc}",
            conflicts=[],
            missing_evidence=["Feature-level worker crashed before a supported coded value could be produced."],
            audit={
                **_feature_audit_metadata(feature),
                "worker_crash": True,
                "exception_type": type(exc).__name__,
                "exception": str(exc),
                "parallel_safe": True,
                "worker_pool": "feature_worker_pool",
            },
        )


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


__all__ = ["ProductCodingAgent"]
