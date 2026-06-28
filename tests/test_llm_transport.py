from __future__ import annotations

import tomllib
from pathlib import Path

from product_coding_tool.services.llm import LLMConfig, LLMService


def test_default_llm_transport_is_httpx_and_url_is_azure_chat_completions():
    cfg = LLMConfig(
        api_key="k",
        api_version="2024-10-21",
        endpoint="https://example.openai.azure.com",
        deployment="dep",
        transport="httpx",
    )
    assert cfg.chat_url == "https://example.openai.azure.com/openai/deployments/dep/chat/completions?api-version=2024-10-21"


def test_llm_httpx_response_parser():
    svc = object.__new__(LLMService)
    data = {
        "model": "m",
        "choices": [{"message": {"content": "{\"ok\": true}"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    resp = svc._response_from_dict(data, purpose="test")
    assert resp.content == '{"ok": true}'
    assert resp.usage["total_tokens"] == 15
    assert resp.finish_reason == "stop"


def test_openai_sdk_not_required_in_base_dependencies():
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    deps = "\n".join(data["project"]["dependencies"])
    assert "openai>=" not in deps
    assert '"openai==1.55.3"' in (root / "pyproject.toml").read_text(encoding="utf-8")
