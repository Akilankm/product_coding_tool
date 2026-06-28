"""Reusable LLM service for product coding.

Default transport is direct HTTP to the Azure OpenAI / compatible chat-completions
endpoint. This intentionally avoids importing the OpenAI Python SDK in notebook
runs, because partially upgraded SDK installs can fail with errors such as
`ModuleNotFoundError: openai.pagination` before any request is sent.

Set PCT_LLM_TRANSPORT=openai only when you explicitly want the optional SDK path.
"""

from __future__ import annotations

import base64
import time
from threading import Lock
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from ..config import Config, get_config
from ..log import logger


@dataclass
class LLMConfig:
    api_key: str
    api_version: str
    endpoint: str
    deployment: str
    consumer_id: str = ""
    max_tokens: int = 4096
    temperature: float = 0.0
    connect_timeout: float = 15.0
    read_timeout: float = 120.0
    max_retries: int = 4
    transport: str = "httpx"
    chat_completions_url: str = ""

    @classmethod
    def from_global(cls, cfg: Config | None = None) -> "LLMConfig":
        cfg = cfg or get_config()
        return cls(
            api_key=cfg.llm_api_key,
            api_version=cfg.llm_api_version,
            endpoint=cfg.llm_endpoint,
            deployment=cfg.llm_deployment,
            consumer_id=cfg.llm_consumer_id,
            max_tokens=cfg.llm_max_tokens,
            temperature=cfg.llm_temperature,
            connect_timeout=cfg.llm_connect_timeout,
            read_timeout=cfg.llm_read_timeout,
            max_retries=cfg.llm_max_retries,
            transport=(cfg.llm_transport or "httpx").strip().lower(),
            chat_completions_url=cfg.llm_chat_completions_url,
        )

    @property
    def default_headers(self) -> dict[str, str]:
        return {"X-NIQ-CIS-Consumer": self.consumer_id} if self.consumer_id else {}

    @property
    def chat_url(self) -> str:
        """Return the chat-completions URL for Azure OpenAI or compatible gateways.

        Supported forms:
        - PCT_LLM_CHAT_COMPLETIONS_URL explicitly set: used as-is.
        - PCT/PCA_LLM_ENDPOINT already points to a chat-completions endpoint: used as-is.
        - Standard Azure endpoint root: builds
          /openai/deployments/{deployment}/chat/completions?api-version={api_version}
        """
        if self.chat_completions_url.strip():
            return self.chat_completions_url.strip()

        endpoint = self.endpoint.rstrip("/")
        if not endpoint:
            return ""

        if "{deployment}" in endpoint:
            endpoint = endpoint.format(deployment=self.deployment)

        if "/chat/completions" in endpoint:
            return self._with_api_version(endpoint)

        if "/openai/deployments/" in endpoint:
            return self._with_api_version(endpoint + "/chat/completions")

        url = f"{endpoint}/openai/deployments/{self.deployment}/chat/completions"
        return self._with_api_version(url)

    def _with_api_version(self, url: str) -> str:
        if "api-version=" in url:
            return url
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}{urlencode({'api-version': self.api_version})}"


@dataclass
class LLMResponse:
    content: str
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""
    finish_reason: str = ""
    raw: Any = None


_DEFAULT_SERVICE: "LLMService | None" = None


def get_llm_service(config: LLMConfig | None = None) -> "LLMService":
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None or config is not None:
        _DEFAULT_SERVICE = LLMService(config)
    return _DEFAULT_SERVICE


