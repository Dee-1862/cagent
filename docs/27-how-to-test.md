# How to test everything, and what each part proves

Checked on 2026-10-25 on a Linux sandbox with no keys: the hub starts offline, the console shows the airport, a headless phone joins and the console shows "1 plane connected" with Plane A on the taxiway.

## 1. On your laptop (no keys, offline, fake speech)

```bash
git fetch && git checkout dev-b/gateway-and-contracts && git pull
pip install -r requirements.txt            # once
cd app && npm install && npm run build && cd ..   # once: builds the pilot app that the hub serves at /pilot/
python -m unstep.live --offline            # or: python scripts/run_demo.py for the scripted flow
```

- **Tower side (Rishit's console):** open `http://127.0.0.1:8765/live/atc/`. Parked airliners at the gates are always there. They are not the planes you fly.
- **Why you may see no moving plane:** a plane you fly appears only after a phone joins. The top right says "0 planes connected" until then.
- **Pilot side (phone, or a narrow browser window):** open `http://127.0.0.1:8765/pilot/` (the path is `/pilot/`, not `/live/pilot/`). Tick the recording box, press "Turn on my radio and join". The console then shows "1 plane connected" and "Plane A · Cessna 1-2-3" near the B1 connector, at the left edge of the default view. Open a second window to join Plane B.
- **Offline limits:** speech is fake, so holding the button does not transcribe. Type into "Say something on the tower radio..." on the console and press Transmit, or use the "Clear Plane A for takeoff" button. Phone captions need Cartesia.

## 2. With real keys (copy `.env.example` to `.env`)

| What to try | Keys | What you should see |
| --- | --- | --- |
| Phones as planes over the internet | Cartesia | `python scripts/demo_public.py` prints a public link and a QR on the console |
| Stepped-on call, card, citation | Cartesia, Elastic | Card at once, FAA paragraph added about 10 s later |
| Moss memory: "what did the tower tell me?" | Moss | Answer in under 1 ms from the plane's own session |
| Restart from disk, flight log survives | Moss | `python scripts/moss_live_check.py` prints `ok` |
| Landing after quiet | Moss, Elastic | `UNSTEP_IDLE_LAND_S=20`: the plane lands, its flight appears in `unstep-flights` and Moss Cloud |
| Where the plane was, in the late explanation | Elastic | Step "Where the plane was: In Taxiway B; 12 m from ... (demo map, not surveyed)" on the trace |
| Agents' MCP path | Elastic | `python scripts/mcp_demo.py` lists the tools (run live by Rishit, R57) |
| Kibana map of airport and planes | Elastic | `python scripts/deploy_elastic.py --only maps`, then Maps in Kibana (uses the saved-objects import API, which works on serverless Kibana; the base map tiles are not available there) |
| Scheduled coach review, 8-hour briefing | Elastic | Only after `--replace`, which needs Rishit's OK; they spend model calls on their own |

## 3. Console on Vercel, compute on Render

`deploy/console/` is a second Vercel project that forwards the console page and everything under `/live/` to the Render hub; the WebSocket goes straight to Render (a Vercel rewrite cannot carry one). Steps are in `deploy/console/README.md` (Root Directory `deploy/console`, project name `cagent-console`). Not yet deployed or tried on Vercel: the pieces are tested here (the hub fills in its own address, 7 tests), the Vercel side is not.

## 4. What is deployed

Nothing from `dev-b` or `rishit` is on Render or Vercel until PR #5 is merged into `master` (it is 106 commits ahead). The sandbox cannot reach the live hosts to check.

## 5. Tests

`python -m pytest -q` (Python) and `cd app && npx vitest run` (pilot app, includes the sleeping-phone reconnect).
