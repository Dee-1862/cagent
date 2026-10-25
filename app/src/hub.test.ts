import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Live } from "./hub";

class FakeSocket {
  static all: FakeSocket[] = [];
  static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
  readyState = 0;
  sent: string[] = [];
  onopen?: () => void; onmessage?: (e: { data: string }) => void; onclose?: (e: { code: number }) => void;
  constructor(public url: string) { FakeSocket.all.push(this); }
  open() { this.readyState = 1; this.onopen?.(); }
  send(d: string) { this.sent.push(d); }
  close() { this.readyState = 3; this.onclose?.({ code: 1000 }); }
}

const hub = { http: "http://h", ws: "ws://h", token: "" } as any;

describe("Live.wake (a phone that slept)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.all = [];
    (globalThis as any).WebSocket = FakeSocket;
    (globalThis as any).window = globalThis;
  });
  afterEach(() => vi.useRealTimers());

  it("reconnects at once, same seat, when the socket is closed", () => {
    const live = new Live(hub, "N123AB", () => {}, () => {});
    live.open();
    FakeSocket.all[0].open();
    FakeSocket.all[0].readyState = 3; // died while asleep; its close event may never come
    live.wake();
    expect(FakeSocket.all).toHaveLength(2);
    expect(FakeSocket.all[1].url).toBe("ws://h/live/ws/N123AB");
  });

  it("replaces a socket that says it is open but never answers a ping", () => {
    const live = new Live(hub, "N123AB", () => {}, () => {});
    live.open();
    FakeSocket.all[0].open();
    FakeSocket.all[0].sent = [];
    live.wake();
    expect(FakeSocket.all[0].sent.some((m) => m.includes('"ping"'))).toBe(true);
    vi.advanceTimersByTime(2100);
    expect(FakeSocket.all).toHaveLength(2);
  });

  it("keeps a healthy socket, and does nothing after close()", () => {
    const live = new Live(hub, "N123AB", () => {}, () => {});
    live.open();
    FakeSocket.all[0].open();
    live.wake();
    FakeSocket.all[0].onmessage?.({ data: JSON.stringify({ type: "pong", t0: Date.now(), t1: Date.now() }) });
    vi.advanceTimersByTime(2100);
    expect(FakeSocket.all).toHaveLength(1);
    live.close();
    live.wake();
    expect(FakeSocket.all).toHaveLength(1);
  });
});
