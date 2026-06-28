"""Top-level loop-engineered Product Coding Agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import threading

from ..config import get_config
from ..log import logger
from ..models import BatchCodingResult, CodingRequest, EvidencePlan, FeatureCodingResult, FeatureRule
from ..outputs.writer import ResultWriter
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
        retriever = EvidenceRetriever(navigator, reader)

        max_workers = self._resolve_max_workers(request)
        logger.info(
            "ProductCodingAgent start artifact={} features={} max_parallel_features={}",
            inventory.artifact_id,
            len(request.features),
            max_workers,
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

        out = BatchCodingResult(
            artifact_id=inventory.artifact_id,
            artifact_dir=navigator.artifact_root,
            results=results,
            output_dir=request.output_dir,
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
        """Run independent feature coding loops through a dynamic worker pool.

        A worker receives one feature, completes that feature's full sequential
        evidence loop including retries, then picks the next queued feature.
        Final output is sorted back to the input feature order.
        """
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
        while True:
            packet = retriever.retrieve(feature, inventory, plan)
            result = self.coder.code(feature, packet, iteration=iteration)
            result.audit["iterations"] = iteration
            result.audit["parallel_safe"] = True
            result.audit["worker_thread"] = worker_thread
            result.audit["worker_pool"] = "feature_worker_pool"
            if not self.review_gate.should_collect_more(feature, packet, result, iteration=iteration, max_iterations=max_iterations):
                return result
            iteration += 1
            plan = plan.model_copy(
                update={
                    "evidence_queries": self.review_gate.strengthen_plan_queries(feature, result),
                    "files_to_read": _dedupe([*plan.files_to_read, "retailer/source.md", "retailer/tables/*.md", "retailer/vision.md"]),
                    "needs_vision": plan.needs_vision or feature.requires_visual,
                    "reason": f"Follow-up evidence collection after review gate: {result.missing_evidence or result.conflicts}",
                }
            )

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
                "worker_crash": True,
                "exception_type": type(exc).__name__,
                "exception": str(exc),
                "parallel_safe": True,
                "worker_pool": "feature_worker_pool",
            },
        )


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
