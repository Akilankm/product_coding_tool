# Product Coding Tool

Standalone artifact-grounded product feature coding agent.

## Runtime inputs

The product coding runtime now takes exactly these three inputs:

```text
data/scraped/
  ROW_0001/
  ROW_0002/
  ...

product_batch_input_canonical_pg_names.csv
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


## Canonical PG names

The product batch CSV and the PG feature CSV now use the same canonical `PG_name` values.
The bundled example batch file has already been fixed, so values such as:

```text
ALL OTHER MISC. TOYS      -> All Other Miscellaneous Toys
TOY VEHICLES/PLAYSET     -> Vehicles / Playsets
INFANT/PRESCHOOL TOY     -> Infant / Preschool Toys
FIGURES/BUILD SETS       -> Figures/Build Sets
GAMES/PUZZLES            -> Games/Puzzles
DOLLS/FASHION TOYS       -> Dolls/Fashion Toys
ELECTR/EDUCAT TOYS       -> Electr/Educat Toys
```

are stored canonically in:

```text
examples/product_batch_input_canonical_pg_names.csv
examples/pg_feature_coding_input.csv
```

The code also preserves `PG_name_original` and `PG_name_resolved` in output context for auditability, but the output `PG_name` is canonical.

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
plan evidence -> collect artifact evidence -> code value -> review gate -> retry only when productive
```

The review gate now logs a per-feature `iteration_trace` with the retry decision and reason.
Closed-set values that are outside the supplied allowed list are marked for manual review instead
of repeatedly calling the LLM with the same evidence.

## Install

```bash
pdm install --prod
```

This installs notebook/runtime dependencies and registers the kernel.

## Batch CLI

```bash
product-code \
  --batch-input examples/product_batch_input_canonical_pg_names.csv \
  --scraped-root data/scraped \
  --pg-feature-input examples/pg_feature_coding_input.csv \
  --output-dir data/coded/batch_run \
  --max-parallel-features 4
```

Smoke test:

```bash
product-code \
  --batch-input examples/product_batch_input_canonical_pg_names.csv \
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
  --batch-input examples/product_batch_input_canonical_pg_names.csv \
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
├── batch_artifact_quality_report.json
├── failed_products.csv
├── ROW_0001/
│   ├── coded_features.csv
│   ├── coded_features.json
│   ├── coding_audit.md
│   ├── artifact_quality_report.json
│   └── agent_trace.json
└── ROW_0002/
```

The combined CSV includes product context plus coded feature values. It also includes
`iterations`, `final_retry_reason`, and `artifact_quality_warning_count` so batch output can
be audited without opening every per-product folder.

## Artifact quality handling

The reader is defensive because upstream scrape artifacts can contain files named `.json`
that are not valid JSON. The tool now:

```text
read file once per product artifact
try strict JSON
try safe lenient JSON recovery
fallback to text if malformed
record the issue in artifact_quality_report.json
log the malformed file only once
```

This means malformed JSON no longer floods logs or causes repeated parsing work. The coding
run still completes, while the artifact defect is visible in `artifact_quality_report.json` and
`batch_artifact_quality_report.json`.

## Evidence-token control

Full scrape files are no longer sent wholesale for every feature. Evidence is compacted into
feature-specific snippets before LLM coding. Default caps are now:

```bash
PCT_CODING_MAX_ITERATIONS=2
PCT_CODING_MAX_EVIDENCE_ITEMS=12
PCT_CODING_MAX_EVIDENCE_CHARS=18000
PCT_CODING_EVIDENCE_CONTEXT_CHARS=900
PCT_CODING_READ_FILE_CHARS=6000
```

## Environment

The LLM transport defaults to the same scraper-compatible AzureOpenAI SDK path used by `product_scrape_tool`:

```bash
PCT_LLM_TRANSPORT=openai
```

Feature parallelism:

```bash
PCT_CODING_MAX_PARALLEL_FEATURES=4
```

Evidence/retry defaults are deliberately conservative to reduce repeated large LLM calls:

```bash
PCT_CODING_MAX_ITERATIONS=2
PCT_CODING_MAX_EVIDENCE_ITEMS=12
PCT_CODING_MAX_EVIDENCE_CHARS=18000
```

