"""Pydantic DTOs for artifact-grounded product feature coding."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_DTO_CONFIG = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

FeatureType = Literal["open_set", "closed_set"]
ValidationStatus = Literal["valid", "invalid", "needs_review"]
IdentityStatus = Literal["supported", "weakly_supported", "unsupported", "conflicting"]
EvidenceStrength = Literal["strong", "medium", "weak"]


class FeatureRule(BaseModel):
    """Feature definition supplied by the rulebook/artifact provider."""

    model_config = _DTO_CONFIG

    feature_id: str
    feature_name: str
    feature_type: FeatureType = "open_set"
    definition: str = ""
    allowed_values: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    evidence_hints: list[str] = Field(default_factory=list)
    requires_visual: bool = False
    missing_value: str = "Not stated"
    pg_name: str = ""
    pg_no: str = ""
    rulebook_pdf: str = ""
    feature_order: int | None = None
    feature_section: str = ""
    source_page: int | None = None
    classification_reason: str = ""

    @field_validator("feature_id", "feature_name")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not (value or "").strip():
            raise ValueError("feature_id and feature_name are required")
        return value.strip()

    @field_validator("allowed_values", "aliases", "evidence_hints")
    @classmethod
    def clean_list(cls, values: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for value in values or []:
            cleaned = (value or "").strip()
            key = cleaned.lower()
            if cleaned and key not in seen:
                out.append(cleaned)
                seen.add(key)
        return out

    @model_validator(mode="after")
    def validate_closed_set(self) -> "FeatureRule":
        # Closed-set features can arrive from the PG input file without allowed_values.
        # In that case the coding agent can still collect evidence and propose a value,
        # but RuleValidator will mark the result as needing manual rulebook validation.
        return self

    @property
    def evidence_terms(self) -> list[str]:
        terms = [self.feature_name, *self.aliases, *self.evidence_hints]
        # Add useful tokenized terms from names like "Battery Required".
        terms.extend(self.feature_name.replace("/", " ").replace("_", " ").split())
        if self.definition:
            terms.extend([w for w in self.definition.replace("/", " ").split() if len(w) > 3][:10])
        if self.feature_type == "closed_set":
            terms.extend([v for v in self.allowed_values if len(v) > 2])
        seen: set[str] = set()
        out: list[str] = []
        for term in terms:
            key = (term or "").strip().lower()
            if key and key not in seen:
                out.append((term or "").strip())
                seen.add(key)
        return out


class CodingRequest(BaseModel):
    """Public runtime request."""

    model_config = _DTO_CONFIG

    artifact_dir: Path
    features: list[FeatureRule]
    output_dir: Path | None = None
    product_id: str = ""
    product_context: dict[str, Any] = Field(default_factory=dict)
    max_iterations: int = 1
    max_parallel_features: int | None = None

    @model_validator(mode="after")
    def validate_request(self) -> "CodingRequest":
        if not self.artifact_dir.exists():
            raise ValueError(f"artifact_dir does not exist: {self.artifact_dir}")
        if not self.features:
            raise ValueError("At least one feature is required")
        if self.max_parallel_features is not None and self.max_parallel_features < 1:
            raise ValueError("max_parallel_features must be >= 1 when provided")
        return self


class ArtifactFile(BaseModel):
    model_config = _DTO_CONFIG

    relative_path: str
    absolute_path: Path
    file_type: str
    bytes_size: int = 0
    priority: int = 50


class ArtifactInventory(BaseModel):
    model_config = _DTO_CONFIG

    artifact_id: str
    artifact_root: Path
    retailer_dir: Path
    files: list[ArtifactFile] = Field(default_factory=list)
    present_expected_files: list[str] = Field(default_factory=list)
    missing_expected_files: list[str] = Field(default_factory=list)

    def has_file(self, relative_path: str) -> bool:
        rel = relative_path.replace("\\", "/")
        return any(f.relative_path == rel for f in self.files)

    def find(self, pattern: str) -> list[ArtifactFile]:
        import fnmatch

        pattern = pattern.replace("\\", "/")
        return [f for f in self.files if fnmatch.fnmatch(f.relative_path, pattern)]


class EvidencePlan(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    evidence_queries: list[str] = Field(default_factory=list)
    files_to_read: list[str] = Field(default_factory=list)
    needs_vision: bool = False
    needs_images: bool = False
    reason: str = ""


class EvidenceItem(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    evidence_id: str
    source_file: str
    evidence_type: str = "text"
    text: str
    field_path: str = ""
    score: float = 0.0
    strength: EvidenceStrength = "medium"
    evidence_axis: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidencePacket(BaseModel):
    model_config = _DTO_CONFIG

    artifact_id: str
    feature_id: str
    feature_name: str
    plan: EvidencePlan
    product_context: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    files_checked: list[str] = Field(default_factory=list)
    missing_files: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    quality_signals: dict[str, Any] = Field(default_factory=dict)


class CandidateValue(BaseModel):
    model_config = _DTO_CONFIG

    value: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    support_strength: EvidenceStrength = "medium"
    confidence: float = 0.0
    rationale: str = ""


class FeatureCodingResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    artifact_id: str
    feature_id: str
    feature_name: str
    feature_type: FeatureType
    coded_value: str = ""
    confidence: float = 0.0
    manual_review: bool = True
    validation_status: ValidationStatus = "needs_review"
    identity_status: IdentityStatus = "weakly_supported"
    evidence: list[EvidenceItem] = Field(default_factory=list)
    justification: str = ""
    conflicts: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)


class BatchCodingResult(BaseModel):
    model_config = _DTO_CONFIG

    artifact_id: str
    artifact_dir: Path
    results: list[FeatureCodingResult]
    output_dir: Path | None = None
    product_id: str = ""
    product_context: dict[str, Any] = Field(default_factory=dict)
    artifact_quality_report: dict[str, Any] = Field(default_factory=dict)


class ProductInputRow(BaseModel):
    """One row from the product batch input CSV."""

    model_config = _DTO_CONFIG

    input_id: str
    pg_name: str
    row_order: int
    fields: dict[str, Any] = Field(default_factory=dict)


class ProductBatchCodingRequest(BaseModel):
    """Runtime request for coding many product artifacts from a product batch CSV."""

    model_config = _DTO_CONFIG

    batch_input_csv: Path
    scraped_root: Path
    pg_feature_input_csv: Path
    output_dir: Path | None = None
    input_ids: list[str] | None = None
    limit_products: int | None = None
    limit_features: int | None = None
    max_iterations: int = 1
    max_parallel_features: int | None = None
    max_parallel_products: int | None = None
    coding_mode: str | None = None
    llm_preflight: bool | None = None

    @model_validator(mode="after")
    def validate_batch_request(self) -> "ProductBatchCodingRequest":
        if not self.batch_input_csv.exists():
            raise ValueError(f"batch_input_csv does not exist: {self.batch_input_csv}")
        if not self.scraped_root.exists():
            raise ValueError(f"scraped_root does not exist: {self.scraped_root}")
        if not self.pg_feature_input_csv.exists():
            raise ValueError(f"pg_feature_input_csv does not exist: {self.pg_feature_input_csv}")
        if self.max_parallel_features is not None and self.max_parallel_features < 1:
            raise ValueError("max_parallel_features must be >= 1 when provided")
        if self.max_parallel_products is not None and self.max_parallel_products < 1:
            raise ValueError("max_parallel_products must be >= 1 when provided")
        if self.coding_mode is not None and self.coding_mode.strip().lower() not in {"per_product", "product", "bulk", "auto", "per_feature", "feature"}:
            raise ValueError("coding_mode must be one of: per_product, product, bulk, auto, per_feature, feature")
        return self


class FailedProductCodingResult(BaseModel):
    """A product-level failure that occurred before feature coding could complete."""

    model_config = _DTO_CONFIG

    input_id: str
    pg_name: str = ""
    artifact_dir: Path | None = None
    error: str
    error_type: str = ""
    product_context: dict[str, Any] = Field(default_factory=dict)


class ProductBatchCodingResult(BaseModel):
    """Output of coding multiple product artifacts from a product batch CSV."""

    model_config = _DTO_CONFIG

    products: list[BatchCodingResult] = Field(default_factory=list)
    failed_products: list[FailedProductCodingResult] = Field(default_factory=list)
    output_dir: Path | None = None
    artifact_quality_reports: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "ArtifactFile",
    "ArtifactInventory",
    "BatchCodingResult",
    "CandidateValue",
    "CodingRequest",
    "EvidenceItem",
    "EvidencePacket",
    "EvidencePlan",
    "FeatureCodingResult",
    "FeatureRule",
    "ProductInputRow",
    "ProductBatchCodingRequest",
    "ProductBatchCodingResult",
    "FailedProductCodingResult",
]
