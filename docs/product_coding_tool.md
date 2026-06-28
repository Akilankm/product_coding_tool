# Product Coding Tool

This package is a standalone artifact-grounded, loop-engineered product coding agent. It consumes an already-created scrape artifact and requested feature rules. It does not discover URLs, call the web, or run scraping.

## Purpose

Input:

```text
scrape artifact folder + requested feature rules
```

Output:

```text
coded_features.json
coded_features.csv
coding_audit.md
agent_trace.json
```

The LLM sits at the center as the planning and coding brain, but it does not directly read the filesystem. Python artifact tools perform deterministic navigation, reading, local artifact evidence lookup, evidence-packet construction, validation, and output writing.

## Expected artifact shape

The agent supports the completed artifact root folder:

```text
data/scraped/scrape_.../
├── request.json
├── scrape_result.json
└── retailer/
    ├── product_evidence.json
    ├── product_evidence.md
    ├── claims.md
    ├── source.md
    ├── vision.md
    ├── metadata.json
    ├── quality_report.json
    ├── noise_report.json
    ├── evidence_recovery_report.json
    ├── tables/*.md
    ├── images/*
    └── manifests/*.json
```

You may also pass the `retailer/` subfolder directly.

## Agent loop

For every requested feature:

```text
FeatureRule
  → ArtifactInventory
  → LLM evidence planner
  → ArtifactRetriever reads and locates evidence in artifact files
  → EvidencePacket
  → LLM feature coder
  → RuleValidator + ReviewGate
  → optional follow-up retrieval loop
  → final FeatureCodingResult
```

## Source priority

The retriever intentionally favors direct retailer evidence:

1. `retailer/source.md`
2. `retailer/tables/*.md`
3. `retailer/metadata.json`
4. `retailer/product_evidence.json` / `.md`
5. `retailer/claims.md`
6. `retailer/vision.md`
7. image manifest/images
8. quality/noise/recovery reports

## LLM reuse

The package includes a standalone `product_coding_tool.services.llm` module based on the same enterprise LLM contract you already use. It supports `PCT_LLM_*` variables and also falls back to existing `PCA_LLM_*` variables, so the same notebook/AzureML LLM configuration can be reused without bringing any scraper code into this package.

## Quick run

```bash
python scripts/run_product_coding.py \
  --artifact-dir data/scraped/scrape_20260628_190357_25c16d76 \
  --features-json examples/features.json \
  --output-dir data/coded/demo
```

## Inline feature test

```bash
python scripts/run_product_coding.py \
  --artifact-dir data/scraped/scrape_20260628_190357_25c16d76 \
  --feature BRAND \
  --feature "Battery Required"
```

## Feature JSON contract

```json
{
  "features": [
    {
      "feature_id": "BATTERY_REQUIRED",
      "feature_name": "Battery Required",
      "feature_type": "closed_set",
      "definition": "Whether the toy requires batteries to operate.",
      "allowed_values": ["Yes", "No", "Not stated"],
      "aliases": ["battery", "batteries required"],
      "evidence_hints": ["battery", "AA", "AAA", "requires"]
    }
  ]
}
```

## Manual-review gate

Manual review is forced when:

- no evidence is found;
- no evidence is attached to the final value;
- closed-set value is outside `allowed_values`;
- confidence is below `PCT/PCA_CODING_MIN_CONFIDENCE`;
- conflicts are detected;
- the LLM call fails and deterministic fallback is used.

## Notebook

Use:

```text
notebooks/run_product_coding_agent.ipynb
```


## Explicit non-goals

This package does not include URL finding, web search, SerpAPI calls, Crawl4AI execution, page scraping, browser automation, or retailer-domain resolution. Those are upstream responsibilities.
