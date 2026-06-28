"""Feature-level worker pool for product coding.

The scrape artifact is immutable/read-only during coding, so individual
features can be coded concurrently. Each feature still owns a complete
sequential evidence loop: plan -> retrieve -> code -> review -> optional retry.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

from ..log import logger
from ..models import FeatureCodingResult, FeatureRule

FeatureWorkFn = Callable[[FeatureRule], FeatureCodingResult]


@dataclass(frozen=True)
class WorkerPoolConfig:
    """Runtime controls for feature-level parallel execution."""

    max_workers: int
    thread_name_prefix: str = "pct-feature-worker"

    def normalized(self, feature_count: int) -> "WorkerPoolConfig":
        return WorkerPoolConfig(
            max_workers=max(1, min(int(self.max_workers), max(1, feature_count))),
            thread_name_prefix=self.thread_name_prefix,
        )


class FeatureWorkerPool:
    """Dynamic task queue for independent feature coding tasks.

    Example: with 4 workers and 8 features, the first 4 features start
    immediately. Whenever any worker completes its full feature loop including
    retries, that worker pulls the next waiting feature. Results are returned in
    the same order as the input feature list.
    """

    def __init__(self, config: WorkerPoolConfig) -> None:
        self.config = config

    def run(
        self,
        features: list[FeatureRule],
        work_fn: FeatureWorkFn,
        crash_fn: Callable[[FeatureRule, Exception], FeatureCodingResult],
    ) -> list[FeatureCodingResult]:
        cfg = self.config.normalized(len(features))
        logger.info(
            "FeatureWorkerPool start features={} max_workers={} thread_prefix={}",
            len(features),
            cfg.max_workers,
            cfg.thread_name_prefix,
        )

        ordered: list[FeatureCodingResult | None] = [None] * len(features)
        with ThreadPoolExecutor(max_workers=cfg.max_workers, thread_name_prefix=cfg.thread_name_prefix) as pool:
            future_to_index: dict[Future[FeatureCodingResult], int] = {
                pool.submit(work_fn, feature): idx for idx, feature in enumerate(features)
            }
            for future in as_completed(future_to_index):
                idx = future_to_index[future]
                feature = features[idx]
                try:
                    ordered[idx] = future.result()
                except Exception as exc:  # noqa: BLE001 - isolate one feature crash from the batch.
                    logger.exception("Feature worker crashed feature={} ({})", feature.feature_name, feature.feature_id)
                    ordered[idx] = crash_fn(feature, exc)

        results = [result for result in ordered if result is not None]
        logger.info("FeatureWorkerPool complete results={}", len(results))
        return results


__all__ = ["FeatureWorkerPool", "FeatureWorkerPoolConfig"]
