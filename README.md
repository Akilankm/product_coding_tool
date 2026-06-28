# Product Coding Tool

Standalone artifact-grounded product feature coding agent.

This package has one responsibility:

```text
existing scrape artifact folder + features to code -> coded feature values with evidence, confidence, and audit
```

It intentionally contains **no URL discovery**, **no web search**, **no SerpAPI**, **no Crawl4AI**, and **no scraping pipeline**. The scrape artifact is treated as a completed upstream input.

## Runtime loop

```text
FeatureRule
  -> artifact inventory
  -> LLM evidence plan
  -> local artifact evidence reader/locator
  -> evidence packet
  -> LLM feature coder
  -> rule validator + review gate
  -> optional follow-up evidence loop
  -> final coded output
```

## Inputs

- `artifact_dir`: path to one completed product scrape artifact root, for example `data/scraped/scrape_.../`
- `features`: JSON/CSV feature rules to code

Expected artifact shape:

```text
scrape_.../
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

## Outputs

- `coded_features.json`
- `coded_features.csv`
- `coding_audit.md`
- `agent_trace.json`

## PDM setup

```bash
pdm install
pdm run install-kernel
```

Use the installed kernel in VS Code / AzureML notebooks:

```text
Product Coding Tool (PDM)
```

The kernel installer writes:

```text
.ipython/profile_default/ipython_config.py
```

with:

```python
c.Completer.use_jedi = False
```

This avoids the slow/hanging Jedi autocomplete path in heavy AzureML/Jupyter environments.

## Non-PDM setup

```bash
python -m pip install -e .
python scripts/install_ipykernel.py
```

## Run from CLI

```bash
python scripts/run_product_coding.py \
  --artifact-dir data/scraped/scrape_20260628_190357_25c16d76 \
  --features-json examples/features.json \
  --output-dir data/coded/demo
```

Or, after install:

```bash
product-code \
  --artifact-dir data/scraped/scrape_20260628_190357_25c16d76 \
  --features-json examples/features.json \
  --output-dir data/coded/demo
```

## LLM config

The package includes a standalone LLM wrapper in `product_coding_tool.services.llm`. Use `PCT_LLM_*` variables. It also accepts existing `PCA_LLM_*` variables as fallback so existing secret injection keeps working.

Set `PCT_LLM_ENABLED=false` for dry contract tests; the deterministic fallback will not invent values.

```env
PCT_LLM_ENABLED=true
PCT_LLM_API_KEY=
PCT_LLM_API_VERSION=2024-10-21
PCT_LLM_ENDPOINT=
PCT_LLM_DEPLOYMENT=gpt-4o
PCT_LLM_CONSUMER_ID=
```

## Test

```bash
pdm run test
```

or:

```bash
python -m pytest -q
```
