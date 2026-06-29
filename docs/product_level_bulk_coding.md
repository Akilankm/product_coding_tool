# Product-level bulk coding mode

## Goal

Target throughput: **10 products within 2 minutes** while preserving evidence-grounded outputs, deterministic validation, and graceful failure handling.

The speed target is not achievable with the older `1 feature = 1 LLM call` path. The production path is now:

```text
1 product = 1 bulk LLM call for all product features
          + deterministic validation for every feature
          + bounded per-feature fallback only for weak/invalid results
```

## Recommended production settings

```bash
export PCT_CODING_MODE=per_product
export PCT_CODING_MAX_PARALLEL_PRODUCTS=10
export PCT_CODING_GLOBAL_LLM_CONCURRENCY=10
export PCT_CODING_MAX_ITERATIONS=1
export PCT_CODING_BULK_CONTEXT_CHARS=36000
export PCT_CODING_BULK_MAX_FALLBACK_FEATURES=3
export PCT_CODING_BULK_FALLBACK_ENABLED=true
```

Equivalent CLI:

```bash
product-code \
  --batch-input examples/product_batch_input_canonical_pg_names.csv \
  --scraped-root data/scraped \
  --pg-feature-input examples/pg_feature_coding_input.csv \
  --output-dir data/coded/batch_fast \
  --coding-mode per_product \
  --max-parallel-products 10
```

## What happens for each product

```text
scrape artifact folder
  -> ArtifactNavigator inventory
  -> ProductArtifactContextBuilder reads and indexes artifact files once
  -> ProductBulkCoder sends one compact product-level request
  -> RuleValidator validates each feature output
  -> ProductLevelCodingAgent selects weak/invalid features for fallback
  -> ResultWriter writes the same output contract as before
```

## Accuracy controls

The bulk output is not blindly trusted. Every feature result is checked by the same `RuleValidator` used by the slower per-feature path.

Validation catches:

```text
missing coded values
closed-set values outside allowed_values
missing evidence attachment
low confidence
conflicting evidence
unsupported identity status
```

Weak or invalid outputs can be escalated to the existing per-feature evidence loop through:

```bash
PCT_CODING_BULK_FALLBACK_ENABLED=true
PCT_CODING_BULK_MAX_FALLBACK_FEATURES=3
```

This preserves productivity: most products finish in one call, while the highest-risk features get a second focused call.

## Debug mode

For maximum traceability or issue reproduction, force the older path:

```bash
product-code \
  --batch-input examples/product_batch_input_canonical_pg_names.csv \
  --scraped-root data/scraped \
  --pg-feature-input examples/pg_feature_coding_input.csv \
  --coding-mode per_feature \
  --max-parallel-products 2 \
  --max-parallel-features 3
```

## Expected latency profile

With `PCT_CODING_MODE=per_product` and `PCT_CODING_MAX_PARALLEL_PRODUCTS=10`:

```text
10 products require roughly 10 bulk LLM calls, not 120-150 feature calls.
```

If the gateway returns each product-level call in 20-60 seconds, 10 products should complete in roughly 20-90 seconds, plus artifact indexing/output overhead. The two-minute target is realistic as long as the gateway supports 10 concurrent requests and the average bulk call stays under about 90 seconds.

## Safety notes

- Product artifacts are frozen local evidence. The coder does not call web search or scraping.
- Malformed JSON remains an artifact-quality warning, not a full product failure.
- Missing artifacts fail only that product row.
- Outputs remain per-feature in `coded_features.csv`, `coded_features.json`, and combined batch CSV.
- Every feature carries audit metadata, including `coding_mode`, LLM usage, evidence IDs, artifact quality warning count, and fallback information when used.
