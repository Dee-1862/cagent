# Hosting Unstep on a website that needs a passcode

How to put the hub on Render (and the pilot app and console on Vercel) so that only people with the passcode can use it. With no passcode set, nothing changes: a local run stays open.

| Field | Value |
| --- | --- |
| Status | v0.1, 2026-10-25 |
| Code | `unstep/live/passcode.py` (the gate), `tests/test_passcode.py` |
| Related | [render.yaml](../render.yaml), [deploy/console/](../deploy/console/), [11-live-demo.md](11-live-demo.md) |

## 1. Two codes, two jobs

| Setting | Who needs it | What it does |
| --- | --- | --- |
| `UNSTEP_ATC_PASSWORD` (the **tower passcode**) | The person running the tower | The tower pages and their endpoints ask for it (HTTP Basic: any user name, this as the password). The tower socket asks for it again inside the page |
| `UNSTEP_GATEWAY_TOKEN` (the **room code**) | Pilots, and anything that joins a plane | Joining a plane and every pilot socket need it. The tower's QR code carries it, so a pilot who scans the QR is in without typing |

Set both on the host. Pilots never see the tower passcode. Strangers need one of them for everything that matters.

## 2. Set it up

**On Render** (Environment tab of the `unstep` service, the values marked "sync: false" in `render.yaml`):
1. `UNSTEP_ATC_PASSWORD`: a long passphrase (it has no lockout, so length is the defence).
2. `UNSTEP_GATEWAY_TOKEN`: a different random string.
3. `UNSTEP_PUBLIC_URL`: already set in `render.yaml`.
4. The service keys (`CARTESIA_API_KEY`, `MOSS_*`, `ELASTIC_*`) as before. Never put any of these in git.

**On Vercel** (optional: the pilot app and the console in front of Render): set `VITE_UNSTEP_HUB` to the Render address and `VITE_UNSTEP_TOKEN` to the room code (see `render.yaml` and `deploy/console/README.md`). The console on Vercel proxies `/live/*` to Render, and the browser's passcode prompt works through the proxy.

**On a laptop with a public tunnel:** `python scripts/demo_public.py` now refuses to start unless `UNSTEP_ATC_PASSWORD` is set (pass `--open` to publish without one, knowingly).

## 3. What is protected and what is open

| Path | Needs |
| --- | --- |
| `/live/atc/` (the 3D tower console), `/live/record/`, `/` (gateway dashboard), `/demo/` | the tower passcode |
| `/live/pilot-link`, `/live/addresses`, `/live/pi-join`, `/live/qr.svg` | the tower passcode (the join link carries the room code) |
| `/live/stats`, `/live/ask-audit`, `/live/reports`, `/live/reports/run`, `/live/flightlog`, `/live/clearance-context/*`, `/live/geo/*` | the tower passcode (they read the audit trail or spend Elastic) |
| `/live/join` and the pilot sockets | the room code |
| the tower socket | the tower passcode, sent inside the socket |
| `/pilot/` (the phone app), `/live/static/*` (scripts, models), `/live/stations`, `/health` | nothing: static files, plane names, and the host's health check |

Before this change, a hub with a room code but no tower passcode showed the room code in the console page and in `/live/pilot-link` to anyone who asked. The hub now prints a warning at start-up when it is open to a network without `UNSTEP_ATC_PASSWORD`.

## 4. Check it yourself (no secrets in the commands)

```
curl -i https://<your host>/live/atc/            # expect 401 and WWW-Authenticate: Basic
curl -i https://<your host>/live/pilot-link      # expect 401
curl -i https://<your host>/health               # expect 200
curl -i -X POST https://<your host>/live/join    # expect 403 (needs the room code)
curl -u any:<tower passcode> https://<your host>/live/pilot-link   # expect 200 and a link
```

## 5. Known limits

- **Two prompts.** The browser asks for the tower passcode when it opens the console, then the console's own "Control Tower access" box asks for the same passcode for its socket. Removing the second needs a change in `atc.js`, which is Rishit's file.
- **No room-code box on the pilot join screen.** A pilot gets the code from the QR or the link. Someone who opens the bare site gets "wrong room token". A code box is a small follow-up in the pilot app.
- **No lockout or rate limit** on either code. Use long values.
- **Free Render sleeps** and takes about a minute to wake; `.github/workflows/keep-warm.yml` pings `/health` every 10 minutes once it is on master.
- **The hub is one room.** Anyone with the room code shares it.
