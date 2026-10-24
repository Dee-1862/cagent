"""Settings from the environment and the local .env file (never committed)."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    """Loads .env without overriding variables already set in the shell."""
    load_dotenv(ROOT / ".env", override=False)


def env(*names: str, default: str | None = None) -> str | None:
    """First non-empty value among names, so older .env spellings keep working."""
    for name in names:
        value = os.environ.get(name) or os.environ.get(name.lower())
        if value:
            return value
    return default


def elastic_settings() -> tuple[str, str] | None:
    url = env("ELASTIC_CLOUD_URL", "ELASTIC_URL")
    key = env("ELASTIC_API_KEY", "ELASTIC_CLOUD_KEY")
    return (url, key) if url and key else None
