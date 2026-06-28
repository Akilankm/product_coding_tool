from __future__ import annotations

import json
from pathlib import Path

from product_coding_tool import CodingRequest, FeatureRule, ProductCodingAgent


def make_artifact(tmp_path: Path) -> Path:
    root = tmp_path / "scrape_parallel"
    retailer = root / "retailer"
    (retailer / "tables").mkdir(parents=True)
    (retailer / "manifests").mkdir()
    (retailer / "images").mkdir()
    (root / "request.json").write_text(json.dumps({"product_url": "https://example.com/p/1"}), encoding="utf-8")
    (root / "scrape_result.json").write_text(json.dumps({"success": True}), encoding="utf-8")
    (retailer / "source.md").write_text("Product: DemoBrand toy. Manufacturer: DemoMaker. No batteries required.", encoding="utf-8")
    (retailer / "claims.md").write_text("Brand: DemoBrand\nManufacturer: DemoMaker", encoding="utf-8")
    (retailer / "product_evidence.json").write_text(json.dumps({"brand": "DemoBrand", "manufacturer": "DemoMaker"}), encoding="utf-8")
    (retailer / "product_evidence.md").write_text("Brand: DemoBrand", encoding="utf-8")
    (retailer / "metadata.json").write_text(json.dumps({"title": "DemoBrand Example Toy"}), encoding="utf-8")
    (retailer / "vision.md").write_text("No relevant visual details.", encoding="utf-8")
    (retailer / "quality_report.json").write_text(json.dumps({"quality": "good"}), encoding="utf-8")
    (retailer / "noise_report.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "evidence_recovery_report.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "manifests" / "artifact_manifest.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "manifests" / "image_manifest.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "manifests" / "table_manifest.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "manifests" / "agent_trace.json").write_text(json.dumps([]), encoding="utf-8")
    return root


def test_parallel_feature_coding_preserves_input_order_and_writes_outputs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PCT_LLM_ENABLED", "false")
    monkeypatch.setenv("PCT_CODING_OUTPUT_ROOT", str(tmp_path / "coded"))
    monkeypatch.setenv("PCT_CODING_MAX_PARALLEL_FEATURES", "3")
    root = make_artifact(tmp_path)
    features = [
        FeatureRule(feature_id="F1", feature_name="BRAND", feature_type="open_set"),
        FeatureRule(feature_id="F2", feature_name="TOY MANUFACTURER", feature_type="open_set"),
        FeatureRule(feature_id="F3", feature_name="Battery Required", feature_type="closed_set", allowed_values=["Yes", "No", "Not stated"]),
    ]
    result = ProductCodingAgent().run(CodingRequest(artifact_dir=root, features=features, max_parallel_features=3))
    assert [r.feature_id for r in result.results] == ["F1", "F2", "F3"]
    assert all(r.audit.get("parallel_safe") is True for r in result.results)
    assert (tmp_path / "coded" / "scrape_parallel" / "coded_features.json").exists()
