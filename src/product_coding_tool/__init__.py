"""Artifact-grounded product feature coding agent."""

from __future__ import annotations

from .agent.orchestrator import ProductCodingAgent
from .models import (
    BatchCodingResult,
    CodingRequest,
    EvidenceItem,
    EvidencePacket,
    EvidencePlan,
    FeatureCodingResult,
    FeatureRule,
)

__version__ = "0.1.0"

__all__ = [
    "BatchCodingResult",
    "CodingRequest",
    "EvidenceItem",
    "EvidencePacket",
    "EvidencePlan",
    "FeatureCodingResult",
    "FeatureRule",
    "ProductCodingAgent",
]
