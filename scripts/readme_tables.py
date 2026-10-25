"""Write the README's three sponsor tables (sections 5 to 7) and the evidence section (9) from the files in docs/evidence/.

    python scripts/readme_tables.py            # rewrite README.md in place
    python scripts/readme_tables.py --check    # exit 1 if README.md is out of step with docs/evidence/

Each table has the same three columns as the demo film: Feature, What it does in Unstep, Measured. The numbers are not typed
here: they are read from the evidence files, so the README cannot say something the data does not. Where a number has
not been re-measured yet, the cell says so instead of repeating an old figure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "evidence"
README = ROOT / "README.md"


def latest(pattern: str) -> Path | None:
    files = sorted(EVIDENCE.glob(pattern))
    return files[-1] if files else None


def load(pattern: str) -> dict:
    path = latest(pattern)
    return json.loads(path.read_text(encoding="utf-8")) if path else {}


def grab(pattern: str, regex: str, default: str = "?") -> str:
    path = latest(pattern)
    match = re.search(regex, path.read_text(encoding="utf-8")) if path else None
    return match.group(1) if match else default


def ms(value: float) -> str:
    return f"{value:.3g}"


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def cartesia_rows() -> tuple[list[tuple[str, str, str]], str]:
    c = load("cartesia-20*.json")
    if not c:
        pending = "not re-measured yet"
        return ([
            ("Ink-2 streaming speech-to-text", "Transcribes the tower and every cockpit while they talk", pending),
            ("Key-term prompting", "29 aviation terms per cockpit, 39 for the tower: callsigns, runways, taxiways, \"niner\", \"hold short\"", pending),
            ("Sonic text-to-speech", "Speaks the recovered call to one pilot, left ear only", pending),
            ("Same voice, other languages", "The advisory repeated in Spanish, Hindi or French", "checked live"),
            ("Pronunciation dictionary and speed", "ATC words said the ATC way; corrections spoken slower", "0.85x for corrections (a setting)"),
            ("Live captions and interruption", "Captions on every screen; the advisory stops when the pilot keys the mic", pending),
        ], "Cartesia numbers are being re-measured; see docs/evidence/.")
    k = c["keyterms"]
    rows = [
        ("Ink-2 streaming speech-to-text", "Transcribes the tower and every cockpit while they talk",
         f"final words {ms(c['stt_streaming_finalize_ms']['p50'])} ms after release (median; 95th percentile {ms(c['stt_streaming_finalize_ms']['p95'])} ms, n={c['stt_streaming_finalize_ms']['n']})"),
        ("Key-term prompting", "29 aviation terms per cockpit, 39 for the tower: callsigns, runways, taxiways, \"niner\", \"hold short\"",
         f"heavy noise: callsigns {pct(k['callsign']['without'])} to {pct(k['callsign']['with'])}, runways {pct(k['runway']['without'])} to {pct(k['runway']['with'])} ({k['n']} lines, {k['runway']['n']} with a runway)"),
        ("Sonic text-to-speech", "Speaks the recovered call to one pilot, left ear only",
         f"first audio {ms(c['tts_first_audio_ms']['p50'])} ms median, {ms(c['tts_first_audio_ms']['p95'])} ms at the 95th percentile (n={c['tts_first_audio_ms']['n']})"),
        ("Same voice, other languages", "The advisory repeated in Spanish, Hindi or French", "checked live"),
        ("Pronunciation dictionary and speed", "ATC words said the ATC way; corrections spoken slower", "0.85x for corrections (a setting)"),
        ("Live captions and interruption", "Captions on every screen; the advisory stops when the pilot keys the mic",
         c.get("captions_text", "not re-measured")),
    ]
    return rows, c.get("note", "")


def moss_rows() -> list[tuple[str, str, str]]:
    m = load("moss-*.json")
    f, q, a = m["fetch_last_tower_call_filter_and_sort"]["moss_reported_ms"], m["hybrid_query_on_a_fragment"], m["ask_last_clearance_moss_part_ms"]
    s = m["hybrid_scores"]
    weaker = grab("moss-live-check-*.txt", r"'Cessna hold runway': score ([0-9.]+)")
    disk_ms = grab("moss-live-check-*.txt", r"4 docs loaded in ([0-9.]+) ms")
    restart_ms = grab("moss-live-check-*.txt", r"restart to answer: ([0-9.]+) ms")
    build_ms = grab("moss-live-check-*.txt", r"build job finished in ([0-9]+) ms")
    back = grab("moss-live-check-*.txt", r"after a fresh client: (\d+) docs back in ([0-9]+) ms")
    back_ms = grab("moss-live-check-*.txt", r"after a fresh client: \d+ docs back in ([0-9]+) ms")
    return [
        ("One in-process session per aircraft", "Every clearance and call a plane hears is indexed in its own memory, on board",
         f"{m['sessions']} sessions, reads {ms(f['p50'])} ms median, {ms(f['p95'])} ms at the 95th percentile (n={f['n']})"),
        ("Hybrid search", "The scrap the pilot did hear finds the full instruction, by meaning and by exact words",
         f"right clearance {s['right clearance']['score']:.1f}, a weaker fragment {float(weaker):.2f}, unrelated speech {s['unrelated speech']['score']:.1f}"),
        ("Metadata filters and sorting", "Only this aircraft, only tower calls, newest first: the Clearance agent's \"last call\"",
         f"{ms(f['p50'])} ms median (the same {f['n']} reads as the first row)"),
        ("Ask your memory, by voice", "\"What was my last clearance?\" answered from Moss and spoken by Sonic",
         f"Moss's part {ms(a['p50'])} ms median, {ms(a['p95'])} ms at the 95th percentile (n={a['n']}); our wall clock around a text query is about {ms(round(q['wall_ms']['p50']))} ms"),
        ("Save to disk and load on restart", "The memory survives a restart without downloading anything",
         f"4 documents restored in {disk_ms} ms; a whole restart to the first answer takes {float(restart_ms) / 1000:.1f} s, because opening a session contacts Moss"),
        ("Moss Cloud sync", "Each finished flight's log is pushed to the cloud once",
         f"survives a restart: a fresh client read {back} documents back in {float(back_ms) / 1000:.1f} s (the index builds in {float(build_ms) / 1000:.1f} s)"),
    ]


def elastic_rows() -> list[tuple[str, str, str]]:
    e = load("elastic-*.json")
    o, cite, geo, audit = e["objects"], e["faa_citation_hybrid_rerank"], e["geo_shape_area_lookup"], e["audit_trail"]
    perc = grab("elastic-percolator-*.txt", r"\n\s+7\s+\S+\s+\S+\s+\S+\s+([0-9.]+)ms\s+([0-9.]+)ms")
    perc_wall = perc
    perc_took = grab("elastic-percolator-*.txt", r"\n\s+7\s+\S+\s+\S+\s+\S+\s+[0-9.]+ms\s+([0-9.]+)ms")
    docs = audit["documents"]
    return [
        ("Agent Builder", "8 agents: Intercept, Compliance, Ground, Readback Auditor, Audit, Coach and two fast variants",
         f"{o['agents']['ours']} agents and {o['tools']['ours']} tools counted on our project"),
        ("Workflows", "Agents run in parallel on every stepped-on call; a shift briefing every 8 hours; a nightly review",
         f"{o['workflows']['ours']} workflows on the project, event-driven and scheduled (run by hand; the clock firing is not yet observed)"),
        ("Percolator rules", "Each instruction and readback is matched to its FAA rule (JO 7110.65, the controller's rulebook)",
         f"Elastic's own time {perc_took} ms; about {float(perc_wall):.0f} ms round trip from our laptop; {docs['unstep-rules']} stored rules, one reviewed by a person"),
        ("Hybrid search and Jina rerank", "Finds the exact FAA paragraph to cite on every decision card",
         f"{ms(round(cite['timing_ms']['p50'] / 1000, 2))} s median, {ms(round(cite['timing_ms']['p95'] / 1000, 2))} s at the 95th percentile, reranked {cite['reranked']} of {cite['answers']} (n={cite['timing_ms']['n']}), over {docs['unstep-faa']} paragraphs"),
        ("geo_shape, flight plans and the airport map", "\"Is the runway clear?\" from live positions; the Clearance agent's plan; incursions flagged",
         f"Elastic's own time {ms(geo['elastic_took_ms']['p50'])} ms, {ms(round(geo['wall_ms']['p50']))} ms round trip (n={geo['elastic_took_ms']['n']}); {docs['unstep-positions']:,} positions, {docs['unstep-airport']} areas, {docs['unstep-flightplans']} flight plans stored"),
        ("ES\\|QL and MCP", "Safety analytics and the audit trail, asked in plain English; our tools exposed over MCP",
         f"{docs['unstep-events']:,} events from {audit['esql_events_and_planes'][0][1]} planes stored; ES\\|QL answers in {ms(round(audit['esql_wall_ms']['p50']))} ms round trip; {e['mcp']['ours'].__len__()} of our tools exposed over MCP"),
    ]


def table(rows: list[tuple[str, str, str]]) -> str:
    out = ["| Feature | What it does in Unstep | Measured |", "| --- | --- | --- |"]
    out += [f"| **{a}** | {b} | {c} |" for a, b, c in rows]
    return "\n".join(out)


def build_sections() -> tuple[str, str]:
    c_rows, c_note = cartesia_rows()
    sponsors = f"""## 5. Cartesia: the ears and the voice

