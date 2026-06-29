from product_coding_tool.agent.product_bulk_coder import ProductBulkCoder
from product_coding_tool.models import EvidenceItem, FeatureRule


def test_product_bulk_parser_returns_one_result_per_feature():
    coder = ProductBulkCoder()
    features = [
        FeatureRule(feature_id="brand", feature_name="BRAND", feature_type="open_set"),
        FeatureRule(feature_id="age", feature_name="AGE", feature_type="closed_set", allowed_values=["3+", "6+"]),
    ]
    evidence = {
        "D001": EvidenceItem(
            evidence_id="D001",
            source_file="retailer/source.md",
            evidence_type="product_context_snippet",
            text="Brand: Acme Toys. Age: 3+.",
            strength="strong",
        )
    }
    data = {
        "features": [
            {
                "feature_id": "brand",
                "coded_value": "Acme Toys",
                "confidence": 0.92,
                "manual_review": False,
                "validation_status": "valid",
                "identity_status": "supported",
                "evidence_used": ["D001"],
                "justification": "Brand is directly stated.",
                "conflicts": [],
                "missing_evidence": [],
            },
            {
                "feature_id": "age",
                "coded_value": "3+",
                "confidence": 0.9,
                "manual_review": False,
                "validation_status": "valid",
                "identity_status": "supported",
                "evidence_used": ["D001"],
                "justification": "Age is directly stated.",
                "conflicts": [],
                "missing_evidence": [],
            },
        ]
    }

    results = coder._results_from_llm_data(
        artifact_id="ROW_0001",
        features=features,
        data=data,
        evidence_by_id=evidence,
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        raw_content="{}",
    )

    assert [r.feature_id for r in results] == ["brand", "age"]
    assert results[0].coded_value == "Acme Toys"
    assert results[0].validation_status == "valid"
    assert results[1].coded_value == "3+"
    assert results[1].manual_review is False


def test_product_bulk_parser_marks_missing_feature_for_review():
    coder = ProductBulkCoder()
    feature = FeatureRule(feature_id="missing", feature_name="MISSING FEATURE", feature_type="open_set")
    evidence = {
        "D001": EvidenceItem(
            evidence_id="D001",
            source_file="retailer/source.md",
            evidence_type="product_context_snippet",
            text="Some product text.",
        )
    }

    results = coder._results_from_llm_data(
        artifact_id="ROW_0001",
        features=[feature],
        data={"features": []},
        evidence_by_id=evidence,
        usage={},
        raw_content="{}",
    )

    assert len(results) == 1
    assert results[0].manual_review is True
    assert results[0].validation_status == "needs_review"
    assert results[0].audit["bulk_missing_feature_result"] is True
