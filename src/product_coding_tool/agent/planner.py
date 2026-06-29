"""LLM-driven evidence planner with deterministic fallback."""

from __future__ import annotations

import json
from typing import Any

from ..config import get_config
from ..log import logger
from ..models import ArtifactInventory, EvidencePlan, FeatureRule
from ..prompts import P
from ..services.llm import get_llm_service
from .json_utils import parse_json_object


class EvidencePlanner:
    def __init__(self) -> None:
        self.cfg = get_config()

    def plan(self, feature: FeatureRule, inventory: ArtifactInventory) -> EvidencePlan:
        mode = (self.cfg.coding_planner_mode or "deterministic").strip().lower()
        if not self.cfg.llm_enabled or mode in {"deterministic", "static", "rule", "rules"}:
            plan = self._fallback_plan(feature)
            logger.debug("Evidence planner used deterministic mode for feature={} mode={}", feature.feature_name, mode)
            return plan.model_copy(
                update={
                    "reason": (
                        f"Deterministic evidence plan used; coding_planner_mode={mode}. "
                        "This avoids one LLM planner call per feature and uses default strong artifact sources plus feature terms."
                    )
                }
            )
        if mode not in {"llm", "auto"}:
            logger.warning(
                "Unknown PCT_CODING_PLANNER_MODE={!r}; using deterministic evidence planning for feature={}",
                mode,
                feature.feature_name,
            )
            return self._fallback_plan(feature)
        payload = {
            "feature": feature.model_dump(),
            "artifact_inventory": {
                "artifact_id": inventory.artifact_id,
                "files": [
                    {"relative_path": f.relative_path, "file_type": f.file_type, "bytes_size": f.bytes_size, "priority": f.priority}
                    for f in inventory.files
                ],
                "missing_expected_files": inventory.missing_expected_files,
            },
            "instructions": [
                "Use local artifact evidence only.",
                "Return files_to_read as relative artifact paths or globs.",
                "Use evidence_queries that will retrieve strongest evidence for this feature.",
            ],
        }
        try:
            resp = get_llm_service().predict(
                json.dumps(payload, ensure_ascii=False, indent=2),
                system_prompt=P.FEATURE_EVIDENCE_PLANNER.system,
                max_tokens=min(2048, self.cfg.llm_max_tokens),
                temperature=0.0,
                response_format={"type": "json_object"},
                purpose=P.FEATURE_EVIDENCE_PLANNER.name,
            )
            data = parse_json_object(resp.content)
            plan = EvidencePlan.model_validate(data)
            return self._merge_safety_defaults(feature, plan)
        except Exception as exc:
            logger.warning("Evidence planner failed for feature={}: {}. Falling back.", feature.feature_name, exc)
            return self._fallback_plan(feature)

    def _fallback_plan(self, feature: FeatureRule) -> EvidencePlan:
        files = [
            "retailer/source.md",
            "retailer/tables/*.md",
            "retailer/metadata.json",
            "retailer/product_evidence.json",
            "retailer/product_evidence.md",
            "retailer/claims.md",
        ]
        terms = feature.evidence_terms
        lname = feature.feature_name.lower()
        if feature.requires_visual or any(x in lname for x in ["color", "colour", "character", "figure", "package", "packaging", "pieces", "image"]):
            files.extend(["retailer/vision.md", "retailer/manifests/image_manifest.json"])
            needs_vision = True
        else:
            needs_vision = False
        if "battery" in lname:
            terms.extend(["battery", "batteries", "AA", "AAA", "requires", "included"])
        if "age" in lname:
            terms.extend(["age", "years", "months", "+", "recommended", "suitable"])
        if "brand" in lname:
            terms.extend(["brand", "manufacturer", "producer", "made by"])
        if "manufacturer" in lname or "manuf" in lname:
            terms.extend(["manufacturer", "producer", "vendor", "brand", "made by"])
        return self._merge_safety_defaults(
            feature,
            EvidencePlan(
                evidence_queries=_dedupe(terms),
                files_to_read=_dedupe(files),
                needs_vision=needs_vision,
                needs_images=feature.requires_visual,
                reason="Deterministic fallback plan based on feature name, aliases, allowed values, and default scrape artifact sources.",
            ),
        )

    def _merge_safety_defaults(self, feature: FeatureRule, plan: EvidencePlan) -> EvidencePlan:
        files = list(plan.files_to_read or [])
        defaults = [
            "retailer/source.md",
            "retailer/tables/*.md",
            "retailer/metadata.json",
            "retailer/product_evidence.json",
            "retailer/claims.md",
        ]
        for rel in defaults:
            if rel not in files:
                files.append(rel)
        queries = _dedupe([*(plan.evidence_queries or []), *feature.evidence_terms])
        return plan.model_copy(update={"files_to_read": _dedupe(files), "evidence_queries": queries})


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


__all__ = ["EvidencePlanner"]
