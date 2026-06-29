from __future__ import annotations

import csv
import json
from pathlib import Path

from product_coding_tool import ProductBatchCodingAgent, ProductBatchCodingRequest


def make_artifact(root: Path, input_id: str) -> Path:
    artifact = root / input_id
    retailer = artifact / "retailer"
    (retailer / "tables").mkdir(parents=True)
    (retailer / "manifests").mkdir()
    (retailer / "images").mkdir()
    (artifact / "request.json").write_text(json.dumps({"product_url": "https://example.com/p/1"}), encoding="utf-8")
    (artifact / "scrape_result.json").write_text(json.dumps({"success": True}), encoding="utf-8")
    (retailer / "source.md").write_text("Product: DemoBrand toy. No batteries required.", encoding="utf-8")
    (retailer / "claims.md").write_text("Brand: DemoBrand", encoding="utf-8")
    (retailer / "product_evidence.json").write_text(json.dumps({"brand": "DemoBrand"}), encoding="utf-8")
    (retailer / "product_evidence.md").write_text("Brand: DemoBrand", encoding="utf-8")
    (retailer / "metadata.json").write_text(json.dumps({"title": "DemoBrand Toy"}), encoding="utf-8")
    (retailer / "vision.md").write_text("No visual details.", encoding="utf-8")
    (retailer / "quality_report.json").write_text(json.dumps({"quality": "good"}), encoding="utf-8")
    (retailer / "noise_report.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "evidence_recovery_report.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "manifests" / "artifact_manifest.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "manifests" / "image_manifest.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "manifests" / "table_manifest.json").write_text(json.dumps({}), encoding="utf-8")
    (retailer / "manifests" / "agent_trace.json").write_text(json.dumps([]), encoding="utf-8")
    return artifact


