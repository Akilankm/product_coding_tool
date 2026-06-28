"""Scrape artifact contract used by the product coding agent."""

from __future__ import annotations

from dataclasses import dataclass


EXPECTED_RETAILER_FILES: tuple[str, ...] = (
    "retailer/product_evidence.json",
    "retailer/product_evidence.md",
    "retailer/claims.md",
    "retailer/source.md",
    "retailer/vision.md",
    "retailer/metadata.json",
    "retailer/quality_report.json",
    "retailer/noise_report.json",
    "retailer/evidence_recovery_report.json",
    "retailer/manifests/artifact_manifest.json",
    "retailer/manifests/image_manifest.json",
    "retailer/manifests/table_manifest.json",
    "retailer/manifests/agent_trace.json",
    "scrape_result.json",
    "request.json",
)

TEXT_PATTERNS: tuple[str, ...] = (
    "retailer/*.md",
    "retailer/tables/*.md",
    "retailer/*.json",
    "retailer/manifests/*.json",
    "*.json",
)

IMAGE_PATTERNS: tuple[str, ...] = (
    "retailer/images/*.jpg",
    "retailer/images/*.jpeg",
    "retailer/images/*.png",
    "retailer/images/*.webp",
)

SOURCE_PRIORITY: dict[str, int] = {
    "retailer/source.md": 1,
    "retailer/tables/": 2,
    "retailer/metadata.json": 3,
    "retailer/product_evidence.json": 4,
    "retailer/product_evidence.md": 4,
    "retailer/claims.md": 5,
    "retailer/vision.md": 6,
    "retailer/manifests/image_manifest.json": 7,
    "retailer/quality_report.json": 8,
    "retailer/noise_report.json": 9,
    "retailer/evidence_recovery_report.json": 9,
    "request.json": 10,
    "scrape_result.json": 10,
}

FILE_TYPE_BY_SUFFIX: dict[str, str] = {
    ".md": "markdown",
    ".json": "json",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".webp": "image",
}


@dataclass(frozen=True)
class ArtifactContract:
    expected_retailer_files: tuple[str, ...] = EXPECTED_RETAILER_FILES
    text_patterns: tuple[str, ...] = TEXT_PATTERNS
    image_patterns: tuple[str, ...] = IMAGE_PATTERNS


def priority_for(relative_path: str) -> int:
    rel = relative_path.replace("\\", "/")
    if rel.startswith("retailer/tables/"):
        return SOURCE_PRIORITY["retailer/tables/"]
    return SOURCE_PRIORITY.get(rel, 50)


def file_type_for(relative_path: str) -> str:
    from pathlib import Path

    return FILE_TYPE_BY_SUFFIX.get(Path(relative_path).suffix.lower(), "other")


__all__ = [
    "ArtifactContract",
    "EXPECTED_RETAILER_FILES",
    "IMAGE_PATTERNS",
    "SOURCE_PRIORITY",
    "TEXT_PATTERNS",
    "file_type_for",
    "priority_for",
]
