"""Markdown audit report rendering."""

from __future__ import annotations

from ..models import BatchCodingResult, FeatureCodingResult


class AuditRenderer:
    def render(self, batch: BatchCodingResult) -> str:
        lines: list[str] = []
        lines.append(f"# Product Coding Audit — {batch.artifact_id}")
        lines.append("")
        lines.append(f"Artifact: `{batch.artifact_dir}`")
        lines.append("")
        for result in batch.results:
            lines.extend(self._render_feature(result))
        return "\n".join(lines).rstrip() + "\n"

    def _render_feature(self, result: FeatureCodingResult) -> list[str]:
        lines = [
            f"## {result.feature_name} ({result.feature_id})",
            "",
            f"- **Coded value:** `{result.coded_value or '(empty)'}`",
            f"- **Confidence:** {result.confidence:.2f}",
            f"- **Manual review:** {result.manual_review}",
            f"- **Validation:** {result.validation_status}",
            f"- **Identity support:** {result.identity_status}",
            f"- **Justification:** {result.justification or '(none)' }",
            "",
        ]
        if result.evidence:
            lines.append("### Evidence used")
            lines.append("")
            for item in result.evidence:
                snippet = item.text.replace("\n", " ").strip()
                if len(snippet) > 500:
                    snippet = snippet[:500] + "..."
                lines.append(f"- `{item.evidence_id}` `{item.source_file}` — {snippet}")
            lines.append("")
        if result.conflicts:
            lines.append("### Conflicts")
            lines.extend(f"- {x}" for x in result.conflicts)
            lines.append("")
        if result.missing_evidence:
            lines.append("### Missing evidence")
            lines.extend(f"- {x}" for x in result.missing_evidence)
            lines.append("")
        trace = result.audit.get("iteration_trace") or []
        if trace:
            lines.append("### Iteration trace")
            lines.append("")
            for item in trace:
                lines.append(
                    f"- iteration={item.get('iteration')} retry={item.get('retry')} "
                    f"reason={item.get('retry_reason')} confidence={item.get('confidence')} "
                    f"validation={item.get('validation_status')} evidence_items={item.get('evidence_items')}"
                )
            lines.append("")
        files = result.audit.get("files_checked") or []
        if files:
            lines.append("### Files checked")
            lines.extend(f"- `{x}`" for x in files)
            lines.append("")
        quality_warning_count = result.audit.get("artifact_quality_warning_count")
        if quality_warning_count:
            lines.append("### Artifact quality")
            lines.append(f"- Warning count: {quality_warning_count}")
            lines.append("- See `artifact_quality_report.json` for file-level details.")
            lines.append("")
        return lines


__all__ = ["AuditRenderer"]
