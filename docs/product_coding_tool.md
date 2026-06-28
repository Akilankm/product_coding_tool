# Product Coding Tool Architecture

## Boundary

This component starts **after scraping is complete**.

It accepts:

```text
1. scrape artifact folder
2. features/rules to code
```

It does not perform:

```text
- web search
- URL discovery
- retailer resolution
- crawling
- scraping
```

## Agentic loop

```text
requested feature list
  -> artifact inventory once
  -> feature-level parallel workers
  -> per feature: LLM evidence planner -> local artifact evidence collection -> evidence packet -> LLM feature coder -> deterministic rule validator -> review gate -> optional follow-up evidence collection
  -> ordered final coded result list
```

Parallelism is only across features. The evidence loop for one feature stays sequential so its audit trail remains readable and deterministic.

Recommended control:

```bash
PCT_CODING_MAX_PARALLEL_FEATURES=4
```

Use `--max-parallel-features 1` when debugging one feature trace at a time.

## Artifact communication tools

| Module | Purpose |
|---|---|
| `ArtifactNavigator` | Normalizes root/retailer folder and lists artifact files. |
| `ArtifactReader` | Reads JSON, markdown, tables, quality files and product context. |
| `ArtifactEvidenceLocator` | Searches local artifact text only. No internet. |
| `EvidencePacketBuilder` | Builds compact feature-specific evidence packets. |
| `ImageLoader` | Loads product images only when visual evidence is required. |

## LLM usage

The LLM is used only as the reasoning brain:

1. plan evidence collection
2. code feature value from collected evidence
3. optionally inspect images for visual features

All file access is deterministic Python tooling.

## Notebook stability

`pyproject.toml` includes `ipykernel` and stable notebook kernel dependencies. The project kernel registration disables Jedi completion through project-local IPython config:

```python
c.Completer.use_jedi = False
```

The notebook also runs:

```python
%config Completer.use_jedi = False
```

This keeps autocomplete from blocking the kernel in heavy AzureML/VS Code environments.


## Dependency installation policy

Use `pdm install --prod` for the notebook/runtime environment. The production dependency set includes `ipykernel`, IPython/Jupyter kernel runtime packages, pandas, HTTP LLM transport, logging, config, and validation dependencies. PDM then runs the `post_install` hook to register the `Product Coding Tool (PDM)` kernel.

The repo intentionally does not contain `requirements.txt` or notebook-specific requirements files. `pyproject.toml` is the single source of truth.


## Feature worker pool semantics

The parallel engine uses a dynamic worker pool, not a fixed static assignment.
With `--max-parallel-features 4` and 8 requested features:

```text
queue: F1 F2 F3 F4 F5 F6 F7 F8

worker_1 -> F1 -> next available feature
worker_2 -> F2 -> next available feature
worker_3 -> F3 -> next available feature
worker_4 -> F4 -> next available feature
```

Each worker completes the full loop for one feature before taking another feature:

```text
plan evidence -> collect artifact evidence -> code value -> review gate -> retry if needed -> final result
```

So retries happen inside the assigned feature worker. Other workers continue processing their own features. Final JSON/CSV output is sorted back to the original feature input order.
