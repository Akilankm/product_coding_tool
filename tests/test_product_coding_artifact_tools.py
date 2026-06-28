from __future__ import annotations

import json
from pathlib import Path

from product_coding_tool.artifacts.navigator import ArtifactNavigator
from product_coding_tool.artifacts.reader import ArtifactReader
from product_coding_tool.artifacts.locator import ArtifactEvidenceLocator
from product_coding_tool.models import EvidencePlan, FeatureRule
from product_coding_tool.artifacts.evidence_packet import EvidencePacketBuilder


def make_artifact(tmp_path: Path) -> Path:
    root = tmp_path / "scrape_123"
    retailer = root / "retailer"
    (retailer / "tables").mkdir(parents=True)
    (retailer / "manifests").mkdir()
    (retailer / "images").mkdir()
    (root / "request.json").write_text(json.dumps({"product_url": "https://example.com/p/1", "main_text": "Bavytoy animal tube"}), encoding="utf-8")
    (root / "scrape_result.json").write_text(json.dumps({"success": True}), encoding="utf-8")
    (retailer / "source.md").write_text("# Bavytoy Animal Tube\nBrand: Bavytoy\nBattery: 3x AA batteries required.", encoding="utf-8")
    (retailer / "claims.md").write_text("- Brand claim: Bavytoy\n- Requires 3 AA batteries.", encoding="utf-8")
    (retailer / "product_evidence.json").write_text(json.dumps({"brand": "Bavytoy", "battery": "3x AA"}), encoding="utf-8")
    (retailer / "product_evidence.md").write_text("Brand: Bavytoy", encoding="utf-8")
    (retailer / "metadata.json").write_text(json.dumps({"title": "Bavytoy Animal Tube"}), encoding="utf-8")
    (retailer / "vision.md").write_text("Packaging visible: Bavytoy logo.", encoding="utf-8")
    (retailer / "quality_report.json").write_text(json.dumps({"quality": "good"}), encoding="utf-8")
    (retailer / "noise_report.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "evidence_recovery_report.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "tables" / "table_001.md").write_text("| Field | Value |\n| Battery | 3x AA batteries required |", encoding="utf-8")
    (retailer / "manifests" / "artifact_manifest.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "manifests" / "image_manifest.json").write_text(json.dumps({"images": []}), encoding="utf-8")
    (retailer / "manifests" / "table_manifest.json").write_text(json.dumps({"tables": ["table_001.md"]}), encoding="utf-8")
    (retailer / "manifests" / "agent_trace.json").write_text(json.dumps([]), encoding="utf-8")
    return root


def test_inventory_reader_locator_and_packet(tmp_path: Path):
    root = make_artifact(tmp_path)
    nav = ArtifactNavigator(root)
    inv = nav.inventory()
    assert inv.artifact_id == "scrape_123"
    assert inv.has_file("retailer/source.md")

    reader = ArtifactReader(nav)
    assert "Bavytoy" in reader.read_text("retailer/source.md")

    locator = ArtifactEvidenceLocator(nav, reader)
    hits = locator.locate(["battery", "AA"])
    assert hits
    assert hits[0].source_file in {"retailer/source.md", "retailer/tables/table_001.md"}

    feature = FeatureRule(
        feature_id="BATTERY_REQUIRED",
        feature_name="Battery Required",
        feature_type="closed_set",
        allowed_values=["Yes", "No", "Not stated"],
        evidence_hints=["battery", "AA"],
    )
    packet = EvidencePacketBuilder(nav, reader).build(
        feature,
        inv,
        EvidencePlan(evidence_queries=["battery", "AA"], files_to_read=["retailer/source.md", "retailer/tables/*.md"]),
    )
    assert packet.evidence
    assert any("battery" in item.text.lower() for item in packet.evidence)
