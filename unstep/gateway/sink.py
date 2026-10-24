"""Event sink: every message through the gateway is stored here.

For M2 this appends JSON lines to data/events.jsonl. Task B1 replaces it with
the Elastic events index, keeping the same `write` method.
"""

import json
from pathlib import Path


class JsonlSink:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, envelope: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(envelope) + "\n")


class MemorySink:
    """For tests."""

    def __init__(self):
        self.records: list[dict] = []

    def write(self, envelope: dict) -> None:
        self.records.append(envelope)
