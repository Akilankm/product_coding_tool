from __future__ import annotations

import tomllib
from pathlib import Path

from product_coding_tool.agent.json_utils import parse_json_object


def test_pyproject_has_notebook_kernel_and_jedi_guardrails():
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    deps = "\n".join(data["project"]["dependencies"])
    assert "ipykernel==6.29.5" in deps
    assert "jedi==0.19.1" in deps
    assert "parso==0.8.4" in deps
    assert "pandas" in deps
    assert "product-coding-install-kernel" in data["project"]["scripts"]
    assert data["tool"]["pdm"]["scripts"]["post_install"] == "python scripts/install_ipykernel.py"
    assert not any(dep.startswith("openai>=") for dep in data["project"]["dependencies"])


def test_pyproject_is_single_dependency_manifest():
    root = Path(__file__).resolve().parents[1]
    forbidden = [
        "requirements.txt",
        "requirements-notebook.txt",
        "constraints-notebook.txt",
    ]
    assert not any((root / name).exists() for name in forbidden)


def test_parse_json_object_recovers_json_fence():
    assert parse_json_object('```json\n{"coded_value": "Yes"}\n```') == {"coded_value": "Yes"}
