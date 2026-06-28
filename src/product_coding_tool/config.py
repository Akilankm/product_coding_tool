"""Runtime configuration for the product coding agent.

The coding agent reuses the existing scraping-agent LLM contract. New `PCT_*`
variables are supported, but every LLM setting falls back to the already used
`PCA_*` names so existing notebooks/AzureML secret injection continue to work.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv_files() -> None:
    """Load local .env files when python-dotenv is installed.

    AzureML/runtime environment variables still win because python-dotenv does not
    override existing variables by default.
    """
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(_ROOT / ".env", override=False)
    load_dotenv(override=False)


_load_dotenv_files()


def _env(name: str, default: str) -> str:
    pct = os.getenv("PCT_" + name)
    if pct is not None and pct.strip():
        return pct
    return os.getenv("PCA_" + name, default)


def _env_int(name: str, default: int) -> int:
    raw = _env(name, "")
    return int(raw) if raw.strip() else default


def _env_float(name: str, default: float) -> float:
    raw = _env(name, "")
    return float(raw) if raw.strip() else default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name, "")
    if not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Config:
    """Central settings for loop-engineered feature coding."""

    output_root: Path = field(default_factory=lambda: Path(_env("CODING_OUTPUT_ROOT", str(_ROOT / "data" / "coded"))))

    # Agent loop controls.
    coding_max_iterations: int = field(default_factory=lambda: _env_int("CODING_MAX_ITERATIONS", 3))
    coding_max_evidence_items: int = field(default_factory=lambda: _env_int("CODING_MAX_EVIDENCE_ITEMS", 24))
    coding_max_evidence_chars: int = field(default_factory=lambda: _env_int("CODING_MAX_EVIDENCE_CHARS", 45_000))
    coding_evidence_context_chars: int = field(default_factory=lambda: _env_int("CODING_EVIDENCE_CONTEXT_CHARS", 1_600))
    coding_read_file_chars: int = field(default_factory=lambda: _env_int("CODING_READ_FILE_CHARS", 12_000))
    coding_min_confidence: float = field(default_factory=lambda: _env_float("CODING_MIN_CONFIDENCE", 0.72))

    # LLM switches.
    llm_enabled: bool = field(default_factory=lambda: _env_bool("LLM_ENABLED", True))
    llm_vision_enabled: bool = field(default_factory=lambda: _env_bool("LLM_VISION_ENABLED", True))
    llm_vision_max_images: int = field(default_factory=lambda: _env_int("LLM_VISION_MAX_IMAGES", 8))
    llm_vision_detail: str = field(default_factory=lambda: _env("LLM_VISION_DETAIL", "low"))

    # Azure OpenAI / compatible gateway. Fallback to PCA_* is intentional.
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", ""))
    llm_api_version: str = field(default_factory=lambda: _env("LLM_API_VERSION", "2024-10-21"))
    llm_endpoint: str = field(default_factory=lambda: _env("LLM_ENDPOINT", ""))
    llm_deployment: str = field(default_factory=lambda: _env("LLM_DEPLOYMENT", "gpt-4o"))
    llm_consumer_id: str = field(default_factory=lambda: _env("LLM_CONSUMER_ID", ""))
    llm_max_tokens: int = field(default_factory=lambda: _env_int("LLM_MAX_TOKENS", 4096))
    llm_temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.0))
    llm_connect_timeout: float = field(default_factory=lambda: _env_float("LLM_CONNECT_TIMEOUT", 15.0))
    llm_read_timeout: float = field(default_factory=lambda: _env_float("LLM_READ_TIMEOUT", 120.0))
    llm_max_retries: int = field(default_factory=lambda: _env_int("LLM_MAX_RETRIES", 4))


def get_config() -> Config:
    return Config()
