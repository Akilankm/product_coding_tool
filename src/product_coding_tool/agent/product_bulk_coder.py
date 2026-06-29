"""One-call product-level feature coding.

This module is the fast production path. It codes every feature for one product
in a single LLM request, then applies the same deterministic RuleValidator used
by the per-feature path. Weak/invalid features can still be selectively sent to
the slower per-feature fallback path by ProductLevelCodingAgent.
"""

from __future__ import annotations

import json
from typing import Any

from ..artifacts.context import ProductArtifactContext
from ..config import get_config
from ..log import logger
from ..models import EvidenceItem, FeatureCodingResult, FeatureRule
from ..prompts import P
from ..rules.validator import RuleValidator
from ..services.llm import get_llm_service
from .json_utils import parse_json_object
from .locator import compact_snippet if False else None


class ProductBulkCoder:
    """Code all requested features for a single product with one compact LLM call."""

    def __init__(self) -> None:
        self.cfg = get_config()
        self.validator = RuleValidator()

    def code_many(
        self,
        *,
        artifact_id: str,
        features: list[FeatureRule],
        product_context: dict[str, Any],
        context: ProductArtifactContext,
    ) -> list[FeatureCodingResult]:
        if not self.cfg.llm_enabled:
            return [self._fallback_result(artifact_id, f, [], "LLM disabled; product bulk coding skipped.") for f in features]

        evidence_items = self._build_product_evidence(features, context)
        evidence_by_id = {e.evidence_id: e for e in evidence_items}
        payload = {
            "artifact_id": artifact_id,
            "coding_mode": "per_product_bulk",
            "product_context": product_context,
            "artifact_quality": context.artifact_quality_report,
            "quality_signals": context.quality_signals,
            "features": [self._feature_payload(feature) for feature in features],
            "product_evidence": [e.model_dump(mode="json") for e in evidence_items],
            "instructions": [
                "Code every feature independently using only product_evidence and product_context.",
                "Do not invent values. Empty value means evidence is insufficient.",
                "For closed_set features, coded_value must exactly match one allowed_values entry when allowed_values is non-empty.",
                "Return one result object for every input feature_id.",
                "Use evidence_used IDs from product_evidence for every supported coded_value.",
                "Set manual_review=true when evidence is weak, conflicting, missing, or a closed-set value cannot be mapped cleanly.",
            ],
            "output_contract": {
                "features": [
                    {
                        "feature_id": "string",
                        "coded_value": "string",
                        "confidence": "float 0..1",
                        "manual_review": "boolean",
                        "validation_status": "valid|invalid|needs_review",
                        "identity_status": "supported|weakly_supported|unsupported|conflicting",
                        "evidence_used": "list of evidence ids",
                        "justification": "short evidence-backed explanation",
                        "conflicts": "list of strings",
                        "missing_evidence": "list of strings",
                    }
                ]
            },
        }
        try:
            resp = get_llm_service().predict(
                json.dumps(payload, ensure_ascii=False, indent=2),
                system_prompt=P.PRODUCT_BULK_CODING.system,
                max_tokens=min(self.cfg.llm_max_tokens, 7000),
                temperature=0.0,
                response_format={"type": "json_object"},
                purpose=P.PRODUCT_BULK_CODING.name,
            )
            data = parse_json_object(resp.content)
            results = self._results_from_llm_data(
                artifact_id=artifact_id,
                features=features,
                data=data,
                evidence_by_id=evidence_by_id,
                usage=resp.usage,
                raw_content=resp.content,
            )
            logger.info(
                "Product bulk coding complete artifact={} features={} evidence_items={} prompt_tokens={} completion_tokens={}",
                artifact_id,
                len(results),
                len(evidence_items),
                resp.usage.get("prompt_tokens", 0),
                resp.usage.get("completion_tokens", 0),
            )
            return results
        except Exception as exc:  # noqa: BLE001 - product-level fallback remains available.
            logger.exception("Product bulk coding failed artifact={} features={}", artifact_id, len(features))
            return [self._fallback_result(artifact_id, f, evidence_items[:3], f"Product bulk coding failed: {exc}") for f in features]

    def _results_from_llm_data(
        self,
        *,
        artifact_id: str,
        features: list[FeatureRule],
        data: dict[str, Any],
        evidence_by_id: dict[str, EvidenceItem],
        usage: dict[str, int],
        raw_content: str,
    ) -> list[FeatureCodingResult]:
        raw_results = data.get("features") or data.get("results") or data.get("coded_features") or []
        if isinstance(raw_results, dict):
            raw_results = list(raw_results.values())
        by_feature_id: dict[str, dict[str, Any]] = {}
        if isinstance(raw_results, list):
            for item in raw_results:
                if isinstance(item, dict):
                    fid = str(item.get("feature_id") or "").strip()
                    if fid:
                        by_feature_id[fid] = item

        out: list[FeatureCodingResult] = []
        parse_error = data.get("_parse_error", "")
        for feature in features:
            item = by_feature_id.get(feature.feature_id)
            if not item:
                result = self._fallback_result(
                    artifact_id,
                    feature,
                    list(evidence_by_id.values())[:3],
                    "Product bulk LLM did not return this feature_id.",
                )
                result.audit["bulk_missing_feature_result"] = True
                result.audit["raw_llm_parse_error"] = parse_error
                out.append(self.validator.validate(feature, result))
                continue
            evidence = self._evidence_from_ids(item, evidence_by_id)
            if not evidence and item.get("coded_value"):
                evidence = list(evidence_by_id.values())[: min(3, len(evidence_by_id))]
            confidence = _clamp_float(item.get("confidence"), default=0.0)
            result = FeatureCodingResult(
                artifact_id=artifact_id,
                feature_id=feature.feature_id,
                feature_name=feature.feature_name,
                feature_type=feature.feature_type,
                coded_value=str(item.get("coded_value") or "").strip(),
                confidence=confidence,
                manual_review=bool(item.get("manual_review", confidence < self.cfg.coding_min_confidence)),
                validation_status=_valid_literal(item.get("validation_status"), {"valid", "invalid", "needs_review"}, "needs_review"),
                identity_status=_valid_literal(item.get("identity_status"), {"supported", "weakly_supported", "unsupported", "conflicting"}, "supported" if evidence and confidence >= self.cfg.coding_min_confidence else "weakly_supported"),
                evidence=evidence,
                justification=str(item.get("justification") or "").strip(),
                conflicts=[str(x) for x in (item.get("conflicts") or []) if str(x).strip()],
                missing_evidence=[str(x) for x in (item.get("missing_evidence") or []) if str(x).strip()],
                audit={
                    "coding_mode": "per_product_bulk",
                    "bulk_llm_usage": usage,
                    "bulk_raw_llm_parse_error": parse_error,
                    "bulk_evidence_ids_available": list(evidence_by_id.keys()),
                    "bulk_raw_content_chars": len(raw_content or ""),
                    "iterations": 1,
                },
            )
            out.append(self.validator.validate(feature, result))
        return out

    @staticmethod
    def _evidence_from_ids(item: dict[str, Any], evidence_by_id: dict[str, EvidenceItem]) -> list[EvidenceItem]:
        evidence_ids = item.get("evidence_used") or item.get("supporting_evidence_ids") or []
        evidence: list[EvidenceItem] = []
        if isinstance(evidence_ids, str):
            evidence_ids = [evidence_ids]
        if isinstance(evidence_ids, list):
            for evid in evidence_ids:
                eid = str(evid.get("evidence_id") if isinstance(evid, dict) else evid).strip()
                if eid in evidence_by_id and evidence_by_id[eid] not in evidence:
                    evidence.append(evidence_by_id[eid])
        return evidence

    def _build_product_evidence(self, features: list[FeatureRule], context: ProductArtifactContext) -> list[EvidenceItem]:
        terms = _feature_terms(features)
        out: list[EvidenceItem] = []
        total_chars = 0
        for rel in context.locatable_files:
            raw = context.read_text(rel, max_chars=self.cfg.coding_context_index_file_chars)
            if not raw.strip():
                continue
            text = _compact_for_terms(raw, terms, max_chars=max(1500, self.cfg.coding_bulk_context_chars // 8))
            if not text.strip():
                continue
            if total_chars + len(text) > self.cfg.coding_bulk_context_chars:
                remaining = self.cfg.coding_bulk_context_chars - total_chars
                if remaining < 800:
                    break
                text = text[:remaining] + "\n...[truncated: product bulk context cap]"
            out.append(
                EvidenceItem(
                    evidence_id=f"D{len(out)+1:03d}",
                    source_file=rel,
                    evidence_type="product_context_snippet",
                    text=text,
                    score=max(1.0, 100.0 - len(out)),
                    strength="strong" if _strong_source(rel) else "medium",
                    metadata={"product_bulk_context": True, "raw_chars": len(raw), "sent_chars": len(text)},
                )
            )
            total_chars += len(text)
            if total_chars >= self.cfg.coding_bulk_context_chars:
                break
        return out

    @staticmethod
    def _feature_payload(feature: FeatureRule) -> dict[str, Any]:
        return {
            "feature_id": feature.feature_id,
            "feature_name": feature.feature_name,
            "feature_type": feature.feature_type,
            "definition": feature.definition,
            "allowed_values": feature.allowed_values,
            "aliases": feature.aliases,
            "evidence_hints": feature.evidence_hints,
            "requires_visual": feature.requires_visual,
            "missing_value": feature.missing_value,
            "pg_name": feature.pg_name,
            "feature_order": feature.feature_order,
            "classification_reason": feature.classification_reason,
        }

    @staticmethod
    def _fallback_result(artifact_id: str, feature: FeatureRule, evidence: list[EvidenceItem], reason: str) -> FeatureCodingResult:
        return FeatureCodingResult(
            artifact_id=artifact_id,
            feature_id=feature.feature_id,
            feature_name=feature.feature_name,
            feature_type=feature.feature_type,
            coded_value="",
            confidence=0.0,
            manual_review=True,
            validation_status="needs_review",
            identity_status="unsupported" if not evidence else "weakly_supported",
            evidence=evidence,
            justification=reason,
            conflicts=[],
            missing_evidence=[reason, "Product-level bulk coder did not produce a supported value."],
            audit={"coding_mode": "per_product_bulk", "bulk_fallback_result": True, "iterations": 1},
        )


def _feature_terms(features: list[FeatureRule]) -> list[str]:
    terms: list[str] = []
    for feature in features:
        terms.extend(feature.evidence_terms)
        terms.extend(feature.allowed_values)
    seen: set[str] = set()
    out: list[str] = []
    for term in sorted(terms, key=lambda x: len(str(x or "")), reverse=True):
        cleaned = " ".join(str(term or "").strip().split())
        key = cleaned.lower()
        if len(key) >= 2 and key not in seen:
            out.append(cleaned)
            seen.add(key)
    return out[:80]


def _compact_for_terms(text: str, terms: list[str], *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    lowered = text.lower()
    snippets: list[str] = []
    header = text[: min(700, max_chars // 3)].strip()
    if header:
        snippets.append(f"[file_start]\n{header}")
    window = max(500, max_chars // 4)
    for term in terms:
        idx = lowered.find(term.lower()) if term else -1
        if idx < 0:
            continue
        start = max(0, idx - window // 2)
        end = min(len(text), start + window)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet += "..."
        if snippet and all(snippet[:180] not in existing for existing in snippets):
            snippets.append(f"[matched_term={term}]\n{snippet}")
        if sum(len(s) for s in snippets) >= max_chars:
            break
    if len(snippets) == 1:
        return text[:max_chars].strip() + "\n...[truncated: no feature term hit]"
    compacted = "\n\n".join(snippets)
    if len(compacted) > max_chars:
        compacted = compacted[:max_chars] + "\n...[truncated]"
    return compacted


def _strong_source(rel: str) -> bool:
    return any(rel.endswith(x) for x in ["source.md", "product_evidence.json", "product_evidence.md", "claims.md"]) or "/tables/" in rel


def _clamp_float(value: Any, *, default: float) -> float:
    try:
        f = float(value)
    except Exception:
        return default
    return max(0.0, min(1.0, f))


def _valid_literal(value: Any, allowed: set[str], default: str) -> str:
    cleaned = str(value or "").strip().lower()
    return cleaned if cleaned in allowed else default


__all__ = ["ProductBulkCoder"]
