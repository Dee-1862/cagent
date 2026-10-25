"""The shift briefing and the nightly review, saved by Elastic workflows and shown on the console.

Both workflows run on a schedule and by hand; each saves one document (`unstep-briefings`, `unstep-reviews`). This
module only reads the newest document and can start a run now. Read-only for the audit trail, off the radio path,
one run at a time, and a failure just says so.
"""

from __future__ import annotations

import logging
import time

import httpx

from unstep.config import elastic_settings, kibana_url

log = logging.getLogger("unstep.reports")

REPORTS = {"briefing": ("unstep-briefing", "unstep-briefings", "briefing"),
           "review": ("unstep-nightly-review", "unstep-reviews", "review")}
MIN_GAP_S = 20.0


class Reports:
    def __init__(self, es: str, kibana: str, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self.es, self.kibana = es.rstrip("/"), kibana.rstrip("/")
        self.client = httpx.AsyncClient(headers={"Authorization": f"ApiKey {api_key}", "kbn-xsrf": "true"},
                                        timeout=10, transport=transport)
        self._last_run = 0.0

    async def latest(self) -> dict:
        out: dict = {}
        for name, (_, index, field) in REPORTS.items():
            try:
                r = await self.client.post(f"{self.es}/{index}/_search",
                                           json={"size": 1, "sort": [{"@timestamp": "desc"}]})
                hits = r.json().get("hits", {}).get("hits", []) if r.status_code == 200 else []
                src = hits[0]["_source"] if hits else None
                out[name] = {"text": src.get(field), "at": src.get("@timestamp")} if src else None
            except (httpx.HTTPError, ValueError, KeyError):
                out[name] = None
        return out

    async def run(self, which: str) -> dict:
        if which not in REPORTS:
            return {"ok": False, "error": "Unknown report."}
        if time.monotonic() - self._last_run < MIN_GAP_S:
            return {"ok": False, "error": "A report was just started. Try again in a moment."}
        self._last_run = time.monotonic()
        workflow = REPORTS[which][0]
        try:
            r = await self.client.post(f"{self.kibana}/api/workflows/workflow/{workflow}/run", json={"inputs": {}})
            r.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("could not start %s: %s", workflow, type(exc).__name__)
            return {"ok": False, "error": "Elastic didn't start the report."}
        return {"ok": True, "workflow": workflow, "note": "Started. It takes about 10 to 20 s; refresh the report then."}


def reports_from_env() -> Reports | None:
    settings, kb = elastic_settings(), kibana_url()
    return Reports(settings[0], kb, settings[1]) if settings and kb else None
