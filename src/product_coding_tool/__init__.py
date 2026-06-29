"""Artifact-grounded product feature coding agent."""

from __future__ import annotations

from .agent.orchestrator import ProductCodingAgent
from .batch import ProductBatchCodingAgent
from .inputs.product_batch import ProductBatchInputProvider
from .rules.pg_input import PGFeatureInputProvider
from .models import (
    BatchCodingResult,
    CodingRequest,
    EvidenceItem,
    EvidencePacket,
    EvidencePlan,
    FailedProductCodingResult,
    FeatureCodingResult,
    FeatureRule,
    ProductBatchCodingRequest,
    ProductBatchCodingResult,
    ProductInputRow,
)

__version__ = "1.3.1"

__all__ = [
    "BatchCodingResult",
    "CodingRequest",
    "EvidenceItem",
    "EvidencePacket",
    "EvidencePlan",
    "FailedProductCodingResult",
    "FeatureCodingResult",
    "FeatureRule",
    "PGFeatureInputProvider",
    "ProductBatchCodingAgent",
    "ProductBatchCodingRequest",
    "ProductBatchCodingResult",
    "ProductBatchInputProvider",
    "ProductCodingAgent",
    "ProductInputRow",
]