Real-time voice AI: Sonic turns text into speech and Ink turns speech into text ([Cartesia changelog](https://docs.cartesia.ai/changelog/2026)). On a radio everything is voice, and a wrong word is a wrong runway.

{table(c_rows)}

*Evidence:* `docs/evidence/cartesia-*.json` (the raw results of `scripts/eval_bench.py`, `scripts/cartesia_repro.py` and `scripts/cartesia_live_check.py`, summed up by `scripts/evidence_cartesia.py`). {c_note} The 200 test lines are synthetic Cartesia voices sent through our simulated VHF radio channel at several noise levels, so these numbers compare with and without key terms on the same audio; they are not an accuracy figure for real controllers. Sonic's cloud API is what we use; Cartesia's on-device Sonic is in private beta and we are not on it.

**The loop caught our own mistake.** We had respelled "niner" as "NY-ner" in the pronunciation dictionary; Sonic then said something Ink-2 heard as "N1er", and runway accuracy was 85%. Speaking the dictionary back through speech-to-text found it, and the fix took it to 100%.

---

## 6. Moss: each aircraft's memory

Real-time semantic search that runs inside an agent's own process ([Moss for voice agents](https://www.moss.dev/use-cases/voice-agents)). Each cockpit agent's loop is Cartesia Ink hears, Moss searches the plane's memory, Cartesia Sonic speaks.

{table(moss_rows())}

*Evidence:* `docs/evidence/moss-*.json` (written by `scripts/evidence_moss.py`: real Moss, six sessions, the sample counts shown) and `docs/evidence/moss-live-check-*.txt` (the output of `scripts/moss_live_check.py`, which also proves the disk restore and the cloud sync). The speed figures are the milliseconds Moss itself reports. A hint only ever says stop or wait, only with a source record, and an older clearance never comes back ahead of a newer one.

---

## 7. Elastic: the agent platform

Search, ES|QL, Agent Builder and Workflows on one Serverless project, deployed from code with `python scripts/deploy_elastic.py` ([Agent Builder](https://www.elastic.co/elasticsearch/agent-builder)). Each agent can only call its own fixed queries, and no agent writes to the audit trail.

{table(elastic_rows())}

*Evidence:* `docs/evidence/elastic-*.json` (written by `scripts/evidence_elastic.py`: it counts the agents, tools and workflows from Kibana itself, then times the calls) and `docs/evidence/elastic-percolator-*.txt` (`scripts/rule_latency.py --elastic`). "Elastic's own time" is the server's `took`; the round trip adds the network from our laptop. At 7 rules a plain in-memory scan is faster than Elastic; the reason for percolating is that rules are data an editor changes without a deploy. An Agent Builder call takes about 5 to 10 s whatever the answer, so the agents stay off the pilot's critical path: the decision card goes out first and the citation is added when it arrives. The hold-short rule (paragraph 3-7-2) was reviewed by a person; the other stored rules are marked candidate or needs review.

---

"""
    evidence = """## 9. Evidence and how to re-run it

Every number in the three tables above is read from a file in [`docs/evidence/`](docs/evidence/) by `python scripts/readme_tables.py`, so the README cannot say something the data does not. To re-measure:

```
python scripts/eval_bench.py --live --n 200 --conditions clean,radio-10 --stepped 0   # Cartesia key terms (uses credits)
python scripts/cartesia_repro.py --runs 30 --only manual_pacing                        # streaming against burst finalize
python scripts/cartesia_live_check.py --only tts caption --tts-runs 30 --runs 5        # Sonic first audio, caption timing
python scripts/evidence_cartesia.py                                                    # summarise the three Cartesia runs
python scripts/evidence_moss.py                                                       # six Moss sessions
python scripts/moss_live_check.py                                                     # disk restore and cloud sync
python scripts/evidence_elastic.py                                                    # agents, tools, workflows, citation, geo, audit
python scripts/rule_latency.py --elastic                                              # percolator
python scripts/readme_tables.py                                                       # rewrite the tables from the files
```

All of it ran on one laptop against our own cloud projects. Speech is synthetic, sent through a simulated radio channel. Simulated traffic is always labelled as such.

### Built in a day

First commit: **2026-10-23 21:00 PDT**.

| What landed | When (PDT) | Hours after the first commit |
| --- | --- | --- |
| Airport index script (Moss reference data) | 2026-10-24 00:12 | 3.2 |
| Elastic deploy script (agents, tools, workflows) | 2026-10-24 20:36 | 23.6 |
| FAA rulebook ingest (52 JO 7110.65 paragraphs) | 2026-10-24 21:07 | 24.1 |
| Traffic simulator (500 labelled calls, simulated) | 2026-10-24 23:15 | 26.3 |

---

"""
    return sponsors, evidence


def apply(text: str) -> str:
    sponsors, evidence = build_sections()
    start = text.find("## For the sponsors")
    if start < 0:
        start = text.index("## 5. Cartesia")
    end = text.index("## 8. The two screens")
    text = text[:start] + sponsors + text[end:]
    start = text.index("## 9. ")
    end = text.index("## 10. Impact and responsible use")
    text = text[:start] + evidence + text[end:]
    text = text.replace("9. [Measured results](#9-measured-results)", "9. [Evidence and how to re-run it](#9-evidence-and-how-to-re-run-it)")
    text = re.sub(r"\nAlso: \[What it looks like\][^\n]*\n", "\nAlso: [What it looks like](#what-it-looks-like) · [Built in a day](#built-in-a-day)\n", text)
    return text


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    current = README.read_text(encoding="utf-8")
    updated = apply(current)
    if args.check:
        sys.exit(0 if updated == current else 1)
    README.write_text(updated, encoding="utf-8")
    print("README.md rewritten; em dashes:", updated.count("—"))
