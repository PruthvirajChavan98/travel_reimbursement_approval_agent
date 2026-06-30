"""Configuration: environment settings + policy loading.

Environment is loaded from a local ``.env`` (gitignored). All policy *numbers*
live in ``config/policy.yaml`` — the single source of truth — and are loaded
lazily so importing this module never requires the policy file to exist.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()  # no-op if .env is absent

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
CLAIMS_DIR = DATA_DIR / "claims"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
POLICY_YAML = CONFIG_DIR / "policy.yaml"
POLICY_MD = DATA_DIR / "policy.md"
PRIOR_CLAIMS = DATA_DIR / "prior_claims.json"


@dataclass(frozen=True)
class Settings:
    """Connection + integration settings, all env-driven."""

    base_url: str | None
    api_key: str | None
    deployment: str
    reasoning_effort: str
    database_url: str | None
    langfuse_public_key: str | None
    langfuse_secret_key: str | None
    langfuse_host: str | None
    cors_origins: tuple[str, ...]
    vlm_model: str
    vlm_base_url: str | None
    vlm_api_key: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:8080")
        return cls(
            base_url=os.getenv("AZURE_OPENAI_BASE_URL") or None,
            api_key=os.getenv("AZURE_OPENAI_API_KEY") or None,
            deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-oss-120b"),
            reasoning_effort=os.getenv("AZURE_OPENAI_REASONING_EFFORT", "high"),
            database_url=os.getenv("DATABASE_URL") or None,
            langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY") or None,
            langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY") or None,
            langfuse_host=os.getenv("LANGFUSE_HOST") or None,
            cors_origins=tuple(o.strip() for o in raw_origins.split(",") if o.strip()),
            # VLM (receipt image extraction): default to the same /openai/v1 host + key as
            # gpt-oss (no Entra); only the model differs. Kimi-K2.6 is the vision model.
            vlm_model=os.getenv("VLM_MODEL", "Kimi-K2.6"),
            vlm_base_url=os.getenv("VLM_BASE_URL") or None,
            vlm_api_key=os.getenv("VLM_API_KEY") or None,
        )

    @property
    def live_ready(self) -> bool:
        """True only when credentials exist to call the real endpoint.

        When False the system runs the deterministic pipeline (mock mode), so a
        cold clone with no secrets still works.
        """
        return bool(self.base_url and self.api_key)

    @property
    def langfuse_ready(self) -> bool:
        """True when both Langfuse keys are present (else tracing no-ops)."""
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


def get_settings() -> Settings:
    return Settings.from_env()


@lru_cache(maxsize=8)
def load_policy(path: str | os.PathLike[str] | None = None) -> dict:
    """Load the authoritative policy config (cached)."""
    target = Path(path) if path is not None else POLICY_YAML
    with open(target, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
