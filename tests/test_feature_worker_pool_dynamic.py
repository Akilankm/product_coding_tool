from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from product_coding_tool import CodingRequest, FeatureCodingResult, FeatureRule, ProductCodingAgent


def make_artifact(tmp_path: Path) -> Path:
    root = tmp_path / "scrape_worker_pool"
    retailer = root / "retailer"
    (retailer / "tables").mkdir(parents=True)
    (retailer / "manifests").mkdir()
    (retailer / "images").mkdir()
    (root / "request.json").write_text(json.dumps({"product_url": "https://example.com/p/1"}), encoding="utf-8")
    (root / "scrape_result.json").write_text(json.dumps({"success": True}), encoding="utf-8")
    (retailer / "source.md").write_text("Demo toy source text.", encoding="utf-8")
    (retailer / "claims.md").write_text("Demo claims.", encoding="utf-8")
    (retailer / "product_evidence.json").write_text(json.dumps({"brand": "DemoBrand"}), encoding="utf-8")
    (retailer / "product_evidence.md").write_text("Brand: DemoBrand", encoding="utf-8")
    (retailer / "metadata.json").write_text(json.dumps({"title": "DemoBrand Example Toy"}), encoding="utf-8")
    (retailer / "vision.md").write_text("No visual evidence required.", encoding="utf-8")
    (retailer / "quality_report.json").write_text(json.dumps({"quality": "good"}), encoding="utf-8")
    (retailer / "noise_report.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "evidence_recovery_report.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "manifests" / "artifact_manifest.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "manifests" / "image_manifest.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "manifests" / "table_manifest.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "manifests" / "agent_trace.json").write_text(json.dumps([]), encoding="utf-8")
    return root


def test_worker_pool_processes_eight_features_with_four_concurrent_workers(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PCT_LLM_ENABLED", "false")
    monkeypatch.setenv("PCT_CODING_OUTPUT_ROOT", str(tmp_path / "coded"))

    root = make_artifact(tmp_path)
    features = [FeatureRule(feature_id=f"F{i}", feature_name=f"Feature {i}") for i in range(1, 9)]

    lock = threading.Lock()
    active = 0
    peak_active = 0
    seen: list[str] = []
    seen_threads: set[str] = set()

    def fake_loop(self, feature, inventory, retriever, max_iterations):  # noqa: ANN001
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
            seen.append(feature.feature_id)
            seen_threads.add(threading.current_thread().name)
        time.sleep(0.05)
        with lock:
            active -= 1
        return FeatureCodingResult(
            artifact_id=inventory.artifact_id,
            feature_id=feature.feature_id,
            feature_name=feature.feature_name,
            feature_type=feature.feature_type,
            coded_value="demo",
            confidence=0.9,
            manual_review=False,
            validation_status="valid",
            identity_status="supported",
            evidence=[],
            justification="Test worker pool result.",
            audit={"iterations": 2, "parallel_safe": True, "worker_thread": threading.current_thread().name},
        )

    monkeypatch.setattr(ProductCodingAgent, "_code_feature_loop", fake_loop)
    result = ProductCodingAgent().run(
        CodingRequest(artifact_dir=root, features=features, max_parallel_features=4, output_dir=tmp_path / "coded_out")
    )

    assert [item.feature_id for item in result.results] == [f"F{i}" for i in range(1, 9)]
    assert sorted(seen) == [f"F{i}" for i in range(1, 9)]
    assert peak_active == 4
    assert len(seen_threads) <= 4
    assert all(item.audit["iterations"] == 2 for item in result.results)
    assert (tmp_path / "coded_out" / "coded_features.json").exists()
