from __future__ import annotations

import csv
from pathlib import Path

import pytest

from product_coding_tool.rules.pg_input import PGFeatureInputError, PGFeatureInputProvider


def test_pg_feature_input_uses_canonical_five_column_csv(tmp_path: Path) -> None:
    path = tmp_path / "pg_feature_coding_input.csv"
    rows = [
        {
            "PG_name": "Figures/Build Sets",
            "features": "BRAND",
            "type": "open_set",
            "allowed_values": "",
            "description": "Brand under which the toy is sold.",
        },
        {
            "PG_name": "Figures/Build Sets",
            "features": "TYPE TOY",
            "type": "closed_set",
            "allowed_values": "Action Figures & Accessories & Playsets; Figures & Playsets",
            "description": "Type of the toy/category.",
        },
        {
            "PG_name": "Games/Puzzles",
            "features": "TYPE",
            "type": "closed_set",
            "allowed_values": "Adult Games; Brainteasers",
            "description": "Type of the toy/category.",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["PG_name", "features", "type", "allowed_values", "description"])
        writer.writeheader()
        writer.writerows(rows)

    provider = PGFeatureInputProvider.from_file(path)
    features = provider.features_for_pg(pg_name="Figures/Build Sets")

    assert [f.feature_name for f in features] == ["BRAND", "TYPE TOY"]
    assert features[0].feature_type == "open_set"
    assert features[0].allowed_values == []
    assert features[0].feature_id == "FIGURES_BUILD_SETS_BRAND"
    assert features[1].feature_type == "closed_set"
    assert features[1].allowed_values == ["Action Figures & Accessories & Playsets", "Figures & Playsets"]
    assert features[1].pg_name == "Figures/Build Sets"


def test_closed_set_requires_allowed_values(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(
        "PG_name,features,type,allowed_values,description\n"
        "Figures/Build Sets,TYPE TOY,closed_set,,Type of toy\n",
        encoding="utf-8",
    )
    with pytest.raises(PGFeatureInputError, match="closed_set but allowed_values is blank"):
        PGFeatureInputProvider.from_file(path)


def test_multiple_pgs_require_pg_name(tmp_path: Path) -> None:
    path = tmp_path / "pg_feature_coding_input.csv"
    path.write_text(
        "PG_name,features,type,allowed_values,description\n"
        "Figures/Build Sets,BRAND,open_set,,Brand\n"
        "Games/Puzzles,BRAND,open_set,,Brand\n",
        encoding="utf-8",
    )
    provider = PGFeatureInputProvider.from_file(path)
    with pytest.raises(PGFeatureInputError, match="multiple PGs"):
        provider.features_for_pg()


def test_pg_alias_normalizes_toy_vehicles_playset(tmp_path: Path) -> None:
    path = tmp_path / "pg_feature_coding_input.csv"
    path.write_text(
        "PG_name,features,type,allowed_values,description\n"
        "Vehicles / Playsets,BRAND,open_set,,Brand\n"
        "Vehicles / Playsets,TYPE,closed_set,Die Cast; Playsets,Type\n",
        encoding="utf-8",
    )
    provider = PGFeatureInputProvider.from_file(path)
    assert provider.resolve_pg_name("TOY VEHICLES/PLAYSET") == "Vehicles / Playsets"
    features = provider.features_for_pg(pg_name="TOY VEHICLES/PLAYSET")
    assert [f.feature_name for f in features] == ["BRAND", "TYPE"]
    assert all(f.pg_name == "Vehicles / Playsets" for f in features)


def test_pg_alias_normalizes_validation_batch_pg_names(tmp_path: Path) -> None:
    path = tmp_path / "pg_feature_coding_input.csv"
    path.write_text(
        "PG_name,features,type,allowed_values,description\n"
        "All Other Miscellaneous Toys,BRAND,open_set,,Brand\n"
        "Vehicles / Playsets,BRAND,open_set,,Brand\n"
        "Infant / Preschool Toys,BRAND,open_set,,Brand\n"
        "Figures/Build Sets,BRAND,open_set,,Brand\n"
        "Games/Puzzles,BRAND,open_set,,Brand\n"
        "Dolls/Fashion Toys,BRAND,open_set,,Brand\n"
        "Electr/Educat Toys,BRAND,open_set,,Brand\n",
        encoding="utf-8",
    )
    provider = PGFeatureInputProvider.from_file(path)
    expected = {
        "ALL OTHER MISC. TOYS": "All Other Miscellaneous Toys",
        "ALL OTHER MISC TOYS": "All Other Miscellaneous Toys",
        "TOY VEHICLES/PLAYSET": "Vehicles / Playsets",
        "INFANT/PRESCHOOL TOY": "Infant / Preschool Toys",
        "FIGURES/BUILD SETS": "Figures/Build Sets",
        "GAMES/PUZZLES": "Games/Puzzles",
        "DOLLS/FASHION TOYS": "Dolls/Fashion Toys",
        "ELECTR/EDUCAT TOYS": "Electr/Educat Toys",
    }
    for raw, canonical in expected.items():
        assert provider.resolve_pg_name(raw) == canonical
