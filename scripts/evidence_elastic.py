"""Evidence for the Elastic table in the README, measured on our own Elastic project.

    python scripts/evidence_elastic.py              # needs ELASTIC_CLOUD_URL, KIBANA_URL and ELASTIC_API_KEY in .env
    python scripts/evidence_elastic.py --runs 30

Measures:
  objects     the Agent Builder agents, tools and Workflows that exist on the project (counted from Kibana, not from our files)
  citation    the closest FAA paragraph by hybrid search with the Jina reranker, the call the decision card waits for
  geo         `geo_shape` lookup of which area a plane is in, Elastic's own `took` and our wall clock
  audit       how many events, proposals and policy decisions are stored, and an ES|QL query over them
  tools       the tools the MCP server exposes

The percolator number (readback matched to its rule) comes from scripts/rule_latency.py --elastic; its output is saved
next to this file. Every number carries its sample count. Writes docs/evidence/elastic-<date>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unstep.config import elastic_settings, kibana_url  # noqa: E402
from unstep.ground.elastic_agents import ElasticAgents  # noqa: E402
from unstep.live.geo import Geo  # noqa: E402


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 1)


def summary(values: list[float]) -> dict:
    return {"n": len(values), "p50": pct(values, 0.5), "p95": pct(values, 0.95), "mean": round(statistics.fmean(values), 1),
            "max": round(max(values), 1)}


async def get_json(client: httpx.AsyncClient, url: str):
    r = await client.get(url, headers={"kbn-xsrf": "true"})
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:200])


def ids(payload, key: str) -> list[str]:
    items = payload.get(key, payload.get("results", payload)) if isinstance(payload, dict) else payload
    return sorted(str(i.get("id") or i.get("name")) for i in items if isinstance(i, dict))


async def main(runs: int) -> dict:
    settings = elastic_settings()
    kibana = kibana_url()
    if not settings or not kibana:
        raise SystemExit("Elastic is not configured (ELASTIC_CLOUD_URL, KIBANA_URL, ELASTIC_API_KEY).")
    es, key = settings[0].rstrip("/"), settings[1]
    result: dict = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    async with httpx.AsyncClient(headers={"Authorization": f"ApiKey {key}"}, timeout=15.0) as client:
        # objects that exist on the project
        objects = {}
        for label, path, key_name in (("agents", "/api/agent_builder/agents", "results"), ("tools", "/api/agent_builder/tools", "results")):
            status, body = await get_json(client, f"{kibana}{path}")
            names = [n for n in ids(body, key_name)] if status == 200 else []
            ours = [n for n in names if n.startswith("unstep")]
            objects[label] = {"http": status, "total_on_project": len(names), "ours": len(ours), "ids": ours}
        status, body = await get_json(client, f"{kibana}/api/workflows?size=100")
        workflows = []
        if status == 200 and isinstance(body, dict):
            workflows = [w.get("name") or w.get("id") for w in (body.get("results") or body.get("workflows") or []) if isinstance(w, dict)]
        objects["workflows"] = {"http": status, "ours": len([w for w in workflows if str(w).startswith("unstep")]),
                                "ids": sorted(str(w) for w in workflows if str(w).startswith("unstep"))}
        result["objects"] = objects

        # the FAA citation: hybrid search plus reranker, as the decision card waits for it
        agents = ElasticAgents(kibana, es, key)
        try:
            cited, ms, reranked = [], [], 0
            for query in ("hold short runway 33", "cleared for takeoff runway 33", "go around", "line up and wait runway 33",
                          "readback hold short instructions")[:max(1, runs // 6) or 1] * 6:
                hit = await agents.cite(query, wait_s=5.0)
                if hit:
                    cited.append(hit["paragraph"])
                    ms.append(hit["ms"])
                    reranked += bool(hit["reranked"])
            result["faa_citation_hybrid_rerank"] = {"timing_ms": summary(ms) if ms else None, "answers": len(ms), "reranked": reranked,
                                                    "paragraphs": sorted(set(cited))}
        finally:
            await agents.aclose()

        # geo_shape: which area is a plane in
        geo = Geo()
        took, wall = [], []
        for _ in range(runs):
            out = await geo.locate([{"id": "N123AB", "x": -14.8, "z": 14.0, "alt": 0, "state": "taxi"}])
            if out["backend"] == "elastic":
                took.append(out["took_ms"])
                wall.append(out["ms"])
        result["geo_shape_area_lookup"] = {"elastic_took_ms": summary(took) if took else None, "wall_ms": summary(wall) if wall else None,
                                           "backend_answered": len(took), "area_example": (out["planes"]["N123AB"]["areas"])}

        # the audit trail and ES|QL
        counts = {}
        for index in ("unstep-events", "unstep-proposals", "unstep-policy", "unstep-clearances", "unstep-flights", "unstep-faa", "unstep-rules",
                      "unstep-flightplans", "unstep-airport", "unstep-positions"):
            r = await client.get(f"{es}/{index}/_count")
            counts[index] = r.json().get("count") if r.status_code == 200 else f"HTTP {r.status_code}"
        status, found = await get_json(client, f"{kibana}/api/saved_objects/_find?type=map&per_page=5")
        maps = [o.get("attributes", {}).get("title") for o in found.get("saved_objects", [])] if status == 200 and isinstance(found, dict) else []
        counts["kibana_maps"] = {"http": status, "titles": maps}
        q_ms = []
        rows = None
        for _ in range(max(5, runs // 3)):
            t = time.perf_counter()
            r = await client.post(f"{es}/_query", json={"query": "FROM unstep-events | STATS events = COUNT(*), planes = COUNT_DISTINCT(callsign)"})
            q_ms.append((time.perf_counter() - t) * 1000)
            if r.status_code == 200:
                rows = r.json().get("values")
        result["audit_trail"] = {"documents": counts, "esql_events_and_planes": rows, "esql_wall_ms": summary(q_ms)}

        # MCP: the tools the server exposes
        r = await client.post(f"{kibana}/api/agent_builder/mcp", headers={"kbn-xsrf": "true", "Accept": "application/json, text/event-stream"},
                              json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = []
        if r.status_code == 200:
            text = r.text
            body = json.loads(text) if text.lstrip().startswith("{") else json.loads(text.split("data:", 1)[1].strip().splitlines()[0])
            tools = sorted(t["name"] for t in body.get("result", {}).get("tools", []))
        result["mcp"] = {"http": r.status_code, "tools_exposed": len(tools), "ours": [t for t in tools if "unstep" in t]}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "evidence")
    args = parser.parse_args()
    out = asyncio.run(main(args.runs))
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"elastic-{datetime.now().strftime('%Y-%m-%d')}.json"
    path.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, indent=1, default=str))
    print("wrote", path)
