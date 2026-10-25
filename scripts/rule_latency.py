"""How fast is "which rule governs this instruction", and how does it scale with the number of rules?

Three ways to answer, measured side by side:
  dict     a compiled table: instruction type -> rule (fastest possible, but only exact keys, edited in code)
  scan     the same stored queries evaluated one by one in Python (what you write without a search engine)
  elastic  the stored queries percolated in Elasticsearch (rules are data, edited in the index, no deploy)

    python scripts/rule_latency.py                       # local only
    python scripts/rule_latency.py --elastic             # also percolate in Elastic (needs ELASTIC_* keys)
    python scripts/rule_latency.py --elastic --sizes 7,100,1000,5000

The extra rules are SYNTHETIC filler (labelled so), loaded into a temporary index that is deleted at the end; they
exist only to show how each approach grows. Our real rule file has a handful of rules, where a dict wins; the
point of Elastic is that rules are data you can change at runtime and that matching stays flat as they grow.
Writes data/rule-latency/<time>.json.
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
from unstep.ground.rules import MAPPINGS, LocalRules, load_rules, rule_doc  # noqa: E402

TEXT = "Cessna one two three, hold short runway three three"
RUNS = 200
TEMP_INDEX = "unstep-rules-bench"


def synthetic(n: int) -> list[dict]:
    real = load_rules()
    extra = [{"id": f"synthetic-{i}", "phrases": [f"synthetic route {i} alpha", f"synthetic route {i} bravo"],
              "paragraph": None, "title": None, "status": "needs_review", "evidence": "synthetic filler"}
             for i in range(max(0, n - len(real)))]
    return real + extra


def timed(fn, runs: int = RUNS) -> dict:
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    return {"p50_ms": round(statistics.median(samples), 4), "p95_ms": round(samples[int(len(samples) * 0.95) - 1], 4)}


def local_row(n: int) -> dict:
    rules = synthetic(n)
    table = {r["phrases"][0]: r for r in rules}  # compiled: exact instruction type -> rule
    scan = LocalRules(rules)
    return {"rules": len(rules), "dict": timed(lambda: table.get("hold short")), "scan": timed(lambda: scan.match(TEXT))}


def elastic_row(client: httpx.Client, url: str, n: int) -> dict:
    rules = synthetic(n)
    client.delete(f"{url}/{TEMP_INDEX}")
    client.put(f"{url}/{TEMP_INDEX}", json={"mappings": MAPPINGS}).raise_for_status()
    lines = []
    for r in rules:
        lines += [json.dumps({"index": {"_index": TEMP_INDEX, "_id": r["id"]}}), json.dumps(rule_doc(r))]
    client.post(f"{url}/_bulk?refresh=true", content="\n".join(lines) + "\n",
                headers={"content-type": "application/x-ndjson"}).raise_for_status()
    from unstep.ground.percolate import normalize

    body = {"query": {"percolate": {"field": "query", "document": {"text": normalize(TEXT)}}}}
    took = []

    def once():
        r = client.post(f"{url}/{TEMP_INDEX}/_search", json=body)
        r.raise_for_status()
        took.append(r.json().get("took", 0))

    wall = timed(once, runs=50)
    return {"wall": wall, "took_p50_ms": statistics.median(took)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", default="7,100,1000,5000")
    parser.add_argument("--elastic", action="store_true")
    args = parser.parse_args()
    sizes = [int(x) for x in args.sizes.split(",")]
    report = {"text": TEXT, "started": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "rows": []}
    client = url = None
    if args.elastic:
        settings = elastic_settings()
        if not settings:
            print("Need ELASTIC_URL and ELASTIC_API_KEY for --elastic")
            return
        url = settings[0].rstrip("/")
        client = httpx.Client(headers={"Authorization": f"ApiKey {settings[1]}"}, timeout=20)
    print(f"{'rules':>6} {'dict p50':>10} {'scan p50':>10} {'scan p95':>10}" + (f" {'elastic wall p50':>17} {'took p50':>9}" if client else ""))
    try:
        for n in sizes:
            row = local_row(n)
            line = f"{row['rules']:>6} {row['dict']['p50_ms']:>8}ms {row['scan']['p50_ms']:>8}ms {row['scan']['p95_ms']:>8}ms"
            if client:
                row["elastic"] = elastic_row(client, url, n)
                line += f" {row['elastic']['wall']['p50_ms']:>15}ms {row['elastic']['took_p50_ms']:>7}ms"
            report["rows"].append(row)
            print(line)
    finally:
        if client:
            client.delete(f"{url}/{TEMP_INDEX}")
    out = ROOT / "data" / "rule-latency"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=1))
    print(f"\nwrote {path.relative_to(ROOT)}. The filler rules are synthetic. Wall time includes the network from this machine.")


if __name__ == "__main__":
    main()
