"""Load FAA Order JO 7110.65 paragraphs into Elastic for the Compliance agent (W2).

We don't ship the Order's text. Download the chapters you need from faa.gov (the
HTML pages of JO 7110.65, or saved as .txt) into a folder, then:

    python scripts/ingest_faa.py --source data/faa --dry-run   # parse and show what would be indexed
    python scripts/ingest_faa.py --source data/faa             # create unstep-faa and index every paragraph

Each paragraph ("3-7-2. TAXI AND GROUND MOVEMENT OPERATIONS" up to the next one) becomes
one document with id = paragraph number, so the hub can check a cited paragraph exists
(GET unstep-faa/_doc/3-7-2). `text` is a semantic_text field (hybrid search in the
Compliance agent's index search tool) and `body` keeps the same text for BM25. Set
UNSTEP_FAA_INFERENCE_ID to pin the inference endpoint; without it semantic_text uses
the deployment's default endpoint (check that one exists on your cluster before relying on it).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unstep.config import elastic_settings, env  # noqa: E402

INDEX = "unstep-faa"
_PARA = re.compile(r"^\s*(\d{1,2}-\d{1,2}-\d{1,2})\.\s+([A-Z][A-Z0-9 ,/()'\-]{2,})\s*$", re.M)


def to_text(raw: str) -> str:
    """HTML or text to plain lines (tags dropped, entities decoded, blocks on their own lines)."""
    if "<" in raw and ">" in raw:
        raw = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
        raw = re.sub(r"(?i)<\s*(br|/p|/div|/h\d|/li|/tr)\s*/?>", "\n", raw)
        raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw).replace("\xa0", " ")
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines())


def paragraphs(text: str, source: str = "") -> list[dict]:
    """Split the Order into paragraphs by their numbered headings."""
    marks = list(_PARA.finditer(text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = re.sub(r"\n{2,}", "\n", text[m.end():end]).strip()
        if not body:
            continue
        out.append({"paragraph": m.group(1), "title": m.group(2).title().strip(), "text": body[:20_000],
                    "body": body[:20_000], "chapter": m.group(1).split("-")[0], "source": source})
    return out


def load(source: Path) -> list[dict]:
    files = [source] if source.is_file() else sorted(p for p in source.rglob("*") if p.suffix.lower() in (".html", ".htm", ".txt"))
    seen: dict[str, dict] = {}
    for f in files:
        for p in paragraphs(to_text(f.read_text(encoding="utf-8", errors="replace")), f.name):
            seen.setdefault(p["paragraph"], p)  # first occurrence wins
    return list(seen.values())


def mapping(inference_id: str | None) -> dict:
    semantic = {"type": "semantic_text", **({"inference_id": inference_id} if inference_id else {})}
    return {"mappings": {
        "_meta": {"description": "FAA Order JO 7110.65 (Air Traffic Control), one document per paragraph"},
        "properties": {"paragraph": {"type": "keyword"}, "title": {"type": "text"}, "text": semantic,
                       "body": {"type": "text"}, "chapter": {"type": "keyword"}, "source": {"type": "keyword"}}}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--index", default=INDEX)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    docs = load(args.source)
    print(f"{len(docs)} paragraphs from {args.source}")
    for d in docs[:8]:
        print(f"  {d['paragraph']:8} {d['title'][:60]} ({len(d['text'])} chars)")
    if args.dry_run or not docs:
        return 0 if docs else 1
    settings = elastic_settings()
    if not settings:
        print("Need ELASTIC_URL and ELASTIC_API_KEY.", file=sys.stderr)
        return 1
    url, key = settings
    with httpx.Client(headers={"Authorization": f"ApiKey {key}"}, timeout=120) as client:
        r = client.put(f"{url.rstrip('/')}/{args.index}", json=mapping(env("UNSTEP_FAA_INFERENCE_ID")))
        if not (r.is_success or "resource_already_exists" in r.text):
            print(f"FAIL create {args.index}: {r.status_code} {r.text[:300]}", file=sys.stderr)
            return 1
        failed = 0
        for i in range(0, len(docs), 50):  # small batches: semantic_text embeds at index time
            batch = docs[i:i + 50]
            body = "".join(json.dumps({"index": {"_index": args.index, "_id": d["paragraph"]}}) + "\n"
                           + json.dumps(d) + "\n" for d in batch)
            r = client.post(f"{url.rstrip('/')}/_bulk", content=body, headers={"Content-Type": "application/x-ndjson"})
            items = r.json().get("items", []) if r.is_success else []
            failed += len(batch) if not r.is_success else sum("error" in it["index"] for it in items)
        print(f"indexed {len(docs) - failed} of {len(docs)} into {args.index}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
