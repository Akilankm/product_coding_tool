"""Batch product coding orchestration.

This module wires the three runtime inputs together:

1. Product batch CSV with `input_id` and `PG_name`
2. Scrape artifact root where each `input_id` is a folder name
3. PG feature CSV with `PG_name,features,type,allowed_values,description`
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .agent.orchestrator import ProductCodingAgent
from .inputs.product_batch import ProductBatchInputProvider
from .log import logger
from .models import (
    BatchCodingResult,
    CodingRequest,
    FailedProductCodingResult,
    ProductBatchCodingRequest,
    ProductBatchCodingResult,
    ProductInputRow,
)
from .outputs.writer import ProductBatchResultWriter
from .rules.pg_input import PGFeatureInputProvider
from .config import get_config
from .services.llm import get_llm_service


class ProductBatchCodingAgent:
    """Run the product coding agent across many scrape artifact folders.

    Product-level execution is intentionally sequential by default. Feature-level
    execution inside each product remains parallel through `max_parallel_features`.
    This prevents uncontrolled LLM fan-out while still accelerating the expensive
    feature coding step for each product.
    """

    def __init__(self, product_agent: ProductCodingAgent | None = None) -> None:
        self.product_agent = product_agent or ProductCodingAgent()

    def run(self, request: ProductBatchCodingRequest) -> ProductBatchCodingResult:
        product_provider = ProductBatchInputProvider.from_file(request.batch_input_csv)
        pg_provider = PGFeatureInputProvider.from_file(request.pg_feature_input_csv)
        rows = product_provider.filter_rows(input_ids=request.input_ids, limit=request.limit_products)
        logger.info(
            "ProductBatchCodingAgent start rows={} scraped_root={} pg_feature_input={}",
            len(rows),
            request.scraped_root,
            request.pg_feature_input_csv,
        )
        pg_name_audit = pg_provider.canonicalization_audit([row.pg_name for row in rows])
        unmatched_pg_names = sorted({item["original_pg_name"] for item in pg_name_audit if not item["matched"]})
        if unmatched_pg_names:
            logger.error(
                "Unmatched PG_name values before LLM calls: {}. Available canonical PGs: {}",
                unmatched_pg_names,
                pg_provider.pg_names(),
            )
        else:
            logger.info("All product batch PG_name values resolved to canonical PG names")
        self._preflight_llm_if_needed(request)

        products: list[BatchCodingResult] = []
        failed: list[FailedProductCodingResult] = []
        output_root = request.output_dir or _default_batch_output_dir()
        output_root.mkdir(parents=True, exist_ok=True)

        for row in rows:
            artifact_dir = request.scraped_root / row.input_id
            try:
                resolved_pg_name = pg_provider.resolve_pg_name(row.pg_name)
                features = pg_provider.features_for_pg(pg_name=resolved_pg_name, limit=request.limit_features)
                if not artifact_dir.exists():
                    raise FileNotFoundError(
                        f"Scrape artifact folder not found for input_id={row.input_id}: {artifact_dir}"
                    )
                logger.info(
                    "Coding product input_id={} pg_name={} resolved_pg_name={} artifact={} features={}",
                    row.input_id,
                    row.pg_name,
                    resolved_pg_name,
                    artifact_dir,
                    len(features),
                )
                product_context = dict(row.fields)
                # Make product output use the same canonical PG_name as the feature CSV.
                # Keep the original batch label separately for audit/debugging.
                product_context["PG_name_original"] = row.pg_name
                product_context["PG_name_resolved"] = resolved_pg_name
                product_context["PG_name"] = resolved_pg_name
                product_result = self.product_agent.run(
                    CodingRequest(
                        artifact_dir=artifact_dir,
                        features=features,
                        output_dir=output_root / row.input_id,
                        product_id=row.input_id,
                        product_context=product_context,
                        max_iterations=request.max_iterations,
                        max_parallel_features=request.max_parallel_features,
                    )
                )
                products.append(product_result)
            except Exception as exc:  # product-level isolation
                logger.exception("Product-level coding failed input_id={} pg_name={}", row.input_id, row.pg_name)
                failed.append(_failed(row, artifact_dir, exc))

        result = ProductBatchCodingResult(products=products, failed_products=failed, output_dir=output_root)
        ProductBatchResultWriter().write(result, output_dir=output_root)
        logger.info(
            "ProductBatchCodingAgent complete products={} failed={} output_dir={}",
            len(products),
            len(failed),
            output_root,
        )
        return result

    def _preflight_llm_if_needed(self, request: ProductBatchCodingRequest) -> None:
        cfg = get_config()
        should_preflight = cfg.llm_preflight_enabled if request.llm_preflight is None else request.llm_preflight
        if not cfg.llm_enabled or not should_preflight:
            logger.info("LLM preflight skipped llm_enabled={} llm_preflight={}", cfg.llm_enabled, should_preflight)
            return
        try:
            get_llm_service().health_check()
        except Exception as exc:  # noqa: BLE001 - convert to clear batch-start failure.
            raise RuntimeError(
                "LLM preflight failed before product coding started. "
                "Check PCT/PCA_LLM_ENDPOINT, PCT/PCA_LLM_DEPLOYMENT, API version, API key, "
                "and consumer header. Set PCT_LLM_PREFLIGHT_ENABLED=false or pass "
                "--skip-llm-preflight only for deterministic/offline debugging. "
                f"Original error: {exc}"
            ) from exc


def _failed(row: ProductInputRow, artifact_dir: Path, exc: Exception) -> FailedProductCodingResult:
    return FailedProductCodingResult(
        input_id=row.input_id,
        pg_name=row.pg_name,
        artifact_dir=artifact_dir,
        error=str(exc),
        error_type=type(exc).__name__,
        product_context=row.fields,
    )


def _default_batch_output_dir() -> Path:
    # Delayed import avoids config initialization when only importing models.
    from .config import get_config

    return get_config().output_root / "batch_product_coding"


__all__ = ["ProductBatchCodingAgent"]
