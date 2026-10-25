"""Create Unstep's Elastic ground agents (B5): indexes, Agent Builder tools and agents, Workflows.

Reads the definitions in elastic/ and sends them to your Elasticsearch and Kibana.
Run on a machine with ELASTIC_URL (or ELASTIC_CLOUD_URL), ELASTIC_API_KEY and, if
Kibana is not the Elasticsearch address with ".es." -> ".kb.", KIBANA_URL:

    python scripts/deploy_elastic.py --dry-run    # print every request, send nothing
    python scripts/deploy_elastic.py              # create what is missing, keep what exists
    python scripts/deploy_elastic.py --replace    # also update existing tools, agents, workflows

The FAA search tool needs the unstep-faa index to exist first, so on a fresh project run
`python scripts/ingest_faa.py --source data/faa` before the real deploy (or re-run the deploy after it).

Then set UNSTEP_ELASTIC_AGENTS=1 for the live room. API paths used (Kibana 9.4 / Serverless):
POST /api/agent_builder/tools, POST /api/agent_builder/agents (PUT /{id} to update),
POST /api/workflows?overwrite=. Prints one line per object and exits 1 on any failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unstep.config import elastic_settings, kibana_url  # noqa: E402

DEFS = ROOT / "elastic"

def _audit_indexes() -> dict:
    """The audit trail and the benchmark in Elastic: simulated records live in their own index, labelled."""
    from unstep.evaluation import EVAL_INDEX, EVAL_MAPPINGS
    from unstep.gateway.sink import MAPPINGS

    from unstep.config import elastic_events_index

    from unstep.ground.flights import FLIGHTS_INDEX, MAPPINGS as FLIGHT_MAPPINGS

    return {elastic_events_index(): {"mappings": MAPPINGS}, "unstep-sim-events": {"mappings": MAPPINGS},
            EVAL_INDEX: {"mappings": EVAL_MAPPINGS}, FLIGHTS_INDEX: {"mappings": FLIGHT_MAPPINGS}}


DATA_VIEWS = {  # Kibana data views, so Discover and Lens can chart the audit trail and the benchmark
    "unstep-events": "@timestamp", "unstep-sim-events": "@timestamp", "unstep-eval": "@timestamp"}  # events: see below

INDEXES = {
    # The workflow writes the agents' answers here, keyed by event id; the hub reads them back.
    "unstep-proposals": {"mappings": {"properties": {"event_id": {"type": "keyword"},
                                                     "execution_id": {"type": "keyword"},
                                                     "intercept": {"type": "text", "index": False},
                                                     "compliance": {"type": "text", "index": False}}}},
    # Shift handoff briefings written by the unstep-briefing workflow; a pipeline stamps @timestamp on write.
    "unstep-briefings": {"settings": {"index.default_pipeline": "unstep-briefings-timestamp"},
                         "mappings": {"properties": {"@timestamp": {"type": "date"}, "focus": {"type": "keyword"},
                                                     "execution_id": {"type": "keyword"},
                                                     "briefing": {"type": "text"}}}},
    "unstep-reviews": {"settings": {"index.default_pipeline": "unstep-briefings-timestamp"},
                       "mappings": {"properties": {"@timestamp": {"type": "date"}, "execution_id": {"type": "keyword"},
                                                   "review": {"type": "text"}}}},
    "unstep-findings": {"mappings": {"properties": {"event_id": {"type": "keyword"},
                                                    "execution_id": {"type": "keyword"},
                                                    "audit": {"type": "text", "index": False}}}},
}


MAP_VIEWS = {  # fixed ids, so the saved map can point at its data views
    "unstep-airport": ("unstep-airport", None), "unstep-positions": ("unstep-positions", "ts")}


def map_steps() -> list[tuple[str, str, str, dict | None]]:
    """The Kibana map (airport shapes plus plane tracks). The saved-object layout is written from memory of Kibana's
    Maps format and has not been run against a cluster: the first live run is the check (hence `--only maps`)."""
    steps: list[tuple[str, str, str, dict | None]] = []
    for view_id, (title, time_field) in MAP_VIEWS.items():
        view = {"id": view_id, "title": title, "name": title, **({"timeFieldName": time_field} if time_field else {})}
        steps.append((f"data view {title}", "POST", "kb/api/data_views/data_view", {"data_view": view, "override": True}))
    for path in sorted((DEFS / "maps").glob("*.json")):
        saved = json.loads(path.read_text())
        steps.append((f"map {saved['id']}", "POST", f"kb/api/saved_objects/map/{saved['id']}?overwrite=true",
                      {"attributes": saved["attributes"]}))
    return steps


def load_definitions() -> dict[str, list]:
    tools = [json.loads(p.read_text()) for p in sorted((DEFS / "tools").glob("*.json"))]
    agents = [json.loads(p.read_text()) for p in sorted((DEFS / "agents").glob("*.json"))]
    workflows = [{"id": p.stem, "yaml": p.read_text()} for p in sorted((DEFS / "workflows").glob("*.yaml"))]
    return {"tools": tools, "agents": agents, "workflows": workflows}


def plan(replace: bool) -> list[tuple[str, str, str, dict | None]]:
    """(label, method, "es"|"kb" + path, body) for every request, in order."""
    d = load_definitions()
    steps: list[tuple[str, str, str, dict | None]] = []
    steps.append(("pipeline unstep-briefings-timestamp", "PUT", "es/_ingest/pipeline/unstep-briefings-timestamp",
                  {"processors": [{"set": {"field": "@timestamp", "value": "{{_ingest.timestamp}}"}}]}))
    for name, body in {**INDEXES, **_audit_indexes()}.items():
        steps.append((f"index {name}", "PUT", f"es/{name}", body))
    from unstep.config import elastic_events_index

    views = {**DATA_VIEWS, elastic_events_index(): "@timestamp"}
    for name, time_field in views.items():  # path from Kibana's data views API: check on first run (E-3)
        steps.append((f"data view {name}", "POST", "kb/api/data_views/data_view",
                      {"data_view": {"title": name, "name": name, "timeFieldName": time_field}, "override": False}))
    from unstep.ground.rules import MAPPINGS as RULE_MAPPINGS, RULES_INDEX, load_rules, rule_doc

    steps.append((f"index {RULES_INDEX}", "PUT", f"es/{RULES_INDEX}", {"mappings": RULE_MAPPINGS}))
    for rule in load_rules():  # rules as data: one stored percolator query per rule, refreshed so it answers at once
        steps.append((f"rule {rule['id']}", "PUT", f"es/{RULES_INDEX}/_doc/{rule['id']}?refresh=true", rule_doc(rule)))
    for tool in d["tools"]:
        steps.append((f"tool {tool['id']}", "POST", "kb/api/agent_builder/tools", tool))
    for agent in d["agents"]:
        steps.append((f"agent {agent['id']}", "POST", "kb/api/agent_builder/agents", agent))
    steps.append(("workflows " + ", ".join(w["id"] for w in d["workflows"]), "POST",
                  f"kb/api/workflows?overwrite={'true' if replace else 'false'}", {"workflows": d["workflows"]}))
    return steps


def _update(client: httpx.Client, base: str, label: str, body: dict) -> httpx.Response:
    kind = "tools" if label.startswith("tool ") else "agents"
    rest = {k: v for k, v in body.items() if k not in ("id", "type")}
    return client.put(f"{base}/api/agent_builder/{kind}/{body['id']}", json=rest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--only", choices=["maps"], help="deploy just this part; it touches no agent, tool or workflow")
    args = parser.parse_args()
    steps = map_steps() if args.only == "maps" else plan(args.replace)
    if args.dry_run:
        for label, method, path, body in steps:
            print(f"{method} {path}  # {label}")
            print(json.dumps(body, indent=2)[:2000])
        return 0
    settings, kb = elastic_settings(), kibana_url()
    if not settings or not kb:
        print("Need ELASTIC_URL and ELASTIC_API_KEY (and KIBANA_URL if it can't be derived).", file=sys.stderr)
        return 1
    es, key = settings
    failed = 0
    headers = {"Authorization": f"ApiKey {key}", "kbn-xsrf": "true", "Content-Type": "application/json"}
    with httpx.Client(headers=headers, timeout=30) as client:
        for label, method, path, body in steps:
            base = es.rstrip("/") if path.startswith("es/") else kb.rstrip("/")
            r = client.request(method, f"{base}/{path[3:]}", json=body)
            exists = r.status_code in (400, 409) and ("already" in r.text or "exists" in r.text)
            if exists and args.replace and (label.startswith("tool ") or label.startswith("agent ")):
                r = _update(client, kb.rstrip("/"), label, body)
                exists = False
            ok = r.is_success or exists
            soft = label.startswith("data view") and args.only != "maps"  # a convenience for Discover and Lens: never fails the deploy
            failed += not ok and not soft
            print(f"{'ok  ' if ok else ('warn' if soft else 'FAIL')} {label}: {r.status_code}"
                  f"{' (exists, kept)' if exists else ''}" + ("" if ok else f" {r.text[:300]}"))
            if not ok and "faa" in label and "unstep-faa" in r.text:
                print("     hint: create the index first: python scripts/ingest_faa.py --source data/faa, then re-run")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
