"""Deterministic validation and review gates for coded feature values."""

from __future__ import annotations

from ..config import get_config
from ..models import FeatureCodingResult, FeatureRule


def normalize_value(value: str) -> str:
    return " ".join((value or "").strip().split()).lower()


class RuleValidator:
    def __init__(self) -> None:
        self.cfg = get_config()

    def validate(self, feature: FeatureRule, result: FeatureCodingResult) -> FeatureCodingResult:
        value = (result.coded_value or "").strip()
        conflicts = list(result.conflicts or [])
        missing = list(result.missing_evidence or [])
        validation_status = result.validation_status
        identity_status = result.identity_status
        manual_review = result.manual_review

        if not value:
            missing.append("No coded value returned.")
            validation_status = "needs_review"
            identity_status = "unsupported"
            manual_review = True

        if feature.feature_type == "closed_set" and value:
            if feature.allowed_values:
                allowed_by_norm = {normalize_value(v): v for v in feature.allowed_values}
                norm = normalize_value(value)
                if norm in allowed_by_norm:
                    value = allowed_by_norm[norm]
                    validation_status = "valid" if result.evidence and not conflicts else "needs_review"
                else:
                    validation_status = "invalid"
                    identity_status = "unsupported"
                    manual_review = True
                    conflicts.append(
                        f"Closed-set value '{result.coded_value}' is not in allowed_values: {feature.allowed_values}"
                    )
            else:
                # The PG input can mark a feature as closed_set without shipping the
                # full allowed-value list. Do not reject the coded value; keep it
                # as evidence-backed but require manual/rulebook validation.
                validation_status = "needs_review"
                manual_review = True
                msg = "Closed-set feature has no allowed_values in the PG feature input; validate against the rulebook allowed list."
                if msg not in missing:
                    missing.append(msg)
        elif feature.feature_type == "open_set" and value:
            validation_status = "valid" if result.evidence and not conflicts else "needs_review"

        if not result.evidence:
            identity_status = "unsupported"
            manual_review = True
            if "No evidence attached to final coded value." not in missing:
                missing.append("No evidence attached to final coded value.")
        elif result.confidence < self.cfg.coding_min_confidence:
            identity_status = "weakly_supported" if identity_status == "supported" else identity_status
            manual_review = True
        elif not conflicts and validation_status == "valid":
            identity_status = "supported"

        if conflicts:
            identity_status = "conflicting"
            manual_review = True

        return result.model_copy(
            update={
                "coded_value": value,
                "validation_status": validation_status,
                "identity_status": identity_status,
                "manual_review": manual_review,
                "conflicts": _dedupe(conflicts),
                "missing_evidence": _dedupe(missing),
            }
        )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.strip().lower()
        if key and key not in seen:
            out.append(value.strip())
            seen.add(key)
    return out


__all__ = ["RuleValidator", "normalize_value"]
