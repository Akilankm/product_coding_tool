from __future__ import annotations

import csv
import json
from pathlib import Path

from product_coding_tool import CodingRequest, FeatureRule, ProductCodingAgent
from product_coding_tool.artifacts.navigator import ArtifactNavigator
from product_coding_tool.artifacts.reader import ArtifactReader
from product_coding_tool.models import EvidencePlan
from product_coding_tool.artifacts.evidence_packet import EvidencePacketBuilder


def make_bad_json_artifact(tmp_path: Path) -> Path:
    root = tmp_path / "ROW_BAD_JSON"
    retailer = root / "retailer"
    (retailer / "tables").mkdir(parents=True)
    (retailer / "manifests").mkdir()
    (root / "request.json").write_text(json.dumps({"product_url": "https://example.com"}), encoding="utf-8")
    (root / "scrape_result.json").write_text("not-json scrape result but contains Brand: DemoBrand", encoding="utf-8")
    (retailer / "metadata.json").write_text("title: DemoBrand Broken Metadata", encoding="utf-8")
    (retailer / "product_evidence.json").write_text(json.dumps({"brand": "DemoBrand"}), encoding="utf-8")
    (retailer / "source.md").write_text("Product: DemoBrand toy. Brand: DemoBrand.", encoding="utf-8")
    (retailer / "claims.md").write_text("Brand claim: DemoBrand", encoding="utf-8")
    (retailer / "vision.md").write_text("No visual details", encoding="utf-8")
    (retailer / "quality_report.json").write_text(json.dumps({"quality": "ok"}), encoding="utf-8")
    (retailer / "noise_report.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "evidence_recovery_report.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "manifests" / "image_manifest.json").write_text("image manifest markdown not json", encoding="utf-8")
    (retailer / "manifests" / "agent_trace.json").write_text(json.dumps([]), encoding="utf-8")
    return root


def test_invalid_json_is_recorded_once_and_outputs_quality_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PCT_LLM_ENABLED", "false")
    root = make_bad_json_artifact(tmp_path)
    feature = FeatureRule(feature_id="BRAND", feature_name="BRAND", feature_type="open_set")

    result = ProductCodingAgent().run(CodingRequest(artifact_dir=root, features=[feature], output_dir=tmp_path / "coded"))

    report = result.artifact_quality_report
    assert report["has_warnings"] is True
    malformed = {row["relative_path"] for row in report["malformed_json_files"]}
    assert "retailer/metadata.json" in malformed
    assert "retailer/manifests/image_manifest.json" in malformed
    assert (tmp_path / "coded" / "artifact_quality_report.json").exists()


def test_reader_caches_json_and_does_not_duplicate_quality_warnings(tmp_path: Path) -> None:
    root = make_bad_json_artifact(tmp_path)
    reader = ArtifactReader(ArtifactNavigator(root))
    for _ in range(5):
        reader.read_json("retailer/metadata.json")
    report = reader.quality_report().to_dict()
    malformed = [row for row in report["malformed_json_files"] if row["relative_path"] == "retailer/metadata.json"]
    assert len(malformed) == 1


def test_evidence_packet_compacts_large_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PCT_CODING_READ_FILE_CHARS", "6000")
    monkeypatch.setenv("PCT_CODING_EVIDENCE_CONTEXT_CHARS", "500")
    root = make_bad_json_artifact(tmp_path)
    huge = "A" * 5000 + " Brand: DemoBrand " + "B" * 5000
    (root / "retailer" / "source.md").write_text(huge, encoding="utf-8")
    nav = ArtifactNavigator(root)
    inv = nav.inventory()
    reader = ArtifactReader(nav)
    packet = EvidencePacketBuilder(nav, reader).build(
        FeatureRule(feature_id="BRAND", feature_name="BRAND", feature_type="open_set"),
        inv,
        EvidencePlan(evidence_queries=["Brand"], files_to_read=["retailer/source.md"]),
    )
    source_items = [item for item in packet.evidence if item.source_file == "retailer/source.md"]
    assert source_items
    assert len(source_items[0].text) < 2500
    assert "DemoBrand" in source_items[0].text
