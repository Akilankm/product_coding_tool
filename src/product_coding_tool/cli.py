"""CLI entrypoint for the artifact-grounded product coding agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import CodingRequest, FeatureRule, ProductCodingAgent
from .log import setup_logging
from .rules.provider import FeatureRuleProvider


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Code product features from an existing scrape artifact folder.")
    parser.add_argument("--artifact-dir", required=True, help="Path to scrape artifact root or retailer subfolder.")
    parser.add_argument("--features-json", help="Feature rules JSON list or {features:[...]}")
    parser.add_argument("--features-csv", help="Feature rules CSV with feature_id, feature_name, feature_type, allowed_values")
    parser.add_argument("--feature", action="append", help="Inline open-set feature name for quick testing. Can repeat.")
    parser.add_argument("--output-dir", help="Output directory. Defaults to PCT/PCA_CODING_OUTPUT_ROOT/<artifact_id>.")
    parser.add_argument("--max-iterations", type=int, default=3, help="Maximum evidence/coding loop iterations per feature.")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def load_features(args: argparse.Namespace) -> list[FeatureRule]:
    if args.features_json:
        return FeatureRuleProvider.from_json(args.features_json).all()
    if args.features_csv:
        return FeatureRuleProvider.from_csv(args.features_csv).all()
    if args.feature:
        return [
            FeatureRule(feature_id=name.lower().replace(" ", "_"), feature_name=name, feature_type="open_set")
            for name in args.feature
        ]
    raise SystemExit("Provide --features-json, --features-csv, or at least one --feature.")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    setup_logging(args.log_level)
    request = CodingRequest(
        artifact_dir=Path(args.artifact_dir),
        features=load_features(args),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        max_iterations=max(1, args.max_iterations),
    )
    result = ProductCodingAgent().run(request)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
