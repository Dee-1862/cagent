"""Starts the Elastic Workflow for each AnomalyEvent (task B5).

The request shape is a placeholder until B5 confirms the Workflow endpoint
against the Elastic docs (M-010). Firing never blocks the live path.
"""

import asyncio
import logging

import httpx

log = logging.getLogger("unstep.workflow")


class NoopTrigger:
    def __init__(self) -> None:
        self.fired: list[str] = []

    def fire(self, event_id: str) -> None:
        self.fired.append(event_id)

    async def stop(self) -> None:
        pass


class HttpWorkflowTrigger:
    def __init__(self, url: str, api_key: str) -> None:
        self.url = url
        self._headers = {"Authorization": f"ApiKey {api_key}"}
        self._tasks: set[asyncio.Task] = set()

    def fire(self, event_id: str) -> None:
        task = asyncio.create_task(self._post(event_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _post(self, event_id: str) -> None:
        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=10) as client:
                response = await client.post(self.url, json={"event_id": event_id})
                response.raise_for_status()
        except Exception:
            log.exception("workflow trigger failed for %s", event_id)

    async def stop(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
