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


def kibana_url() -> str | None:
    """Kibana hosts Agent Builder and Workflows (task B5). On Elastic Cloud its
    address is the Elasticsearch one with ".es." replaced by ".kb."."""
    explicit = env("KIBANA_URL")
    if explicit:
        return explicit.rstrip("/")
    settings = elastic_settings()
    if settings and ".es." in settings[0]:
        return settings[0].replace(".es.", ".kb.", 1).rstrip("/")
    return None
