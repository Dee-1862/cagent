// Where the hub (the tower laptop) is, and the live socket to it.
//
// The pilot app can be served by Vercel while the hub runs on a laptop behind a
// tunnel, so the hub address comes from the join link: ?hub=<host or URL>&token=<room token>.

import { bestOffset, Sample, Sync } from "./clock";

export type Hub = { http: string; ws: string; token: string | null };

const STORE = "unstep.hub";

export function hubFromLocation(loc: Location = window.location): Hub | null {
  const q = new URLSearchParams(loc.search);
  let raw = q.get("hub");
  let token = q.get("token");
  if (raw) {
    try { localStorage.setItem(STORE, JSON.stringify({ raw, token })); } catch { /* private mode */ }
  } else {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || "null");
      if (saved?.raw) ({ raw, token } = saved);
    } catch { /* ignore */ }
  }
  if (!raw && !loc.hostname.endsWith(".vercel.app")) raw = loc.origin; // served by the hub itself
  return raw ? parseHub(raw, token) : null;
}

export function parseHub(raw: string, token: string | null = null): Hub {
  let s = raw.trim().replace(/\/+$/, "");
  if (!/^[a-z]+:\/\//i.test(s)) {
    const local = /^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(s);
    s = (local ? "http://" : "https://") + s;
  }
  const http = s.replace(/^ws/i, "http");
  return { http, ws: http.replace(/^http/i, "ws"), token: token || null };
}

export type Seat = { station: string; callsign: string; spoken: string; name: string; frequency: string; live: boolean };

export async function join(hub: Hub): Promise<Seat> {
  const q = hub.token ? `?token=${encodeURIComponent(hub.token)}` : "";
  const r = await fetch(`${hub.http}/live/join${q}`, { method: "POST" });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || `hub answered ${r.status}`);
  return body as Seat;
}

export type Msg = { type: string; [k: string]: any };

/** One live socket with reconnect and clock sync. Hub time = Date.now() + offset. */
export class Live {
  offset = 0;
  sync: Sync | null = null;
  private ws: WebSocket | null = null;
  private samples: Sample[] = [];
  private closed = false;
  private retry = 0;
  private timers: number[] = [];

  constructor(private hub: Hub, private station: string, private on: (m: Msg) => void,
              private onState: (s: "connecting" | "open" | "closed") => void) {}

  now(): number { return Date.now() + this.offset; }

  open(): void {
    this.closed = false;
    this.onState("connecting");
    const q = this.hub.token ? `?token=${encodeURIComponent(this.hub.token)}` : "";
    const ws = new WebSocket(`${this.hub.ws}/live/ws/${encodeURIComponent(this.station)}${q}`);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.onState("open");
      for (let i = 0; i < 8; i++) this.timers.push(window.setTimeout(() => this.ping(), i * 120));
      this.timers.push(window.setInterval(() => this.ping(), 10_000));
    };
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data) as Msg;
      if (m.type === "pong") return this.pong(m);
      if (m.type === "hello" && !this.sync) this.offset = m.now_ms - Date.now(); // rough until pongs arrive
      this.on(m);
    };
    ws.onclose = () => {
      this.timers.forEach((t) => clearTimeout(t));
      this.timers = [];
      this.onState("closed");
      if (!this.closed) window.setTimeout(() => this.open(), Math.min(5000, 500 * 2 ** this.retry++));
    };
  }

  close(): void {
    this.closed = true;
    this.ws?.close();
  }

  send(m: Msg): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(m));
    return true;
  }

  private ping(): void {
    this.send({ type: "ping", t0: Date.now() });
  }

  private pong(m: Msg): void {
    this.samples = [...this.samples.slice(-15), { t0: m.t0, t1: m.t1, t3: Date.now() }];
    this.sync = bestOffset(this.samples);
    if (this.sync) this.offset = this.sync.offset;
  }
}
