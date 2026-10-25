# Evidence for the README tables

Every number in the README's Cartesia, Moss and Elastic tables comes from a file here, measured on 2026-10-25 on one laptop against our own cloud projects. `python scripts/readme_tables.py` reads these files and writes the tables, so the README cannot say something the data does not.

| File | What it is | Made by |
| --- | --- | --- |
| `cartesia-2026-10-25.json` | The summary the Cartesia table reads | `scripts/evidence_cartesia.py` |
| `cartesia-bench-2026-10-25.json` | 200 lines, synthetic speech through a simulated VHF channel at 10 dB noise, three voices, with and without key terms (live, seed 7, every line and what was heard) | `scripts/eval_bench.py --live --n 200 --conditions clean,radio-10 --stepped 0` |
| `cartesia-repro-2026-10-25.json` | Speech-to-text finalize time, streaming against whole-clip, 30 runs each | `scripts/cartesia_repro.py --runs 30 --only manual_pacing` |
| `cartesia-live-check-2026-10-25.json` | Sonic first audio (30 requests) and caption timing (5 runs) | `scripts/cartesia_live_check.py --only tts caption` |
| `moss-2026-10-25.json` | Six real Moss sessions, 300 timed reads, search scores | `scripts/evidence_moss.py` |
| `moss-live-check-2026-10-25.txt` | Disk restore, cloud sync, the plane's answers | `scripts/moss_live_check.py` |
| `elastic-2026-10-25.json` | Agents, tools and workflows counted from Kibana; citation, geo and ES\|QL timings; stored document counts; MCP tools | `scripts/evidence_elastic.py` |
| `elastic-percolator-2026-10-25.txt` | Rule matching at 7, 100, 1,000 and 5,000 rules | `scripts/rule_latency.py --elastic` |

## How to read the numbers

- **Speech is synthetic.** Cartesia voices, sent through our simulated radio channel. The key-term comparison is fair (same audio with and without), but it is not an accuracy figure for real controllers.
- **Sample sizes** are in every file and in the README cells. The key-term lines: 200, of which 136 name a runway.
- **"Elastic's own time"** is the server's `took`. The round trip adds the network from the laptop, about 85 to 90 ms.
- **Moss's own time** is what the SDK reports. Our wall clock around a text query is about 5 ms, because it includes embedding the query.
- **One voice is harder:** with key terms the pilot voice gets callsigns right 80.6% of the time, the tower and helicopter voices 100%.
- **Not measured today:** the Kibana map (the API refused the count), the scheduled workflows' clock, anything on real radio recordings.
- A failed first attempt at the Cartesia timings (the laptop changed wifi and DNS dropped) is not in the data; the runs here are the clean re-run.
