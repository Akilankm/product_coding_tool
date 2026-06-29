"""Writers for JSON, CSV, and Markdown audit artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ..config import get_config
from ..log import logger
from ..models import BatchCodingResult, ProductBatchCodingResult
from .audit import AuditRenderer


class ResultWriter:
    def __init__(self) -> None:
        self.cfg = get_config()
        self.audit = AuditRenderer()

    def resolve_output_dir(self, batch: BatchCodingResult, output_dir: str | Path | None = None) -> Path:
        if output_dir:
            out = Path(output_dir)
        elif batch.output_dir:
            out = Path(batch.output_dir)
        else:
            out = self.cfg.output_root / (batch.product_id or batch.artifact_id)
        out.mkdir(parents=True, exist_ok=True)
        return out

    def write(self, batch: BatchCodingResult, *, output_dir: str | Path | None = None) -> Path:
        out = self.resolve_output_dir(batch, output_dir)
        (out / "coded_features.json").write_text(
            json.dumps(batch.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._write_csv(batch, out / "coded_features.csv")
        (out / "coding_audit.md").write_text(self.audit.render(batch), encoding="utf-8")
        self._write_trace(batch, out / "agent_trace.json")
        logger.info("Wrote product coding outputs to {}", out)
        return out

    def _write_csv(self, batch: BatchCodingResult, path: Path) -> None:
        fields = _coded_feature_fields()
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for result in batch.results:
                writer.writerow(_result_to_row(batch, result))

    def _write_trace(self, batch: BatchCodingResult, path: Path) -> None:
        payload = {
            "artifact_id": batch.artifact_id,
            "artifact_dir": str(batch.artifact_dir),
            "product_id": batch.product_id,
            "product_context": batch.product_context,
            "results": [
                {
                    "feature_id": r.feature_id,
                    "feature_name": r.feature_name,
                    "audit": r.audit,
                    "evidence": [e.model_dump(mode="json") for e in r.evidence],
                    "manual_review": r.manual_review,
                    "validation_status": r.validation_status,
                    "identity_status": r.identity_status,
                }
                for r in batch.results
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class ProductBatchResultWriter:
    """Write combined outputs for many product artifacts."""

    def write(self, result: ProductBatchCodingResult, *, output_dir: str | Path) -> Path:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "batch_coding_result.json").write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._write_combined_csv(result, out / "combined_coded_features.csv")
        self._write_failed_csv(result, out / "failed_products.csv")
        logger.info(
            "Wrote batch product coding outputs to {} products={} failed={}",
            out,
            len(result.products),
            len(result.failed_products),
        )
        return out

    def _write_combined_csv(self, result: ProductBatchCodingResult, path: Path) -> None:
        # Include all product input CSV columns first, then coding output columns.
        input_fields = _collect_input_fields(result)
        coding_fields = _coded_feature_fields()
        fields = _unique([*input_fields, *coding_fields])
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for product in result.products:
                for feature_result in product.results:
                    row = dict(product.product_context or {})
                    row.update(_result_to_row(product, feature_result))
                    writer.writerow({field: row.get(field, "") for field in fields})

    def _write_failed_csv(self, result: ProductBatchCodingResult, path: Path) -> None:
        input_fields = _collect_failed_input_fields(result)
        fields = _unique(["input_id", "PG_name", "artifact_dir", "error_type", "error", *input_fields])
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for failed in result.failed_products:
                row = dict(failed.product_context or {})
                row.update(
                    {
                        "input_id": failed.input_id,
                        "PG_name": failed.pg_name,
                        "artifact_dir": str(failed.artifact_dir or ""),
                        "error_type": failed.error_type,
                        "error": failed.error,
                    }
                )
                writer.writerow({field: row.get(field, "") for field in fields})


def _coded_feature_fields() -> list[str]:
    return [
        "input_id",
        "artifact_id",
        "artifact_dir",
        "product_url",
        "main_text",
        "ean",
        "retailer_name",
        "country_code",
        "PG_name",
        "pg_name",
        "feature_order",
        "feature_id",
        "feature_name",
        "feature_type",
        "allowed_values",
        "coded_value",
        "confidence",
        "manual_review",
        "validation_status",
        "identity_status",
        "evidence_files",
        "justification",
        "conflicts",
        "missing_evidence",
    ]


def _result_to_row(batch: BatchCodingResult, result: Any) -> dict[str, Any]:
    audit = result.audit or {}
    context = dict(batch.product_context or {})
    context.update(audit.get("product_context") or {})
    return {
        "input_id": audit.get("input_id") or batch.product_id or context.get("input_id") or "",
        "artifact_id": result.artifact_id,
        "artifact_dir": str(batch.artifact_dir),
        "product_url": context.get("product_url", audit.get("product_url", "")),
        "main_text": context.get("main_text", audit.get("main_text", "")),
        "ean": context.get("ean", audit.get("ean", "")),
        "retailer_name": context.get("retailer_name", audit.get("retailer_name", "")),
        "country_code": context.get("country_code", audit.get("country_code", "")),
        "PG_name": context.get("PG_name", audit.get("pg_name", "")),
        "pg_name": audit.get("pg_name", context.get("PG_name", "")),
        "feature_order": audit.get("feature_order", ""),
        "feature_id": result.feature_id,
        "feature_name": result.feature_name,
        "feature_type": result.feature_type,
        "allowed_values": "; ".join(audit.get("allowed_values") or []),
        "coded_value": result.coded_value,
        "confidence": f"{result.confidence:.4f}",
        "manual_review": result.manual_review,
        "validation_status": result.validation_status,
        "identity_status": result.identity_status,
        "evidence_files": "; ".join(_unique([e.source_file for e in result.evidence])),
        "justification": result.justification,
        "conflicts": " | ".join(result.conflicts),
        "missing_evidence": " | ".join(result.missing_evidence),
    }


def _collect_input_fields(result: ProductBatchCodingResult) -> list[str]:
    fields: list[str] = []
    for product in result.products:
        fields.extend((product.product_context or {}).keys())
    return _unique([str(x) for x in fields])


def _collect_failed_input_fields(result: ProductBatchCodingResult) -> list[str]:
    fields: list[str] = []
    for failed in result.failed_products:
        fields.extend((failed.product_context or {}).keys())
    return _unique([str(x) for x in fields])


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


__all__ = ["ResultWriter", "ProductBatchResultWriter"]
