// Where the hub (the tower laptop) is, and the live socket to it.
//
// The pilot app can be served by Vercel while the hub runs on a laptop behind a
// tunnel, so the hub address comes from the join link: ?hub=<host or URL>&token=<room token>.

import { bestOffset, Sample, Sync } from "./clock";

export type Hub = { http: string; ws: string; token: string | null };

const STORE = "unstep.hub";
// The public demo hub (render.yaml). Not a secret: the room code, when set, is separate.
const PUBLIC_HUB = "https://unstep.onrender.com";

export function hubFromLocation(loc: Location = window.location, dev: boolean = import.meta.env.DEV): Hub | null {
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
  // A hosted build (Vercel) can bake in its hub: VITE_UNSTEP_HUB=https://<service>.onrender.com.
  const built = (import.meta.env.VITE_UNSTEP_HUB as string | undefined)
    || (loc.hostname.endsWith(".vercel.app") ? PUBLIC_HUB : undefined);
  const servedByHub = loc.pathname.startsWith("/pilot"); // the hub mounts this app at /pilot/
  if (!raw && servedByHub) raw = loc.origin;
  if (!raw && built) {
    raw = built;
    token = token || (import.meta.env.VITE_UNSTEP_TOKEN as string | undefined) || null;
  }
  // `npm run dev` serves this app on :5173, which is not the hub: use the hub on this machine (port 8765).
  if (!raw && dev && loc.port === "5173") raw = `${loc.protocol}//${loc.hostname}:8765`;
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

export type Seat = { station: string; callsign: string; spoken: string; name: string; frequency: string; live: boolean; language?: string | null };

export async function join(hub: Hub, language?: string | null, speaker?: { name: string; consent: boolean }): Promise<Seat> {
  const params = new URLSearchParams();
  if (hub.token) params.set("token", hub.token);
  if (language) params.set("language", language);
  if (speaker?.name) { params.set("name", speaker.name); params.set("consent", speaker.consent ? "1" : "0"); }
  const q = params.toString() ? `?${params}` : "";
  const r = await fetch(`${hub.http}/live/join${q}`, { method: "POST" });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(body.error || `hub answered ${r.status}`), { full: Boolean(body.full) });
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
  private reopen: number | null = null;
  private lastPong = 0;
  /** Close code (4003 = the hub refused: unknown seat, wrong room code or origin) and retry count. */
  onClose?: (code: number, attempt: number) => void;

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
    ws.onclose = (e) => {
      if (this.ws !== ws) return; // an old socket we already replaced
      this.timers.forEach((t) => clearTimeout(t));
      this.timers = [];
      this.onState("closed");
      this.onClose?.(e.code, this.retry);
      if (!this.closed) this.reopen = window.setTimeout(() => this.open(), Math.min(5000, 500 * 2 ** this.retry++));
    };
  }

  /** The phone woke up (tab visible again, network back). A socket that slept is often dead without saying so:
   * if it is not open, reconnect now with no backoff; if it claims to be open, ping it and replace it when no
   * pong comes back in 2 s. The same station id is reused, so the same seat is reclaimed. */
  wake(): void {
    if (this.closed) return;
    const ws = this.ws;
    if (ws && ws.readyState === WebSocket.CONNECTING) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) return this.reconnect();
    const before = this.lastPong;
    this.ping();
    window.setTimeout(() => { if (!this.closed && this.ws === ws && this.lastPong === before) this.reconnect(); }, 2000);
  }

  private reconnect(): void {
    if (this.reopen !== null) clearTimeout(this.reopen);
    this.reopen = null;
    this.timers.forEach((t) => clearTimeout(t));
    this.timers = [];
    const old = this.ws;
    this.retry = 0;
    this.open(); // sets this.ws to the new socket first, so the old one's close event is ignored
    try { old?.close(); } catch { /* already dead */ }
  }

  close(): void {
    this.closed = true;
    if (this.reopen !== null) clearTimeout(this.reopen);
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
    this.lastPong = Date.now();
    this.samples = [...this.samples.slice(-15), { t0: m.t0, t1: m.t1, t3: Date.now() }];
    this.sync = bestOffset(this.samples);
    if (this.sync) this.offset = this.sync.offset;
  }
}
