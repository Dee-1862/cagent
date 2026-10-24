"""Pre-flight airport ingestion, the sole writer of persistent airport knowledge.

Run: python scripts/ingest_airport.py
Uses MOSS_PROJECT_ID/MOSS_PROJECT_KEY from the process environment.
The bundled seed describes only the fictional KUNS airport.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from unstep.cockpit.memory import airport_index
from unstep.cockpit.seed import AIRPORT_ICAO, airport_docs


async def ingest(client) -> str:
    from moss import DocumentInfo, MutationOptions

    index = airport_index(AIRPORT_ICAO)
    docs = [DocumentInfo(id=d.id, text=d.text,
                         metadata={k: str(v) for k, v in d.metadata.items()})
            for d in airport_docs()]
    indexes = await client.list_indexes()
    if not any(info.name == index for info in indexes):
        await client.create_index(index, docs)
    else:
        # Stable seed ids make repeated ingestion idempotent without replacing
        # unrelated airport records. No cockpit or session push writes this index.
        await client.add_docs(index, docs, MutationOptions(upsert=True))
    return index


async def main() -> int:
    pid, key = os.getenv("MOSS_PROJECT_ID"), os.getenv("MOSS_PROJECT_KEY")
    if not pid or not key:
        print("skipped: MOSS_PROJECT_ID/MOSS_PROJECT_KEY not set")
        return 0
    from moss import MossClient

    try:
        index = await ingest(MossClient(pid, key))
    except Exception:
        print("Airport ingestion failed; check credentials, connectivity and index status.")
        return 1
    print(f"ingested {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
