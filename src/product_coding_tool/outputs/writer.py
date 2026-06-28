"""Writers for JSON, CSV, and Markdown audit artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ..config import get_config
from ..log import logger
from ..models import BatchCodingResult, EvidenceItem, FeatureCodingResult
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
            out = self.cfg.output_root / batch.artifact_id
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
        fields = [
            "artifact_id",
            "feature_id",
            "feature_name",
            "feature_type",
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
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for result in batch.results:
                writer.writerow(
                    {
                        "artifact_id": result.artifact_id,
                        "feature_id": result.feature_id,
                        "feature_name": result.feature_name,
                        "feature_type": result.feature_type,
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
                )

    def _write_trace(self, batch: BatchCodingResult, path: Path) -> None:
        payload = {
            "artifact_id": batch.artifact_id,
            "artifact_dir": str(batch.artifact_dir),
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


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


__all__ = ["ResultWriter"]
