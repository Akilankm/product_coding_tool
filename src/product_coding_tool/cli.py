"""CLI entrypoint for the artifact-grounded product coding agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import CodingRequest, ProductBatchCodingAgent, ProductBatchCodingRequest, ProductCodingAgent
from .log import setup_logging
from .rules.provider import FeatureRuleProvider


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Code product features from existing scrape artifact folders.")

    # Batch mode: the production path.
    parser.add_argument(
        "--batch-input",
        help="Product batch CSV containing input_id, PG_name, and product context columns.",
    )
    parser.add_argument(
        "--scraped-root",
        help="Root folder containing one scrape artifact folder per input_id, e.g. data/scraped/ROW_0001.",
    )
    parser.add_argument("--input-id", action="append", help="Optional input_id filter for batch mode. Can repeat.")
    parser.add_argument("--limit-products", type=int, help="Optional product row limit for smoke tests.")

    # Single product mode: useful for debugging.
    parser.add_argument("--artifact-dir", help="Path to one scrape artifact root or retailer subfolder.")
    parser.add_argument("--pg-name", help="Product group name to select from --pg-feature-input in single-product mode.")

    # Shared inputs.
    parser.add_argument(
        "--pg-feature-input",
        required=True,
        help="Canonical 5-column CSV: PG_name, features, type, allowed_values, description.",
    )
    parser.add_argument("--feature-name", action="append", help="Optional feature filter in single-product mode. Can repeat.")
    parser.add_argument("--limit-features", type=int, help="Optional limit after PG filtering; useful for smoke tests.")
    parser.add_argument("--output-dir", help="Output directory/root.")
    parser.add_argument("--max-iterations", type=int, default=3, help="Maximum evidence/coding loop iterations per feature.")
    parser.add_argument(
        "--max-parallel-features",
        type=int,
        default=None,
        help="Maximum features to code concurrently per product. Defaults to PCT/PCA_CODING_MAX_PARALLEL_FEATURES.",
    )
    parser.add_argument(
        "--skip-llm-preflight",
        action="store_true",
        help="Skip the one-call LLM preflight check before batch mode starts.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def _load_single_product_features(args: argparse.Namespace):
    return FeatureRuleProvider.from_pg_input(
        args.pg_feature_input,
        pg_name=args.pg_name,
        feature_names=args.feature_name,
        limit=args.limit_features,
    ).all()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    setup_logging(args.log_level)

    if args.batch_input:
        if not args.scraped_root:
            raise SystemExit("--scraped-root is required when --batch-input is provided.")
        request = ProductBatchCodingRequest(
            batch_input_csv=Path(args.batch_input),
            scraped_root=Path(args.scraped_root),
            pg_feature_input_csv=Path(args.pg_feature_input),
            output_dir=Path(args.output_dir) if args.output_dir else None,
            input_ids=args.input_id,
            limit_products=args.limit_products,
            limit_features=args.limit_features,
            max_iterations=max(1, args.max_iterations),
            max_parallel_features=args.max_parallel_features,
            llm_preflight=not args.skip_llm_preflight,
        )
        result = ProductBatchCodingAgent().run(request)
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return

    if not args.artifact_dir:
        raise SystemExit("Either --batch-input with --scraped-root, or --artifact-dir with --pg-name, is required.")
    if not args.pg_name:
        raise SystemExit("--pg-name is required for single-product mode.")

    request = CodingRequest(
        artifact_dir=Path(args.artifact_dir),
        features=_load_single_product_features(args),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        max_iterations=max(1, args.max_iterations),
        max_parallel_features=args.max_parallel_features,
    )
    result = ProductCodingAgent().run(request)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
