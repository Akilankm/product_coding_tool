from product_coding_tool.artifacts.context import ProductArtifactContextBuilder
from product_coding_tool.artifacts.navigator import ArtifactNavigator


def test_product_artifact_context_indexes_text_once(tmp_path):
    artifact = tmp_path / "ROW_0001"
    retailer = artifact / "retailer"
    retailer.mkdir(parents=True)
    (retailer / "source.md").write_text("Brand: Acme Toys\nAge: 3+\n", encoding="utf-8")
    (retailer / "claims.md").write_text("Battery not required", encoding="utf-8")
    (retailer / "product_evidence.json").write_text('{"brand":"Acme Toys"}', encoding="utf-8")

    navigator = ArtifactNavigator(artifact)
    inventory = navigator.inventory()
    context = ProductArtifactContextBuilder(navigator).build(inventory)

    assert context.artifact_id == "ROW_0001"
    assert "retailer/source.md" in context.locatable_files
    assert "Brand: Acme Toys" in context.read_text("retailer/source.md")
    assert context.file_count >= 3
    assert context.total_text_chars > 0


def test_product_artifact_context_records_malformed_json_warning(tmp_path):
    artifact = tmp_path / "ROW_0002"
    retailer = artifact / "retailer"
    retailer.mkdir(parents=True)
    (retailer / "source.md").write_text("Brand: Example", encoding="utf-8")
    (retailer / "metadata.json").write_text("not json", encoding="utf-8")

    navigator = ArtifactNavigator(artifact)
    context = ProductArtifactContextBuilder(navigator).build(navigator.inventory())

    assert context.artifact_quality_report["has_warnings"] is True
    assert context.artifact_quality_report["warning_count"] >= 1
