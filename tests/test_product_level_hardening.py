from product_coding_tool.agent.product_level import ProductLevelCodingAgent
from product_coding_tool.models import FeatureCodingResult, FeatureRule


def _result(feature: FeatureRule, *, value: str = "", audit: dict | None = None) -> FeatureCodingResult:
    return FeatureCodingResult(
        artifact_id="ROW_0001",
        feature_id=feature.feature_id,
        feature_name=feature.feature_name,
        feature_type=feature.feature_type,
        coded_value=value,
        confidence=0.0 if not value else 0.9,
        manual_review=not bool(value),
        validation_status="needs_review" if not value else "valid",
        identity_status="unsupported" if not value else "supported",
        evidence=[],
        justification="test",
        audit=audit or {},
    )


def test_systemic_bulk_failure_when_half_or_more_features_are_placeholders():
    features = [FeatureRule(feature_id=f"f{i}", feature_name=f"Feature {i}") for i in range(4)]
    results = [_result(feature, audit={"bulk_fallback_result": True}) for feature in features]
    assert ProductLevelCodingAgent()._is_systemic_bulk_failure(results, features) is True


def test_systemic_bulk_failure_false_for_mostly_valid_bulk_result():
    features = [FeatureRule(feature_id=f"f{i}", feature_name=f"Feature {i}") for i in range(4)]
    results = [
        _result(features[0], value="A"),
        _result(features[1], value="B"),
        _result(features[2], value="C"),
        _result(features[3], audit={"bulk_missing_feature_result": True}),
    ]
    assert ProductLevelCodingAgent()._is_systemic_bulk_failure(results, features) is False
