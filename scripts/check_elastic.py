"""Checks the Elastic settings in .env without printing any secret.

    python scripts/check_elastic.py

Reports whether the Elasticsearch URL, the Kibana URL and the API key work,
and catches the common mix-up of putting the Elasticsearch address (".es.")
in KIBANA_URL or the other way round.
"""

import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from unstep.config import env, kibana_url, load_env


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'ok' if ok else 'FAIL'}] {name}{': ' + detail if detail else ''}")
    return ok


def main() -> int:
    load_env()
    es = env("ELASTIC_CLOUD_URL", "ELASTIC_URL")
    key = env("ELASTIC_API_KEY", "ELASTIC_CLOUD_KEY")
    kb = kibana_url()
    good = True

    good &= check("ELASTIC_API_KEY is set", bool(key))
    good &= check("ELASTIC_CLOUD_URL is set", bool(es), "" if es else "add the Elasticsearch URL (contains .es.)")
    if es:
        good &= check("ELASTIC_CLOUD_URL is an Elasticsearch address", ".es." in urlparse(es).netloc,
                      "" if ".es." in urlparse(es).netloc else "it should contain .es., not .kb.")
    if kb and ".es." in urlparse(kb).netloc:
        good &= check("KIBANA_URL is a Kibana address", False,
                      "it contains .es., so it is the Elasticsearch address. Use the same URL with .kb.")
    if not key:
        return 1

    headers = {"Authorization": f"ApiKey {key}", "kbn-xsrf": "true"}
    if es:
        try:
            r = httpx.get(es.rstrip("/") + "/", headers=headers, timeout=20)
            good &= check("Elasticsearch answers with this key", r.status_code == 200, f"HTTP {r.status_code}")
        except httpx.HTTPError as e:
            good &= check("Elasticsearch reachable", False, type(e).__name__)
    if kb and ".kb." in urlparse(kb).netloc:
        try:
            r = httpx.get(kb + "/api/status", headers=headers, timeout=20)
            level = r.json()["status"]["overall"]["level"] if r.status_code == 200 else f"HTTP {r.status_code}"
            good &= check("Kibana answers with this key", r.status_code == 200, level)
            r = httpx.get(kb + "/api/agent_builder/agents", headers=headers, timeout=20)
            good &= check("Agent Builder API answers", r.status_code == 200, f"HTTP {r.status_code}")
        except httpx.HTTPError as e:
            good &= check("Kibana reachable", False, type(e).__name__)
        print(f"Kibana in the browser: {kb.replace(':443', '')}")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
