"""Call Unstep's Elastic tools from outside Elastic, through Agent Builder's MCP server.

    python scripts/mcp_demo.py                      # list the tools the MCP server exposes
    python scripts/mcp_demo.py unstep_trend_decisions   # call one tool (tools that need parameters: --args '{"k":"v"}')

Any MCP client (a coding agent, Moss's `McpServer` tool entry) can do the same with this URL and an API key. The
endpoint path (`/api/agent_builder/mcp`) is from Elastic's docs; the first live run should confirm the tool names it
lists. Read-only: it only lists and calls tools, and the tools we expose are stored ES|QL reads. Needs
ELASTIC_CLOUD_URL (or KIBANA_URL) and ELASTIC_API_KEY in `.env`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unstep.config import elastic_settings, kibana_url  # noqa: E402

MCP_PATH = "/api/agent_builder/mcp"


def parse_reply(response: httpx.Response) -> dict:
    """A reply is JSON or one server-sent event; return the JSON-RPC message either way."""
    text = response.text.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return {}


class McpClient:
    def __init__(self, base: str, api_key: str, transport=None):
        self.client = httpx.AsyncClient(
            base_url=base, transport=transport, timeout=30,
            headers={"Authorization": f"ApiKey {api_key}", "kbn-xsrf": "true",
                     "Accept": "application/json, text/event-stream", "Content-Type": "application/json"})
        self._id = 0
        self.session: str | None = None

    async def _rpc(self, method: str, params: dict | None = None, notify: bool = False) -> dict:
        message = {"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})}
        if not notify:
            self._id += 1
            message["id"] = self._id
        headers = {"Mcp-Session-Id": self.session} if self.session else {}
        response = await self.client.post(MCP_PATH, json=message, headers=headers)
        response.raise_for_status()
        self.session = response.headers.get("Mcp-Session-Id", self.session)
        return {} if notify else parse_reply(response)

    async def start(self) -> dict:
        reply = await self._rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                               "clientInfo": {"name": "unstep-demo", "version": "1"}})
        await self._rpc("notifications/initialized", notify=True)
        return reply

    async def tools(self) -> list[dict]:
        return (await self._rpc("tools/list")).get("result", {}).get("tools", [])

    async def call(self, name: str, arguments: dict | None = None) -> dict:
        return await self._rpc("tools/call", {"name": name, "arguments": arguments or {}})

    async def close(self) -> None:
        await self.client.aclose()


async def main_async(tool: str | None, arguments: dict) -> int:
    settings, base = elastic_settings(), kibana_url()
    if not settings or not base:
        print("skipped: set ELASTIC_CLOUD_URL (or KIBANA_URL) and ELASTIC_API_KEY in .env")
        return 0
    client = McpClient(base, settings[1])
    try:
        await client.start()
        if tool is None:
            for t in await client.tools():
                print(f"{t.get('name')}: {(t.get('description') or '')[:100]}")
            return 0
        print(json.dumps(await client.call(tool, arguments), indent=2)[:3000])
        return 0
    except httpx.HTTPError as exc:
        print(f"failed: {type(exc).__name__}: {exc}")
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tool", nargs="?")
    ap.add_argument("--args", default="{}")
    a = ap.parse_args()
    sys.exit(asyncio.run(main_async(a.tool, json.loads(a.args))))