def test_batch_product_coding_maps_input_id_to_artifact_and_pg_to_features(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PCT_LLM_ENABLED", "false")
    monkeypatch.setenv("PCT_CODING_OUTPUT_ROOT", str(tmp_path / "coded_default"))

    scraped_root = tmp_path / "data" / "scraped"
    make_artifact(scraped_root, "ROW_0001")
    make_artifact(scraped_root, "ROW_0002")

    batch_csv = tmp_path / "product_batch.csv"
    batch_csv.write_text(
        "input_id,product_url,main_text,PG_name,ean,retailer_name,country_code\n"
        "ROW_0001,https://example.com/p1,Demo toy,Figures/Build Sets,123,Retailer,CZ\n"
        "ROW_0002,https://example.com/p2,Demo toy 2,Games/Puzzles,456,Retailer,CO\n",
        encoding="utf-8",
    )
    pg_csv = tmp_path / "pg_feature_coding_input.csv"
    pg_csv.write_text(
        "PG_name,features,type,allowed_values,description\n"
        "Figures/Build Sets,BRAND,open_set,,Brand name\n"
        "Figures/Build Sets,Battery Required,closed_set,Yes; No; Not stated,Battery requirement\n"
        "Games/Puzzles,BRAND,open_set,,Brand name\n",
        encoding="utf-8",
    )
    out = tmp_path / "coded" / "batch"

    result = ProductBatchCodingAgent().run(
        ProductBatchCodingRequest(
            batch_input_csv=batch_csv,
            scraped_root=scraped_root,
            pg_feature_input_csv=pg_csv,
            output_dir=out,
            max_parallel_features=2,
        )
    )

    assert len(result.products) == 2
    assert len(result.failed_products) == 0
    assert [p.product_id for p in result.products] == ["ROW_0001", "ROW_0002"]
    assert len(result.products[0].results) == 2
    assert len(result.products[1].results) == 1
    assert (out / "ROW_0001" / "coded_features.csv").exists()
    assert (out / "combined_coded_features.csv").exists()

    with (out / "combined_coded_features.csv").open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    assert rows[0]["input_id"] == "ROW_0001"
    assert rows[0]["PG_name"] == "Figures/Build Sets"
    assert rows[0]["main_text"] == "Demo toy"


def test_batch_product_coding_records_missing_artifact_as_failed_product(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PCT_LLM_ENABLED", "false")
    scraped_root = tmp_path / "scraped"
    scraped_root.mkdir()
    batch_csv = tmp_path / "product_batch.csv"
    batch_csv.write_text("input_id,PG_name,main_text\nROW_MISSING,Figures/Build Sets,Demo\n", encoding="utf-8")
    pg_csv = tmp_path / "pg_feature_coding_input.csv"
    pg_csv.write_text("PG_name,features,type,allowed_values,description\nFigures/Build Sets,BRAND,open_set,,Brand\n", encoding="utf-8")
    out = tmp_path / "coded"

    result = ProductBatchCodingAgent().run(
        ProductBatchCodingRequest(
            batch_input_csv=batch_csv,
            scraped_root=scraped_root,
            pg_feature_input_csv=pg_csv,
            output_dir=out,
        )
    )

    assert result.products == []
    assert len(result.failed_products) == 1
    assert result.failed_products[0].input_id == "ROW_MISSING"
    assert (out / "failed_products.csv").exists()


def test_batch_product_coding_resolves_pg_alias_from_product_input(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PCT_LLM_ENABLED", "false")
    scraped_root = tmp_path / "scraped"
    make_artifact(scraped_root, "ROW_0001")
    batch_csv = tmp_path / "product_batch.csv"
    batch_csv.write_text(
        "input_id,PG_name,main_text\nROW_0001,TOY VEHICLES/PLAYSET,Vehicle demo\n",
        encoding="utf-8",
    )
    pg_csv = tmp_path / "pg_feature_coding_input.csv"
    pg_csv.write_text(
        "PG_name,features,type,allowed_values,description\n"
        "Vehicles / Playsets,BRAND,open_set,,Brand\n",
        encoding="utf-8",
    )
    out = tmp_path / "coded"
    result = ProductBatchCodingAgent().run(
        ProductBatchCodingRequest(
            batch_input_csv=batch_csv,
            scraped_root=scraped_root,
            pg_feature_input_csv=pg_csv,
            output_dir=out,
        )
    )
    assert len(result.products) == 1
    assert result.failed_products == []
    assert result.products[0].product_context["PG_name_resolved"] == "Vehicles / Playsets"


def test_batch_product_coding_canonicalizes_output_pg_name(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PCT_LLM_ENABLED", "false")
    scraped_root = tmp_path / "scraped"
    make_artifact(scraped_root, "ROW_0006")
    batch_csv = tmp_path / "product_batch.csv"
    batch_csv.write_text(
        "input_id,PG_name,main_text\nROW_0006,ALL OTHER MISC. TOYS,Other toy\n",
        encoding="utf-8",
    )
    pg_csv = tmp_path / "pg_feature_coding_input.csv"
    pg_csv.write_text(
        "PG_name,features,type,allowed_values,description\n"
        "All Other Miscellaneous Toys,BRAND,open_set,,Brand\n",
        encoding="utf-8",
    )
    out = tmp_path / "coded"
    result = ProductBatchCodingAgent().run(
        ProductBatchCodingRequest(
            batch_input_csv=batch_csv,
            scraped_root=scraped_root,
            pg_feature_input_csv=pg_csv,
            output_dir=out,
        )
    )
    assert len(result.products) == 1
    assert result.failed_products == []
    context = result.products[0].product_context
    assert context["PG_name"] == "All Other Miscellaneous Toys"
    assert context["PG_name_original"] == "ALL OTHER MISC. TOYS"
    assert context["PG_name_resolved"] == "All Other Miscellaneous Toys"
    with (out / "combined_coded_features.csv").open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["PG_name"] == "All Other Miscellaneous Toys"
    assert rows[0]["PG_name_original"] == "ALL OTHER MISC. TOYS"
