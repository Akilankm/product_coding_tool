from __future__ import annotations

import tomllib
from pathlib import Path

from product_coding_tool.config import Config
from product_coding_tool.services.llm import LLMConfig, LLMService, _is_retryable_http_status


def test_default_llm_transport_is_scraper_compatible_openai_sdk():
    cfg = LLMConfig(
        api_key="k",
        api_version="2024-10-21",
        endpoint="https://example.openai.azure.com",
        deployment="dep",
    )
    assert cfg.transport == "openai"


def test_httpx_transport_still_supports_explicit_azure_chat_url():
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


def test_openai_sdk_is_in_production_dependencies():
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    deps = "\n".join(data["project"]["dependencies"])
    assert "openai==1.55.3" in deps


def test_http_status_retry_policy_does_not_retry_404():
    assert _is_retryable_http_status(429)
    assert _is_retryable_http_status(503)
    assert not _is_retryable_http_status(404)
    assert not _is_retryable_http_status(401)


def test_config_defaults_to_openai_transport_and_no_fake_deployment(monkeypatch):
    monkeypatch.delenv("PCT_LLM_TRANSPORT", raising=False)
    monkeypatch.delenv("PCA_LLM_TRANSPORT", raising=False)
    monkeypatch.delenv("PCT_LLM_DEPLOYMENT", raising=False)
    monkeypatch.delenv("PCA_LLM_DEPLOYMENT", raising=False)
    cfg = Config()
    assert cfg.llm_transport == "openai"
    assert cfg.llm_deployment == ""