class LLMService:
    """Thin wrapper around chat completions with text and image support."""

    _cumulative_prompt: int = 0
    _cumulative_completion: int = 0
    _cumulative_calls: int = 0
    _usage_lock: Lock = Lock()

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_global()
        if not self.config.api_key or not self.config.endpoint:
            raise RuntimeError(
                "LLM is enabled, but PCT/PCA_LLM_API_KEY or PCT/PCA_LLM_ENDPOINT is missing. "
                "Set PCT_LLM_ENABLED=false or PCA_LLM_ENABLED=false to skip LLM synthesis."
            )
        if self.config.transport in {"openai", "sdk", "azureopenai"}:
            self._client = self._build_openai_sdk_client()
        else:
            self._client = None

    def _build_openai_sdk_client(self) -> Any:
        try:
            from openai import AzureOpenAI
        except Exception as exc:
            raise RuntimeError(
                "PCT_LLM_TRANSPORT=openai was requested, but the OpenAI SDK is not importable. "
                "Use the default PCT_LLM_TRANSPORT=httpx, or reinstall the SDK cleanly."
            ) from exc

        return AzureOpenAI(
            api_key=self.config.api_key,
            api_version=self.config.api_version,
            azure_endpoint=self.config.endpoint,
            azure_deployment=self.config.deployment,
            default_headers=self.config.default_headers,
            max_retries=self.config.max_retries,
            timeout=httpx.Timeout(
                connect=self.config.connect_timeout,
                read=self.config.read_timeout,
                write=self.config.read_timeout,
                pool=self.config.read_timeout,
            ),
        )

    def predict(
        self,
        text: str,
        *,
        system_prompt: str | None = None,
        image: str | bytes | None = None,
        images: list[str | bytes] | None = None,
        image_detail: str = "auto",
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
        purpose: str = "",
    ) -> LLMResponse:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if images:
            user_content = self._build_multi_image_content(text, images, image_detail=image_detail)
        else:
            user_content = self._build_user_content(text, image, image_detail=image_detail)
        messages.append({"role": "user", "content": user_content})
        return self._call(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
            purpose=purpose,
        )

    def _call(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
        purpose: str = "",
    ) -> LLMResponse:
        if self.config.transport in {"openai", "sdk", "azureopenai"}:
            return self._call_openai_sdk(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format=response_format,
                purpose=purpose,
            )
        return self._call_httpx(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
            purpose=purpose,
        )

    def _base_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None,
        temperature: float | None,
        response_format: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.deployment,
            "messages": messages,
            "max_tokens": max_tokens or self.config.max_tokens,
            "temperature": self.config.temperature if temperature is None else temperature,
        }
        if response_format:
            payload["response_format"] = response_format
        return payload

    def _call_httpx(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None,
        temperature: float | None,
        response_format: dict[str, Any] | None,
        purpose: str,
    ) -> LLMResponse:
        url = self.config.chat_url
        if not url:
            raise RuntimeError("LLM chat-completions URL could not be derived from PCT/PCA_LLM_ENDPOINT.")

        payload = self._base_payload(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
        )
        headers = {
            "Content-Type": "application/json",
            "api-key": self.config.api_key,
            **self.config.default_headers,
        }
        timeout = httpx.Timeout(
            connect=self.config.connect_timeout,
            read=self.config.read_timeout,
            write=self.config.read_timeout,
            pool=self.config.read_timeout,
        )

        last_exc: Exception | None = None
        for attempt in range(1, max(1, self.config.max_retries) + 1):
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(url, headers=headers, json=payload)
                if response.status_code >= 400:
                    logger.error(
                        "LLM [{}] HTTP {} failed body={}",
                        purpose,
                        response.status_code,
                        response.text[:1500],
                    )
                    response.raise_for_status()
                data = response.json()
                return self._response_from_dict(data, purpose=purpose)
            except Exception as exc:  # noqa: BLE001 - we need retry logging around SDK/gateway exceptions.
                last_exc = exc
                if attempt >= max(1, self.config.max_retries):
                    logger.exception("LLM [{}] failed after {} attempt(s)", purpose, attempt)
                    raise
                sleep_s = min(2**attempt, 8)
                logger.warning("LLM [{}] attempt {}/{} failed: {}. Retrying in {}s", purpose, attempt, self.config.max_retries, exc, sleep_s)
                time.sleep(sleep_s)
        assert last_exc is not None
        raise last_exc

    def _call_openai_sdk(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None,
        temperature: float | None,
        response_format: dict[str, Any] | None,
        purpose: str,
    ) -> LLMResponse:
        kwargs = self._base_payload(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
        )
        try:
            completion = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            body = getattr(getattr(exc, "response", None), "text", None)
            if body:
                logger.error("LLM [{}] failed: {} — body={}", purpose, exc, body[:1000])
            else:
                logger.exception("LLM [{}] failed", purpose)
            raise

        choice = completion.choices[0]
        usage: dict[str, int] = {}
        if completion.usage:
            usage = {
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens,
            }
            self._record_usage(usage, purpose)
        return LLMResponse(
            content=choice.message.content or "",
            usage=usage,
            model=completion.model or "",
            finish_reason=choice.finish_reason or "",
            raw=completion,
        )

    def _response_from_dict(self, data: dict[str, Any], *, purpose: str) -> LLMResponse:
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"LLM response for {purpose!r} has no choices: {str(data)[:1000]}")
        choice = choices[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        usage_raw = data.get("usage") or {}
        usage = {
            "prompt_tokens": int(usage_raw.get("prompt_tokens") or 0),
            "completion_tokens": int(usage_raw.get("completion_tokens") or 0),
            "total_tokens": int(usage_raw.get("total_tokens") or 0),
        }
        if any(usage.values()):
            self._record_usage(usage, purpose)
        return LLMResponse(
            content=content,
            usage=usage,
            model=data.get("model") or self.config.deployment,
            finish_reason=choice.get("finish_reason") or "",
            raw=data,
        )

    @classmethod
    def _record_usage(cls, usage: dict[str, int], purpose: str) -> None:
        with cls._usage_lock:
            cls._cumulative_prompt += usage.get("prompt_tokens", 0)
            cls._cumulative_completion += usage.get("completion_tokens", 0)
            cls._cumulative_calls += 1
        logger.info(
            "LLM [{}] prompt={} completion={} total={}",
            purpose,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            usage.get("total_tokens", 0),
        )

    def _build_user_content(
        self,
        text: str,
        image: str | bytes | None,
        *,
        image_detail: str,
    ) -> str | list[dict[str, Any]]:
        if image is None:
            return text
        return [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": self._resolve_image(image), "detail": image_detail}},
        ]

    def _build_multi_image_content(
        self,
        text: str,
        images: list[str | bytes],
        *,
        image_detail: str,
    ) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for img in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": self._resolve_image(img), "detail": image_detail},
            })
        return content

    @staticmethod
    def _resolve_image(image: str | bytes) -> str:
        if isinstance(image, bytes):
            return LLMService._bytes_to_data_url(image)
        if image.startswith(("http://", "https://", "data:")):
            return image
        path = Path(image)
        if path.is_file():
            return LLMService._bytes_to_data_url(path.read_bytes(), path.suffix)
        raise FileNotFoundError(f"Image file not found: {image}")

    @staticmethod
    def _bytes_to_data_url(data: bytes, suffix: str = ".png") -> str:
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }
        mime = mime_map.get(suffix.lower(), "image/png")
        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    @classmethod
    def token_summary(cls) -> str:
        with cls._usage_lock:
            calls = cls._cumulative_calls
            prompt = cls._cumulative_prompt
            completion = cls._cumulative_completion
        total = prompt + completion
        return (
            f"LLM totals: {calls} calls | "
            f"prompt={prompt:,} completion={completion:,} "
            f"total={total:,} tokens"
        )


__all__ = ["LLMConfig", "LLMResponse", "LLMService", "get_llm_service"]
