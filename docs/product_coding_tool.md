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
requested feature
  -> artifact inventory
  -> LLM evidence planner
  -> local artifact evidence collection
  -> evidence packet
  -> LLM feature coder
  -> deterministic rule validator
  -> review gate
  -> optional follow-up evidence collection
  -> final coded result
```

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
