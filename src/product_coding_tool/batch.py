"""Batch product coding orchestration.

This module wires the three runtime inputs together:

1. Product batch CSV with `input_id` and `PG_name`
2. Scrape artifact root where each `input_id` is a folder name
3. PG feature CSV with `PG_name,features,type,allowed_values,description`
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .agent.orchestrator import ProductCodingAgent
from .artifacts.navigator import ArtifactNavigator
from .config import get_config
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
from .services.llm import get_llm_service


@dataclass(frozen=True)
class ProductPreflightRecord:
    row: ProductInputRow
    artifact_dir: Path
    resolved_pg_name: str
    feature_count: int
    missing_expected_files: list[str]
    artifact_file_count: int


class ProductBatchCodingAgent:
    """Run the product coding agent across many scrape artifact folders.

    Product-level execution is bounded by `max_parallel_products`. Feature-level
    execution inside each product remains bounded by `max_parallel_features`.
    The LLM service also has a global semaphore, so total gateway fan-out stays
    controlled even when product and feature parallelism are both enabled.
    """

    def __init__(self, product_agent: ProductCodingAgent | None = None) -> None:
        self.product_agent = product_agent or ProductCodingAgent()
        self.cfg = get_config()

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

        output_root = request.output_dir or _default_batch_output_dir()
        output_root.mkdir(parents=True, exist_ok=True)

        preflight_records, preflight_failures = self._preflight_products(request, pg_provider, rows)
        max_parallel_products = self._resolve_max_parallel_products(request, len(preflight_records))
        logger.info(
            "Batch execution plan products={} preflight_failures={} max_parallel_products={} max_parallel_features={} global_llm_concurrency={}",
            len(preflight_records),
            len(preflight_failures),
            max_parallel_products,
            request.max_parallel_features or self.cfg.coding_max_parallel_features,
            self.cfg.coding_global_llm_concurrency,
        )

        if max_parallel_products <= 1 or len(preflight_records) <= 1:
            products = []
            failed = list(preflight_failures)
            for record in preflight_records:
                product_result, failure = self._code_one_product(record, request=request, output_root=output_root)
                if product_result is not None:
                    products.append(product_result)
                if failure is not None:
                    failed.append(failure)
        else:
            products, runtime_failures = self._run_products_parallel(
                preflight_records,
                request=request,
                output_root=output_root,
                max_parallel_products=max_parallel_products,
            )
            failed = [*preflight_failures, *runtime_failures]

        products.sort(key=lambda p: str((p.product_context or {}).get("input_id") or p.product_id))
        artifact_quality_reports = [p.artifact_quality_report for p in products if p.artifact_quality_report]
        result = ProductBatchCodingResult(
            products=products,
            failed_products=failed,
            output_dir=output_root,
            artifact_quality_reports=artifact_quality_reports,
        )
        ProductBatchResultWriter().write(result, output_dir=output_root)
        logger.info(
            "ProductBatchCodingAgent complete products={} failed={} output_dir={}",
            len(products),
            len(failed),
            output_root,
        )
        return result

    def _preflight_products(
        self,
        request: ProductBatchCodingRequest,
        pg_provider: PGFeatureInputProvider,
        rows: list[ProductInputRow],
    ) -> tuple[list[ProductPreflightRecord], list[FailedProductCodingResult]]:
        records: list[ProductPreflightRecord] = []
        failed: list[FailedProductCodingResult] = []
        for row in rows:
            artifact_dir = request.scraped_root / row.input_id
            try:
                resolved_pg_name = pg_provider.resolve_pg_name(row.pg_name)
                features = pg_provider.features_for_pg(pg_name=resolved_pg_name, limit=request.limit_features)
                if not artifact_dir.exists():
                    raise FileNotFoundError(f"Scrape artifact folder not found for input_id={row.input_id}: {artifact_dir}")
                missing_expected: list[str] = []
                artifact_file_count = 0
                if self.cfg.coding_preflight_artifacts_enabled:
                    inventory = ArtifactNavigator(artifact_dir).inventory()
                    missing_expected = list(inventory.missing_expected_files)
                    artifact_file_count = len(inventory.files)
                    if missing_expected:
                        logger.warning(
                            "Product artifact preflight warnings input_id={} missing_expected_files={}",
                            row.input_id,
                            missing_expected,
                        )
                records.append(
                    ProductPreflightRecord(
                        row=row,
                        artifact_dir=artifact_dir,
                        resolved_pg_name=resolved_pg_name,
                        feature_count=len(features),
                        missing_expected_files=missing_expected,
                        artifact_file_count=artifact_file_count,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - keep batch preflight isolated.
                logger.exception("Product preflight failed input_id={} pg_name={}", row.input_id, row.pg_name)
                failed.append(_failed(row, artifact_dir, exc))
        logger.info("Product preflight complete runnable={} failed={}", len(records), len(failed))
        return records, failed

    def _run_products_parallel(
        self,
        records: list[ProductPreflightRecord],
        *,
        request: ProductBatchCodingRequest,
        output_root: Path,
        max_parallel_products: int,
    ) -> tuple[list[BatchCodingResult], list[FailedProductCodingResult]]:
        products: list[BatchCodingResult] = []
        failed: list[FailedProductCodingResult] = []
        with ThreadPoolExecutor(max_workers=max_parallel_products, thread_name_prefix="product_worker") as executor:
            future_to_record = {
                executor.submit(self._code_one_product, record, request=request, output_root=output_root): record
                for record in records
            }
            for future in as_completed(future_to_record):
                record = future_to_record[future]
                try:
                    product_result, failure = future.result()
                except Exception as exc:  # noqa: BLE001 - product-level isolation.
                    logger.exception("Product worker crashed input_id={} pg_name={}", record.row.input_id, record.row.pg_name)
                    product_result, failure = None, _failed(record.row, record.artifact_dir, exc)
                if product_result is not None:
                    products.append(product_result)
                if failure is not None:
                    failed.append(failure)
        return products, failed

    def _code_one_product(
        self,
        record: ProductPreflightRecord,
        *,
        request: ProductBatchCodingRequest,
        output_root: Path,
    ) -> tuple[BatchCodingResult | None, FailedProductCodingResult | None]:
        row = record.row
        try:
            pg_provider = PGFeatureInputProvider.from_file(request.pg_feature_input_csv)
            features = pg_provider.features_for_pg(pg_name=record.resolved_pg_name, limit=request.limit_features)
            logger.info(
                "Coding product input_id={} pg_name={} resolved_pg_name={} artifact={} features={} artifact_files={} missing_expected={}",
                row.input_id,
                row.pg_name,
                record.resolved_pg_name,
                record.artifact_dir,
                len(features),
                record.artifact_file_count,
                len(record.missing_expected_files),
            )
            product_context = dict(row.fields)
            product_context["PG_name_original"] = row.pg_name
            product_context["PG_name_resolved"] = record.resolved_pg_name
            product_context["PG_name"] = record.resolved_pg_name
            product_context["artifact_missing_expected_files"] = "; ".join(record.missing_expected_files)
            product_context["artifact_file_count"] = record.artifact_file_count
            agent = self.product_agent if self._resolve_max_parallel_products(request, 1) <= 1 else ProductCodingAgent()
            product_result = agent.run(
                CodingRequest(
                    artifact_dir=record.artifact_dir,
                    features=features,
                    output_dir=output_root / row.input_id,
                    product_id=row.input_id,
                    product_context=product_context,
                    max_iterations=request.max_iterations,
                    max_parallel_features=request.max_parallel_features,
                )
            )
            return product_result, None
        except Exception as exc:  # product-level isolation
            logger.exception("Product-level coding failed input_id={} pg_name={}", row.input_id, row.pg_name)
            return None, _failed(row, record.artifact_dir, exc)

    def _resolve_max_parallel_products(self, request: ProductBatchCodingRequest, row_count: int) -> int:
        requested = request.max_parallel_products
        if requested is None:
            requested = self.cfg.coding_max_parallel_products
        return max(1, min(int(requested), max(1, row_count)))

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
