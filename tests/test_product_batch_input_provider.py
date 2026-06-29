from __future__ import annotations

from pathlib import Path

import pytest

from product_coding_tool.inputs.product_batch import ProductBatchInputError, ProductBatchInputProvider


def test_product_batch_input_provider_reads_input_id_pg_name_and_context(tmp_path: Path) -> None:
    path = tmp_path / "batch.csv"
    path.write_text(
        "input_id,product_url,main_text,PG_name,ean,retailer_name,country_code\n"
        "ROW_0001,https://example.com/p1,Demo toy,Figures/Build Sets,123,Retailer,CZ\n"
        "ROW_0002,https://example.com/p2,Demo plush,PLUSH/PUPPETS TOYS,456,Retailer,CO\n",
        encoding="utf-8",
    )

    provider = ProductBatchInputProvider.from_file(path)
    rows = provider.filter_rows(input_ids=["ROW_0002"])

    assert provider.input_ids() == ["ROW_0001", "ROW_0002"]
    assert len(rows) == 1
    assert rows[0].input_id == "ROW_0002"
    assert rows[0].pg_name == "PLUSH/PUPPETS TOYS"
    assert rows[0].fields["main_text"] == "Demo plush"
    assert rows[0].fields["PG_name"] == "PLUSH/PUPPETS TOYS"


def test_product_batch_input_requires_input_id_and_pg_name(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("input_id,main_text\nROW_0001,Demo\n", encoding="utf-8")
    with pytest.raises(ProductBatchInputError, match="PG_name"):
        ProductBatchInputProvider.from_file(path)
