# Product bulk coding production hardening

This hardening layer protects the fast product-level bulk path from weak scrape artifacts and bad bulk responses.

## Quality gate

Before any bulk LLM call, the product artifact is classified:

```text
GREEN  -> run product-level bulk coding
AMBER  -> run product-level bulk coding, keep stricter review/fallback audit
RED    -> do not bulk-code
```

RED has two sub-cases:

```text
no usable evidence             -> manual review / re-scrape needed, no LLM waste
some evidence but weak shape   -> full-product per-feature fallback
```

## Bulk failure handling

If the bulk call fails badly, returns too many placeholders, misses many feature IDs, or returns parse-error output, the whole product is routed to the existing per-feature loop.

```text
bulk succeeds, few weak features       -> selective per-feature fallback
bulk fails systemically                -> full-product per-feature fallback
artifact unusable                      -> manual review + re-scrape-needed signal
```

## Audit fields

Every feature receives:

```text
artifact_quality_gate
artifact_quality_decision
rescrape_needed
full_product_fallback / fallback_from_bulk when applicable
artifact_quality_warning_count
```

The product-level `artifact_quality_report` also includes the quality gate payload.
