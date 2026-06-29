from product_coding_tool.agent.planner import EvidencePlanner
from product_coding_tool.config import get_config
from product_coding_tool.models import ArtifactInventory, FeatureRule


def test_low_latency_defaults(monkeypatch):
    monkeypatch.delenv("PCT_CODING_PLANNER_MODE", raising=False)
    monkeypatch.delenv("PCT_CODING_MAX_ITERATIONS", raising=False)
    cfg = get_config()
    assert cfg.coding_planner_mode == "deterministic"
    assert cfg.coding_max_iterations == 1


def test_evidence_planner_default_is_deterministic(monkeypatch):
    monkeypatch.delenv("PCT_CODING_PLANNER_MODE", raising=False)
    feature = FeatureRule(
        pg_name="Vehicles / Playsets",
        feature_id="VEHICLES_PLAYSETS_BRAND",
        feature_name="BRAND",
        feature_type="open_set",
        allowed_values=[],
        aliases=["brand"],
    )
    inventory = ArtifactInventory(
        artifact_id="ROW_0001",
        artifact_root="/tmp/ROW_0001",
        retailer_dir="/tmp/ROW_0001/retailer",
        files=[],
        missing_expected_files=[],
    )
    plan = EvidencePlanner().plan(feature, inventory)
    assert "Deterministic evidence plan" in plan.reason
    assert "retailer/source.md" in plan.files_to_read
    assert "brand" in [x.lower() for x in plan.evidence_queries]
