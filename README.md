# Unstep

No ATC instruction lost or misheard. See [docs/01-prd.md](docs/01-prd.md).

> Work in progress. This README covers running the current skeleton. The full README (setup, Cartesia features used, known limitations) is shared task S2.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill in keys, never commit .env
```

## Run the M2 first wire

Four terminals, from the repo root:

```bash
uvicorn unstep.gateway.server:app --port 8765      # gateway, dashboard at http://127.0.0.1:8765
python -m unstep.ground.mock_agents                # mock ground agents (Dev B replaces with Elastic, B5)
python -m unstep.ground.auto_approver              # optional: approves by "voice" automatically
python -m unstep.cockpit.mock_cockpit --runs 10    # mock cockpit (Dev A replaces with real audio)
```

Without the auto approver, open the dashboard and click Approve or Reject.

## Tests

```bash
python -m pytest -q
```

## Layout

| Path | What | Owner |
| --- | --- | --- |
| `unstep/contracts.py` | Shared message contracts (Work Split section 3) | Both |
| `unstep/clock.py` | One clock, epoch ms (FR-17) | Both |
| `unstep/scenario.py` | Demo scenario data used by examples, mocks and tests | Both |
| `contracts/examples/` | One JSON example per contract (`python scripts/export_contract_examples.py`) | Both |
| `unstep/gateway/` | WebSocket gateway and event sink | Dev B |
| `unstep/ground/` | Mock agents and auto approver | Dev B |
| `web/dashboard.html` | Mock controller dashboard | Dev B |
| `unstep/cockpit/` | Cockpit edge | Dev A |
| `docs/` | PRD, architecture, work split and the rest | Both |

## Message format

Every message is an envelope: `{"type": "AnomalyEvent", "ts": 1792800000000, "data": {...}}`. Clients connect to `ws://<gateway>/ws/<role>` where role is one of `cockpit`, `tower`, `agents`, `dashboard`, `controller_voice`, `monitor`. Routing is in `unstep/gateway/server.py` (`ROUTES`).
