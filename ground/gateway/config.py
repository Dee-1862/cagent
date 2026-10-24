"""Gateway settings from the environment, with an optional local .env file."""

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path = Path(".env")) -> None:
    """Reads KEY=VALUE lines into os.environ without overriding what is set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    events_path: Path
    elastic_url: str | None
    elastic_api_key: str | None
    elastic_events_index: str
    elastic_workflow_url: str | None
    voice_controller_id: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        env = os.environ.get
        return cls(
            host=env("UNSTEP_GATEWAY_HOST", "0.0.0.0"),
            port=int(env("UNSTEP_GATEWAY_PORT", "8765")),
            events_path=Path(env("UNSTEP_EVENTS_PATH", "data/events.jsonl")),
            elastic_url=env("ELASTIC_URL") or None,
            elastic_api_key=env("ELASTIC_API_KEY") or None,
            elastic_events_index=env("ELASTIC_EVENTS_INDEX", "unstep-events"),
            elastic_workflow_url=env("ELASTIC_WORKFLOW_URL") or None,
            voice_controller_id=env("UNSTEP_CONTROLLER_ID", "controller-1"),
        )
