"""Feature coding reasoner."""

from __future__ import annotations

import json
from typing import Any

from ..config import get_config
from ..log import logger
from ..models import EvidenceItem, EvidencePacket, FeatureCodingResult, FeatureRule
from ..prompts import P
from ..rules.validator import RuleValidator
from ..services.llm import get_llm_service
from .json_utils import parse_json_object


class FeatureCoder:
    """Turn a feature-specific evidence packet into a coded value."""

    def __init__(self) -> None:
        self.cfg = get_config()
        self.validator = RuleValidator()

    def code(self, feature: FeatureRule, packet: EvidencePacket, *, iteration: int = 1) -> FeatureCodingResult:
        if not self.cfg.llm_enabled:
            result = self._fallback_result(feature, packet, reason="LLM disabled; deterministic evidence-only fallback.")
            return self.validator.validate(feature, result)

        payload = {
            "feature_rule": feature.model_dump(),
            "artifact_id": packet.artifact_id,
            "product_context": packet.product_context,
            "quality_signals": packet.quality_signals,
            "evidence_packet": {
                "plan": packet.plan.model_dump(),
                "evidence": [e.model_dump(mode="json") for e in packet.evidence],
                "files_checked": packet.files_checked,
                "missing_files": packet.missing_files,
                "missing_evidence": packet.missing_evidence,
            },
            "output_contract": {
                "coded_value": "string. Empty only if evidence insufficient.",
                "confidence": "float 0..1",
                "manual_review": "boolean",
                "validation_status": "valid|invalid|needs_review",
                "identity_status": "supported|weakly_supported|unsupported|conflicting",
                "evidence_used": "list of evidence ids used for final value",
                "justification": "short evidence-backed explanation",
                "conflicts": "list of conflicts",
                "missing_evidence": "list of missing evidence items",
            },
            "iteration": iteration,
        }
        try:
            resp = get_llm_service().predict(
                json.dumps(payload, ensure_ascii=False, indent=2),
                system_prompt=P.FEATURE_CODING_JSON.system,
                max_tokens=min(4096, self.cfg.llm_max_tokens),
                temperature=0.0,
                response_format={"type": "json_object"},
                purpose=P.FEATURE_CODING_JSON.name,
            )
            data = parse_json_object(resp.content)
            result = self._result_from_llm_data(feature, packet, data, raw_content=resp.content, usage=resp.usage)
            return self.validator.validate(feature, result)
        except Exception as exc:
            logger.warning("Feature coding failed feature={} iteration={}: {}", feature.feature_name, iteration, exc)
            result = self._fallback_result(feature, packet, reason=f"LLM coding failed: {exc}")
            return self.validator.validate(feature, result)

    def _result_from_llm_data(
        self,
        feature: FeatureRule,
        packet: EvidencePacket,
        data: dict[str, Any],
        *,
        raw_content: str,
        usage: dict[str, int],
    ) -> FeatureCodingResult:
        by_id = {e.evidence_id: e for e in packet.evidence}
        evidence_ids = data.get("evidence_used") or data.get("supporting_evidence_ids") or []
        evidence: list[EvidenceItem] = []
        if isinstance(evidence_ids, list):
            for evid in evidence_ids:
                if isinstance(evid, str) and evid in by_id:
                    evidence.append(by_id[evid])
                elif isinstance(evid, dict):
                    eid = str(evid.get("evidence_id") or evid.get("id") or "")
                    if eid in by_id:
                        evidence.append(by_id[eid])
        # If the LLM omitted evidence ids but there is a value, attach top evidence to preserve auditability.
        if not evidence and data.get("coded_value") and packet.evidence:
            evidence = packet.evidence[: min(3, len(packet.evidence))]

        confidence = _clamp_float(data.get("confidence"), default=0.0)
        manual_review = bool(data.get("manual_review", confidence < self.cfg.coding_min_confidence))
        validation_status = _valid_literal(
            data.get("validation_status"),
            {"valid", "invalid", "needs_review"},
            "needs_review",
        )
        identity_status = _valid_literal(
            data.get("identity_status"),
            {"supported", "weakly_supported", "unsupported", "conflicting"},
            "supported" if evidence and confidence >= self.cfg.coding_min_confidence else "weakly_supported",
        )
        return FeatureCodingResult(
            artifact_id=packet.artifact_id,
            feature_id=feature.feature_id,
            feature_name=feature.feature_name,
            feature_type=feature.feature_type,
            coded_value=str(data.get("coded_value") or "").strip(),
            confidence=confidence,
            manual_review=manual_review,
            validation_status=validation_status,
            identity_status=identity_status,
            evidence=evidence,
            justification=str(data.get("justification") or "").strip(),
            conflicts=[str(x) for x in (data.get("conflicts") or []) if str(x).strip()],
            missing_evidence=[str(x) for x in (data.get("missing_evidence") or []) if str(x).strip()] + packet.missing_evidence,
            audit={
                "planner_reason": packet.plan.reason,
                "files_checked": packet.files_checked,
                "missing_files": packet.missing_files,
                "llm_usage": usage,
                "raw_llm_parse_error": data.get("_parse_error", ""),
                "iterations": 1,
            },
        )

    def _fallback_result(self, feature: FeatureRule, packet: EvidencePacket, *, reason: str) -> FeatureCodingResult:
        top = packet.evidence[: min(3, len(packet.evidence))]
        missing = list(packet.missing_evidence)
        if not top:
            missing.append("No evidence available for deterministic fallback.")
        return FeatureCodingResult(
            artifact_id=packet.artifact_id,
            feature_id=feature.feature_id,
            feature_name=feature.feature_name,
            feature_type=feature.feature_type,
            coded_value="",
            confidence=0.0,
            manual_review=True,
            validation_status="needs_review",
            identity_status="unsupported" if not top else "weakly_supported",
            evidence=top,
            justification=reason,
            conflicts=[],
            missing_evidence=missing,
            audit={
                "planner_reason": packet.plan.reason,
                "files_checked": packet.files_checked,
                "missing_files": packet.missing_files,
                "fallback": True,
                "iterations": 1,
            },
        )


def _clamp_float(value: Any, *, default: float) -> float:
    try:
        f = float(value)
    except Exception:
        return default
    return max(0.0, min(1.0, f))


__all__ = ["FeatureCoder"]


def _valid_literal(value: Any, allowed: set[str], default: str) -> str:
    cleaned = str(value or "").strip().lower()
    return cleaned if cleaned in allowed else default
