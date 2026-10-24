"""Settings from the environment and the local .env file (never committed).

Every connection and vendor setting is read here, with a default, so nothing
else in the code needs a hardcoded URL, model, version, index or token. The
.env file is loaded when this module is imported; variables already set in the
shell win over .env.
"""

import os
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_GATEWAY_URL = "ws://127.0.0.1:8765"
DEFAULT_CARTESIA_VERSION = "2026-08-14"
DEFAULT_CARTESIA_STT_MODEL = "ink-2"
DEFAULT_CARTESIA_TTS_MODEL = "sonic-3.6"
DEFAULT_EVENTS_INDEX = "unstep-events"
DEFAULT_PENDING_TTL_S = 60.0


def load_env() -> None:
    """Loads .env without overriding variables already set in the shell."""
    load_dotenv(ROOT / ".env", override=False)


load_env()


def env(*names: str, default: str | None = None) -> str | None:
    """First non-empty value among names, so older .env spellings keep working."""
    for name in names:
        value = os.environ.get(name) or os.environ.get(name.lower())
        if value:
            return value
    return default


# Gateway


def gateway_url() -> str:
    return env("UNSTEP_GATEWAY_URL", default=DEFAULT_GATEWAY_URL).rstrip("/")


def gateway_token() -> str | None:
    """Optional shared secret (FR-13). When set, every client must send it."""
    return env("UNSTEP_GATEWAY_TOKEN")


def ws_url(role: str, base: str | None = None) -> str:
    """The WebSocket address for a role, with the token when one is set."""
    url = f"{(base or gateway_url()).rstrip('/')}/ws/{role}"
    token = gateway_token()
    return f"{url}?token={quote(token, safe='')}" if token else url


def pending_ttl_s() -> float:
    return float(env("UNSTEP_PENDING_TTL_S", default=str(DEFAULT_PENDING_TTL_S)))


# Cartesia


def cartesia_version() -> str:
    return env("CARTESIA_VERSION", default=DEFAULT_CARTESIA_VERSION)


def cartesia_stt_model() -> str:
    return env("CARTESIA_STT_MODEL", default=DEFAULT_CARTESIA_STT_MODEL)


def cartesia_tts_model() -> str:
    return env("CARTESIA_TTS_MODEL", default=DEFAULT_CARTESIA_TTS_MODEL)


# Elastic


def elastic_settings() -> tuple[str, str] | None:
    url = env("ELASTIC_CLOUD_URL", "ELASTIC_URL")
    key = env("ELASTIC_API_KEY", "ELASTIC_CLOUD_KEY")
    return (url, key) if url and key else None


def elastic_events_index() -> str:
    return env("ELASTIC_EVENTS_INDEX", default=DEFAULT_EVENTS_INDEX)


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
