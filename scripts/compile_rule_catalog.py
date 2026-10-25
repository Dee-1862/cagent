"""Compile the rule catalog: find the FAA paragraphs that most likely govern each instruction type, for a person to review.

Star trackers are fast because the hard work is done ahead of time: a catalog of known patterns is built once, and
at run time a lookup identifies what the camera sees. This does the same for instructions. The slow, fuzzy search
(hybrid keyword and meaning search with a reranker, over the FAA order in Elastic) runs here, offline, for every
instruction type Unstep knows; the output is a short list of candidate paragraphs per type with their scores. A
person reads the paragraphs, picks one, and sets its status to `reviewed` in elastic/rules/rules.json. At run time
the hub then answers from the stored rule in milliseconds and never searches.

    python scripts/compile_rule_catalog.py            # print candidates and write data/rule-catalog/<time>.json
    python scripts/compile_rule_catalog.py --top 5

Needs ELASTIC_CLOUD_URL (or ELASTIC_URL) and ELASTIC_API_KEY. It only reads: it changes nothing in Elastic and
never edits rules.json. Scores are the reranker's; they rank candidates, they do not prove a paragraph governs.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unstep.config import elastic_settings  # noqa: E402
from unstep.ground.elastic_agents import faa_search_body, rerank_id  # noqa: E402
from unstep.ground.rules import load_rules  # noqa: E402

# One plain sentence per instruction type: what a controller means, in words the FAA text would use.
QUERIES = {
    "hold-short": "instruct aircraft to hold short of the runway",
    "hold-position": "instruct aircraft to hold position and not move",
    "line-up-and-wait": "line up and wait on the runway before takeoff clearance",
    "cleared-for-takeoff": "clearance for takeoff from the runway",
    "cleared-to-land": "clearance to land on the runway",
    "go-around": "instruct aircraft to go around when landing is not possible",
    "stop": "instruct aircraft to stop immediately on the movement area",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--top", type=int, default=3)
    args = parser.parse_args()
    settings = elastic_settings()
    if not settings:
        print("Need ELASTIC_URL (or ELASTIC_CLOUD_URL) and ELASTIC_API_KEY")
        return
    url, key = settings[0].rstrip("/"), settings[1]
    reranker = rerank_id()
    known = {r["id"]: r for r in load_rules()}
    client = httpx.Client(headers={"Authorization": f"ApiKey {key}"}, timeout=30)
    report = {"started": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "reranker": reranker, "rules": {}}
    wall = []
    for rule_id, query in QUERIES.items():
        started = time.perf_counter()
        body = faa_search_body(query, reranker, size=args.top)
        r = client.post(f"{url}/unstep-faa/_search", json=body)
        if r.status_code != 200 and reranker:  # a rejected reranker: plain hybrid, and say so
            body = faa_search_body(query, None, size=args.top)
            r = client.post(f"{url}/unstep-faa/_search", json=body)
        ms = (time.perf_counter() - started) * 1000
        wall.append(ms)
        r.raise_for_status()
        hits = [{"paragraph": h["_source"].get("paragraph"), "title": h["_source"].get("title"),
                 "score": round(h["_score"] or 0, 3), "text": (h["_source"].get("body") or "")[:200]}
                for h in r.json()["hits"]["hits"]]
        current = known.get(rule_id, {})
        report["rules"][rule_id] = {"query": query, "search_ms": round(ms, 1), "took_ms": r.json().get("took"),
                                    "current": {k: current.get(k) for k in ("paragraph", "status")}, "candidates": hits}
        print(f"\n{rule_id}  ({round(ms)} ms, took {r.json().get('took')} ms)  current: "
              f"{current.get('paragraph')} [{current.get('status')}]")
        for h in hits:
            print(f"   {h['score']:>7}  {h['paragraph']}  {h['title']}")
    out = ROOT / "data" / "rule-catalog"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=1))
    print(f"\nhybrid search wall time over {len(wall)} queries: p50 {round(statistics.median(wall))} ms, "
          f"max {round(max(wall))} ms (includes the network from this machine)")
    print(f"wrote {path.relative_to(ROOT)}. Candidates are for a person to read; nothing was changed.")


if __name__ == "__main__":
    main()
