from __future__ import annotations

import json
from pathlib import Path

from product_coding_tool import CodingRequest, FeatureRule, ProductCodingAgent


def make_artifact(tmp_path: Path) -> Path:
    root = tmp_path / "scrape_contract"
    retailer = root / "retailer"
    (retailer / "tables").mkdir(parents=True)
    (retailer / "manifests").mkdir()
    (retailer / "images").mkdir()
    (root / "request.json").write_text(json.dumps({"product_url": "https://example.com/p/1"}), encoding="utf-8")
    (root / "scrape_result.json").write_text(json.dumps({"success": True}), encoding="utf-8")
    (retailer / "source.md").write_text("Product: Example Toy. Brand: DemoBrand. No batteries required.", encoding="utf-8")
    (retailer / "claims.md").write_text("Brand: DemoBrand", encoding="utf-8")
    (retailer / "product_evidence.json").write_text(json.dumps({"brand": "DemoBrand"}), encoding="utf-8")
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


def test_agent_runs_without_llm_credentials_and_writes_outputs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PCT_LLM_ENABLED", "false")
    monkeypatch.setenv("PCT_CODING_OUTPUT_ROOT", str(tmp_path / "coded"))
    root = make_artifact(tmp_path)
    feature = FeatureRule(feature_id="BRAND", feature_name="BRAND", feature_type="open_set")
    result = ProductCodingAgent().run(CodingRequest(artifact_dir=root, features=[feature]))
    assert result.artifact_id == "scrape_contract"
    assert len(result.results) == 1
    assert result.results[0].manual_review is True  # deterministic fallback does not invent a value
    out = tmp_path / "coded" / "scrape_contract"
    assert (out / "coded_features.json").exists()
    assert (out / "coded_features.csv").exists()
    assert (out / "coding_audit.md").exists()
