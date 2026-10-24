"""Settings from the environment and the local .env file (never committed).

Every connection and vendor setting is read here, with a default, so nothing
else in the code needs a hardcoded URL, model, version, index or token. The
.env file is loaded when this module is imported; variables already set in the
shell win over .env.
"""

import os
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_GATEWAY_URL = "ws://127.0.0.1:8765"
DEFAULT_CARTESIA_VERSION = "2026-08-14"
DEFAULT_CARTESIA_STT_MODEL = "ink-2"
# ink-2 has key terms but no word timestamps; ink-whisper has word timestamps.
DEFAULT_CARTESIA_STT_TIMESTAMP_MODEL = "ink-whisper"
DEFAULT_CARTESIA_TTS_MODEL = "sonic-3.6"
DEFAULT_EVENTS_INDEX = "unstep-events"
DEFAULT_PENDING_TTL_S = 60.0
DEFAULT_MOSS_INFERENCE_MODEL = "moss"


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


def allowed_hosts() -> list[str]:
    """Host headers the gateway answers to. Local only by default, which blocks DNS
    rebinding: a web page on another domain can't reach the gateway through the
    browser. Add LAN names or IPs with UNSTEP_ALLOWED_HOSTS (comma separated); the
    host of UNSTEP_GATEWAY_URL is always allowed."""
    from urllib.parse import urlparse

    hosts = ["127.0.0.1", "localhost", "[::1]", "::1"]
    gw_host = urlparse(gateway_url()).hostname
    if gw_host:
        hosts.append(gw_host)
    extra = env("UNSTEP_ALLOWED_HOSTS") or ""
    hosts += [h.strip() for h in extra.split(",") if h.strip()]
    return sorted(set(hosts))


def allowed_origins() -> list[str]:
    """Web origins on other domains that may open a live room socket, for example the
    pilot app on Vercel: UNSTEP_ALLOWED_ORIGINS=https://unstep.vercel.app (comma
    separated, `*` wildcards allowed, as in https://*.vercel.app). Pages served by the
    gateway itself are always allowed. The gateway token still applies."""
    extra = env("UNSTEP_ALLOWED_ORIGINS") or ""
    return [o.strip().rstrip("/") for o in extra.split(",") if o.strip()]


def gateway_token() -> str | None:
    """Optional shared secret (FR-13). When set, every client must send it."""
    return env("UNSTEP_GATEWAY_TOKEN")


def ws_url(role: str, base: str | None = None) -> str:
    """The WebSocket address for a role. A query already in `base` (such as
    ?token=...) is kept; otherwise the token from the environment is added."""
    parts = urlsplit(base or gateway_url())
    query = parse_qsl(parts.query)
    token = gateway_token()
    if token and not any(k == "token" for k, _ in query):
        query.append(("token", token))
    path = parts.path.rstrip("/") + f"/ws/{role}"
    return urlunsplit(parts._replace(path=path, query=urlencode(query, quote_via=quote)))


def pending_ttl_s() -> float:
    return float(env("UNSTEP_PENDING_TTL_S", default=str(DEFAULT_PENDING_TTL_S)))


# Cartesia


def cartesia_version() -> str:
    return env("CARTESIA_VERSION", default=DEFAULT_CARTESIA_VERSION)


def cartesia_stt_model() -> str:
    return env("CARTESIA_STT_MODEL", default=DEFAULT_CARTESIA_STT_MODEL)


def cartesia_stt_timestamp_model() -> str:
    return env("CARTESIA_STT_TIMESTAMP_MODEL", default=DEFAULT_CARTESIA_STT_TIMESTAMP_MODEL)


DEFAULT_MOSS_AIRCRAFT = 6


def moss_aircraft() -> int:
    """How many aircraft get their own Moss session (UNSTEP_MOSS_AIRCRAFT, default 6, the whole fleet).

    A Moss session is a local in-memory index; only push_index() writes a cloud index,
    and per-aircraft sessions are never pushed. Rishit ran six real sessions at once
    (agent mail R3): 0 to 1 ms searches and no new cloud indexes.
    """
    try:
        return max(0, int(env("UNSTEP_MOSS_AIRCRAFT", default=str(DEFAULT_MOSS_AIRCRAFT))))
    except ValueError:
        return DEFAULT_MOSS_AIRCRAFT


def radio_sound() -> bool:
    """Listeners hear transmissions band-limited like VHF radio (UNSTEP_RADIO_SOUND, default on)."""
    return env("UNSTEP_RADIO_SOUND", default="1").lower() not in ("0", "false", "no", "off")


def realtime_replay() -> bool:
    """Pace replayed audio to the manual STT endpoint at real time (UNSTEP_REALTIME_REPLAY=1).

    Off by default: a 15-run re-test showed /stt/websocket transcribes audio sent as
    fast as possible just as well (docs/09-cartesia-feedback.md, "Measured re-test"),
    which saves about the clip's length per replay. The turns endpoint is always paced.
    """
    return env("UNSTEP_REALTIME_REPLAY", default="0").lower() in ("1", "true", "yes", "on")


def cartesia_tts_model() -> str:
    return env("CARTESIA_TTS_MODEL", default=DEFAULT_CARTESIA_TTS_MODEL)


# Moss


def moss_inference_model() -> str:
    return env("MOSS_INFERENCE_MODEL", default=DEFAULT_MOSS_INFERENCE_MODEL)


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
