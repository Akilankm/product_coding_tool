"""Quality gate for product-level coding."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..artifacts.context import ProductArtifactContext
from ..models import FeatureRule

QualityDecision = Literal["GREEN", "AMBER", "RED"]


@dataclass(frozen=True)
class ArtifactQualityDecision:
    decision: QualityDecision
    score: float
    bulk_allowed: bool
    full_product_fallback_required: bool
    rescrape_needed: bool
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, int | float | bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "score": self.score,
            "bulk_allowed": self.bulk_allowed,
            "full_product_fallback_required": self.full_product_fallback_required,
            "rescrape_needed": self.rescrape_needed,
            "reasons": list(self.reasons),
            "metrics": dict(self.metrics),
        }


class ArtifactQualityGate:
    STRONG_SOURCES = (
        "retailer/source.md",
        "retailer/product_evidence.json",
        "retailer/product_evidence.md",
        "retailer/claims.md",
    )

    def evaluate(self, context: ProductArtifactContext, features: list[FeatureRule]) -> ArtifactQualityDecision:
        reasons: list[str] = []
        warning_count = int((context.artifact_quality_report or {}).get("warning_count") or 0)
        missing_expected_count = len(context.missing_expected_files or [])
        strong_source_count = sum(1 for rel in self.STRONG_SOURCES if (context.file_texts.get(rel) or "").strip())
        visual_feature_count = sum(1 for feature in features if feature.requires_visual)
        has_vision = bool((context.file_texts.get("retailer/vision.md") or "").strip() or (context.file_texts.get("retailer/manifests/image_manifest.json") or "").strip())

        score = 1.0
        if context.file_count == 0:
            score -= 0.55
            reasons.append("No readable artifact files were indexed.")
        if context.total_text_chars < 500:
            score -= 0.45
            reasons.append("Indexed artifact text is too small for reliable coding.")
        elif context.total_text_chars < 2000:
            score -= 0.20
            reasons.append("Indexed artifact text is limited.")
        if strong_source_count == 0:
            score -= 0.30
            reasons.append("No strong product evidence source was found.")
        if warning_count:
            score -= min(0.20, warning_count * 0.03)
            reasons.append(f"Artifact reader recorded {warning_count} warning(s).")
        if missing_expected_count:
            score -= min(0.18, missing_expected_count * 0.03)
            reasons.append(f"{missing_expected_count} expected artifact file(s) are missing.")
        if visual_feature_count and not has_vision:
            score -= 0.12
            reasons.append("Visual feature evidence is missing.")
        score = max(0.0, min(1.0, score))
        metrics = {
            "file_count": context.file_count,
            "total_text_chars": context.total_text_chars,
            "strong_source_count": strong_source_count,
            "warning_count": warning_count,
            "missing_expected_count": missing_expected_count,
            "feature_count": len(features),
            "visual_feature_count": visual_feature_count,
            "has_vision_evidence": has_vision,
        }
        if context.file_count == 0 or context.total_text_chars < 500:
            return ArtifactQualityDecision("RED", score, False, False, True, reasons, metrics)
        if score < 0.55 or strong_source_count == 0:
            return ArtifactQualityDecision("RED", score, False, True, False, reasons, metrics)
        if score < 0.78 or warning_count or missing_expected_count or (visual_feature_count and not has_vision):
            return ArtifactQualityDecision("AMBER", score, True, False, False, reasons, metrics)
        return ArtifactQualityDecision("GREEN", score, True, False, False, reasons, metrics)


__all__ = ["ArtifactQualityDecision", "ArtifactQualityGate"]
