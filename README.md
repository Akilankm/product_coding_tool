# Product Coding Tool

Standalone artifact-grounded product feature coding agent.

## Runtime inputs

The product coding runtime now takes exactly these three inputs:

```text
data/scraped/
  ROW_0001/
  ROW_0002/
  ...

product_batch_input_with_pg_name.csv
pg_feature_coding_input.csv
```

### 1. Product batch input CSV

Must contain at least:

```csv
input_id,PG_name
```

All other columns are preserved as product context and copied into output/audit.

`input_id` must match the scrape artifact folder name:

```text
input_id=ROW_0001  ->  data/scraped/ROW_0001
```

Typical columns:

```text
input_id, product_url, main_text, PG_name, ean, retailer_name, country_code, ...
```

### 2. Scrape artifact root

Folder containing one artifact folder per `input_id`:

```text
data/scraped/
├── ROW_0001/
│   ├── retailer/
│   │   ├── product_evidence.json
│   │   ├── claims.md
│   │   ├── source.md
│   │   ├── vision.md
│   │   └── ...
│   ├── request.json
│   └── scrape_result.json
└── ROW_0002/
```

### 3. PG feature coding input CSV

Exactly 5 columns:

```csv
PG_name,features,type,allowed_values,description
```

- `type` must be `open_set` or `closed_set`
- `allowed_values` is semicolon-separated and required for `closed_set`
- `allowed_values` is blank for `open_set`

## Execution model

For each row in the product batch CSV:

```text
input_id -> locate scrape artifact folder
PG_name  -> select features from pg_feature_coding_input.csv
feature list -> run ProductCodingAgent
```

Inside each product, feature coding is parallelized:

```text
4 workers + 8 features
  worker_1 -> feature_1 -> next available feature
  worker_2 -> feature_2 -> next available feature
  worker_3 -> feature_3 -> next available feature
  worker_4 -> feature_4 -> next available feature
```

Each feature worker performs its own sequential agent loop:

```text
plan evidence -> collect artifact evidence -> code value -> review gate -> retry if needed
```

## Install

```bash
pdm install --prod
```

This installs notebook/runtime dependencies and registers the kernel.

## Batch CLI

```bash
product-code \
  --batch-input examples/product_batch_input_with_pg_name.csv \
  --scraped-root data/scraped \
  --pg-feature-input examples/pg_feature_coding_input.csv \
  --output-dir data/coded/batch_run \
  --max-parallel-features 4
```

Smoke test:

```bash
product-code \
  --batch-input examples/product_batch_input_with_pg_name.csv \
  --scraped-root data/scraped \
  --pg-feature-input examples/pg_feature_coding_input.csv \
  --output-dir data/coded/smoke \
  --limit-products 2 \
  --limit-features 3 \
  --max-parallel-features 4
```

Run specific rows:

```bash
product-code \
  --batch-input examples/product_batch_input_with_pg_name.csv \
  --scraped-root data/scraped \
  --pg-feature-input examples/pg_feature_coding_input.csv \
  --input-id ROW_0001 \
  --input-id ROW_0002
```

## Single-artifact debug mode

```bash
product-code \
  --artifact-dir data/scraped/ROW_0001 \
  --pg-name "TOY VEHICLES/PLAYSET" \
  --pg-feature-input examples/pg_feature_coding_input.csv \
  --output-dir data/coded/ROW_0001_debug \
  --max-parallel-features 4
```

## Outputs

Batch output root:

```text
data/coded/batch_run/
├── combined_coded_features.csv
├── batch_coding_result.json
├── failed_products.csv
├── ROW_0001/
│   ├── coded_features.csv
│   ├── coded_features.json
│   ├── coding_audit.md
│   └── agent_trace.json
└── ROW_0002/
```

The combined CSV includes product context plus coded feature values.

## Environment

The LLM transport defaults to direct HTTP to avoid OpenAI SDK import conflicts:

```bash
PCT_LLM_TRANSPORT=httpx
```

Feature parallelism:

```bash
PCT_CODING_MAX_PARALLEL_FEATURES=4
```

