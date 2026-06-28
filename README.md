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

This repo uses `pyproject.toml` as the single dependency source of truth. There are no `requirements.txt` files.

For the notebook-first AzureML/VS Code workflow, run:

```bash
pdm install --prod
```

That installs runtime + notebook/kernel dependencies from `[project.dependencies]` and then runs the PDM `post_install` hook to register the Jupyter kernel automatically.

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

PDM is the supported path for this project. If you must use pip, install directly from `pyproject.toml` and then register the kernel manually:

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

Test/dev dependencies are intentionally not installed by `pdm install --prod`. For tests, run:

```bash
pdm install -G test
pdm run test
```

or, if pytest is already available:

```bash
python -m pytest -q
```


## v123 notebook LLM fix

The notebook now uses direct `httpx` chat-completions transport by default:

```bash
PCT_LLM_TRANSPORT=httpx
```

This avoids the AzureML/VS Code notebook failure:

```text
ModuleNotFoundError: No module named 'openai.pagination'
```

That error is caused by a broken or mixed OpenAI SDK install in the active kernel. The product coding agent does not need the SDK for normal runs. It posts directly to the Azure OpenAI / compatible chat-completions endpoint derived from `PCT_LLM_ENDPOINT`, `PCT_LLM_DEPLOYMENT`, and `PCT_LLM_API_VERSION`.

If your gateway already gives a full chat endpoint, set:

```bash
PCT_LLM_CHAT_COMPLETIONS_URL=<full chat completions url>
```

Only use the SDK path if you intentionally install the optional extra:

```bash
pdm add openai==1.55.3
# or install .[openai-sdk]
PCT_LLM_TRANSPORT=openai
```


## Clean reinstall after `openai.pagination` error

If you already created the old v122 environment, recreate it once so the notebook does not keep using the broken package state:

```bash
rm -rf .venv
pdm install --prod
```

Then select the kernel named:

```text
Product Coding Tool (PDM)
```

The code path now defaults to direct HTTP and does not import `openai` unless you explicitly set `PCT_LLM_TRANSPORT=openai`.


## Dependency policy

- `pyproject.toml` is the only dependency manifest.
- Runtime, LLM HTTP transport, pandas, and Jupyter kernel dependencies live in `[project.dependencies]`, so `pdm install --prod` is enough for notebook execution.
- Test/lint tooling lives in optional groups and is installed only when requested.
- No `requirements.txt`, `requirements-notebook.txt`, or constraints files are maintained to avoid dependency drift.
