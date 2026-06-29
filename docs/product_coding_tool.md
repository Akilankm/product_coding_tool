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

## Failure isolation

- Missing artifact folder -> product-level failure in `failed_products.csv`.
- One feature crash -> feature-level manual-review result; other features continue.
- One product failure -> remaining product rows continue.

