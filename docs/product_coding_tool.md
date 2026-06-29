# Product Coding Tool Design

## Inputs

1. `product_batch_input_canonical_pg_names.csv`
   - Required columns: `input_id`, `PG_name`
   - Other columns are product context.
2. `data/scraped/`
   - Contains one scrape artifact folder per `input_id`.
3. `pg_feature_coding_input.csv`
   - Columns: `PG_name`, `features`, `type`, `allowed_values`, `description`.

## Flow

```text
product batch row
  -> input_id locates scrape artifact folder
  -> PG_name selects feature rules
  -> ProductCodingAgent codes all selected features
  -> per-product output + combined batch output
```

## Parallelism

Product rows are processed sequentially by default to avoid uncontrolled LLM fan-out.
For each product, feature coding runs through a dynamic worker pool.

Each feature has an internal loop:

```text
plan evidence -> retrieve compact evidence -> code JSON -> review gate -> optional retry
```

The review gate now records an `iteration_trace` and retries only when more evidence is likely to improve the result.
Closed-set values outside the allowed list are marked for manual review instead of repeatedly calling the LLM.

## Artifact quality handling

The reader now caches every file per product artifact. JSON files are parsed once, with this order:

```text
strict JSON
safe lenient recovery
text fallback
```

Malformed `.json` files do not crash coding. They are logged once and reported in:

```text
ROW_XXXX/artifact_quality_report.json
batch_artifact_quality_report.json
```

The combined CSV also carries `artifact_quality_warning_count` for quick filtering.

## Evidence-token controls

Evidence packets are compacted into feature-specific snippets before LLM coding. The default caps are:

```text
PCT_CODING_MAX_ITERATIONS=2
PCT_CODING_MAX_EVIDENCE_ITEMS=12
PCT_CODING_MAX_EVIDENCE_CHARS=18000
PCT_CODING_EVIDENCE_CONTEXT_CHARS=900
PCT_CODING_READ_FILE_CHARS=6000
```

These defaults reduce repeated 25k-30k token coding calls while keeping direct source/table/metadata evidence available.

## Failure isolation

- Missing artifact folder -> product-level failure in `failed_products.csv`.
- One feature crash -> feature-level manual-review result; other features continue.
- One product failure -> remaining product rows continue.
- Malformed artifact JSON -> text fallback + artifact-quality warning, not product failure.
