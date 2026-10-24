"""Upload assets/pronunciation/atc.json as a Cartesia pronunciation dictionary.

POST https://api.cartesia.ai/pronunciation-dicts/ with `Authorization: Bearer <key>`
and `Cartesia-Version: 2026-08-14` (REST uses a Bearer token; the WebSockets use X-API-Key).
Prints the new dictionary id to put in CARTESIA_PRONUNCIATION_DICT_ID.

Without CARTESIA_API_KEY it prints "skipped: ..." and exits 0.

Run from the repo root: python scripts/upload_pronunciation_dict.py [--name NAME]
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

URL = "https://api.cartesia.ai/pronunciation-dicts/"
VERSION = "2026-08-14"
DICT_PATH = ROOT / "assets" / "pronunciation" / "atc.json"


def main() -> int:
    api_key = os.getenv("CARTESIA_API_KEY")
    if not api_key:
        print("skipped: CARTESIA_API_KEY not set")
        return 0
    name = sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv else "unstep-atc"

    entries = json.loads(DICT_PATH.read_text(encoding="utf-8"))
    items = [{"text": e["text"], "pronunciation": e["pronunciation"],
              **({"case_sensitive": e["case_sensitive"]} if "case_sensitive" in e else {})}
             for e in entries]
    body = json.dumps({"name": name, "description": "Unstep ATC phraseology pronunciations",
                       "items": items}).encode("utf-8")
    req = urllib.request.Request(URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {api_key}",
        "Cartesia-Version": VERSION,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"upload failed: HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
        return 1
    print(f"uploaded {len(items)} entries as {resp.get('name')!r}")
    print(f"CARTESIA_PRONUNCIATION_DICT_ID={resp['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
