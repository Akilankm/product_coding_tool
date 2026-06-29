"""Artifact-grounded product feature coding agent."""

from __future__ import annotations

from .agent.orchestrator import ProductCodingAgent
from .agent.product_level import ProductLevelCodingAgent
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

__version__ = "1.4.0"

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
    "ProductLevelCodingAgent",
    "ProductInputRow",
]
