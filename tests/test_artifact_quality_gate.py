from product_coding_tool.agent.artifact_quality_gate import ArtifactQualityGate
from product_coding_tool.artifacts.context import ProductArtifactContext
from product_coding_tool.models import FeatureRule


def test_quality_gate_green_for_strong_artifact():
    context = ProductArtifactContext(
        artifact_id="ROW_0001",
        locatable_files=["retailer/source.md", "retailer/product_evidence.json"],
        file_texts={
            "retailer/source.md": "Brand: Acme Toys. Age: 3+. " * 120,
            "retailer/product_evidence.json": '{"brand":"Acme Toys","age":"3+"}',
        },
        artifact_quality_report={"warning_count": 0},
    )
    decision = ArtifactQualityGate().evaluate(context, [FeatureRule(feature_id="brand", feature_name="BRAND")])
    assert decision.decision == "GREEN"
    assert decision.bulk_allowed is True
    assert decision.rescrape_needed is False


def test_quality_gate_red_rescrape_for_empty_artifact():
    context = ProductArtifactContext(artifact_id="ROW_0002")
    decision = ArtifactQualityGate().evaluate(context, [FeatureRule(feature_id="brand", feature_name="BRAND")])
    assert decision.decision == "RED"
    assert decision.bulk_allowed is False
    assert decision.rescrape_needed is True
    assert decision.full_product_fallback_required is False


def test_quality_gate_red_full_fallback_for_weak_artifact_with_some_text():
    context = ProductArtifactContext(
        artifact_id="ROW_0003",
        locatable_files=["retailer/metadata.json"],
        file_texts={"retailer/metadata.json": "metadata text only " * 200},
        artifact_quality_report={"warning_count": 0},
    )
    decision = ArtifactQualityGate().evaluate(context, [FeatureRule(feature_id="brand", feature_name="BRAND")])
    assert decision.decision == "RED"
    assert decision.bulk_allowed is False
    assert decision.full_product_fallback_required is True
    assert decision.rescrape_needed is False
