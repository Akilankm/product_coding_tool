"""Top-level loop-engineered Product Coding Agent."""

from __future__ import annotations

from pathlib import Path

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


class ProductCodingAgent:
    """LLM-centered feature coding agent over one scrape artifact folder."""

    def __init__(self) -> None:
        self.cfg = get_config()
        self.planner = EvidencePlanner()
        self.coder = FeatureCoder()
        self.review_gate = ReviewGate()

    def code_feature(self, artifact_dir: str | Path, feature: FeatureRule, *, output_dir: str | Path | None = None) -> FeatureCodingResult:
        request = CodingRequest(artifact_dir=Path(artifact_dir), features=[feature], output_dir=Path(output_dir) if output_dir else None)
        return self.run(request).results[0]

    def run(self, request: CodingRequest) -> BatchCodingResult:
        navigator = ArtifactNavigator(request.artifact_dir)
        inventory = navigator.inventory()
        reader = ArtifactReader(navigator)
        retriever = EvidenceRetriever(navigator, reader)
        results: list[FeatureCodingResult] = []

        logger.info("ProductCodingAgent start artifact={} features={}", inventory.artifact_id, len(request.features))
        for feature in request.features:
            logger.info("Coding feature: {} ({})", feature.feature_name, feature.feature_id)
            plan = self.planner.plan(feature, inventory)
            final_result: FeatureCodingResult | None = None
            iteration = 1
            while True:
                packet = retriever.retrieve(feature, inventory, plan)
                result = self.coder.code(feature, packet, iteration=iteration)
                result.audit["iterations"] = iteration
                if not self.review_gate.should_collect_more(feature, packet, result, iteration=iteration, max_iterations=request.max_iterations):
                    final_result = result
                    break
                iteration += 1
                plan = plan.model_copy(
                    update={
                        "evidence_queries": self.review_gate.strengthen_plan_queries(feature, result),
                        "files_to_read": _dedupe([*plan.files_to_read, "retailer/source.md", "retailer/tables/*.md", "retailer/vision.md"]),
                        "needs_vision": plan.needs_vision or feature.requires_visual,
                        "reason": f"Follow-up evidence collection after review gate: {result.missing_evidence or result.conflicts}",
                    }
                )
            results.append(final_result)

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
