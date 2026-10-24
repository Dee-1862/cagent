import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { audio, chirp, keepAwake, playWav } from "./audio";
import { Hub, hubFromLocation, join, Live, Msg, parseHub, Seat } from "./hub";
import { Mic } from "./mic";
import { ASK_LINES, sayLines } from "./phrases";

type Station = { id: string; kind: string; label: string; callsign?: string; spoken?: string; name?: string };
type Line = { ts: number; party: string; text: string; latency: Record<string, number> };
type Trace = { event_id: string; callsign: string; status: string; readbacks: { readback_text: string; match: boolean }[] };
type Alert = { stations: string[]; uplink_ms: number; at: number };

const PLANE_COLORS: Record<string, string> = { A: "#2dd4bf", B: "#fb923c", C: "#a78bfa", D: "#f472b6", E: "#facc15", F: "#60a5fa" };
const TAIL_MS = 250; // keep recording briefly after release so the last word isn't clipped

const mic = new Mic();

export default function App() {
  const [hub, setHub] = useState<Hub | null>(() => hubFromLocation());
  // Hash routes (#/fly/N789PA) work on Vercel and under /pilot/ on the hub alike.
  const seatInHash = () => window.location.hash.match(/^#\/fly\/([A-Za-z0-9]+)/)?.[1] ?? null;
  const [station, setStation] = useState<string | null>(seatInHash);
  useEffect(() => {
    const on = () => setStation(seatInHash());
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);

  if (!hub) return <HubPrompt onHub={setHub} />;
  if (!station) return <Join hub={hub} onSeat={(s) => { location.hash = `/fly/${s.station}`; }} />;
  return <Fly hub={hub} station={station} onLeave={() => { location.hash = ""; }} />;
}

// ------------------------------------------------------------ hub and join

function HubPrompt({ onHub }: { onHub: (h: Hub) => void }) {
  const [raw, setRaw] = useState("");
  return (
    <main className="join">
      <h1>Unstep <span>pilot</span></h1>
      <p className="lead">Scan the QR code on the tower screen. Or paste the tower's address:</p>
      <input value={raw} onChange={(e) => setRaw(e.target.value)} placeholder="abc.trycloudflare.com" autoCapitalize="off" />
      <button className="big" disabled={!raw.trim()} onClick={() => onHub(parseHub(raw))}>Connect</button>
    </main>
  );
}

function Join({ hub, onSeat }: { hub: Hub; onSeat: (s: Seat) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [room, setRoom] = useState<{ live: boolean; stations: Station[]; connected: Record<string, number> } | null>(null);

  useEffect(() => {
    let stop = false;
    const load = () => fetch(`${hub.http}/live/stations`).then((r) => r.json()).then((d) => !stop && setRoom(d))
      .catch(() => !stop && setError("Can't reach the tower. Is the hub running and the link right?"));
    load();
    const t = setInterval(load, 3000);
    return () => { stop = true; clearInterval(t); };
  }, [hub]);

  // One tap does everything a browser only allows inside a user gesture.
  const go = async () => {
    setBusy(true);
    setError(null);
    audio();
    chirp(880, 60);
    await mic.enable();
    await keepAwake();
    try {
      onSeat(await join(hub));
    } catch (e) {
      setError(String((e as Error).message));
      setBusy(false);
    }
  };

  const planes = room?.stations.filter((s) => s.kind === "aircraft") ?? [];
  const flying = planes.filter((p) => (room?.connected[p.id] ?? 0) > 0).length;
  return (
    <main className="join">
      <h1>Unstep <span>pilot</span></h1>
      <p className="lead">You are about to fly a plane at a pretend airport. Everyone shares one radio, like real pilots.
        If two people talk at once, the call gets <b>stepped on</b> and nobody knows. Unstep catches it.</p>
      <button className="big" onClick={go} disabled={busy || !room}>{busy ? "Getting your plane..." : "Turn on my radio and join"}</button>
      {error && <p className="error">{error}</p>}
      <p className="small">{room ? `${flying} of ${planes.length} planes flying · ${room.live ? "live voice" : "offline voice"}` : "Looking for the tower..."}</p>
      {!Mic.available() && <p className="small warn">This page isn't on https, so your mic is off. You can still talk with the tap-to-say lines.</p>}
    </main>
  );
}

// ------------------------------------------------------------ flying

function Fly({ hub, station, onLeave }: { hub: Hub; station: string; onLeave: () => void }) {
  const [conn, setConn] = useState<"connecting" | "open" | "closed">("connecting");
  const [stations, setStations] = useState<Station[]>([]);
  const [keyed, setKeyed] = useState<Record<string, number>>({});
  const [onAir, setOnAir] = useState(false);
  const [alert, setAlert] = useState<Alert | null>(null);
  const [ear, setEar] = useState<Line | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [uplink, setUplink] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  const [ask, setAsk] = useState("");
  const [, tick] = useState(0);
  const live = useRef<Live | null>(null);
  const earAudio = useRef<string | null>(null);
  const pressAt = useRef(0);
  const releaseTimer = useRef<number | null>(null);

  const me = stations.find((s) => s.id === station);
  const nameOf = useCallback((id: string) => (id === "atc" ? "Tower" : stations.find((s) => s.id === id)?.name ?? id), [stations]);

  const say = (text: string) => { setToast(text); setTimeout(() => setToast(null), 4000); };

  useEffect(() => {
    const l = new Live(hub, station, (m: Msg) => {
      switch (m.type) {
        case "hello":
          setStations(m.stations);
          setKeyed(m.keyed || {});
          setTrace([...m.traces].reverse().find((t: Trace) => t.callsign === station) ?? null);
          return;
        case "stations": return setStations(m.stations);
        case "keyed":
          setKeyed(m.keyed);
          if (m.station === station && m.down && m.keyed[station]) setUplink(m.ts - m.keyed[station]);
          return;
        case "stepon_live":
          setAlert({ stations: m.stations, uplink_ms: m.uplink_ms, at: Date.now() });
          if (m.stations.includes(station)) navigator.vibrate?.([60, 40, 60]);
          return;
        case "onair": return void playWav(m.audio);
        case "advisory_audio":
          earAudio.current = m.audio;
          return void playWav(m.audio);
        case "cockpit_line": {
          const line = m as unknown as Line;
          setLines((ls) => [...ls.slice(-40), line]);
          if (line.party === "PILOT EAR") setEar(line);
          return;
        }
        case "trace":
          if (m.trace.callsign === station) setTrace(m.trace);
          return;
        case "status": return void say(m.text);
      }
    }, setConn);
    live.current = l;
    l.open();
    const t = setInterval(() => tick((n) => n + 1), 500);
    return () => { l.close(); clearInterval(t); };
  }, [hub, station]);

  // ---- push to talk

  const down = () => {
    if (onAir) return;
    if (releaseTimer.current) { clearTimeout(releaseTimer.current); releaseTimer.current = null; }
    if (!mic.ready) return void say("Mic is off: use a line below");
    audio();
    chirp(1400, 30);
    navigator.vibrate?.(30);
    pressAt.current = live.current!.now();
    const startMs = Math.round(pressAt.current);
    live.current!.send({ type: "key", down: true, at: startMs });
    // Stream while held, so Cartesia hears the call as it is spoken and finishes at release.
    mic.start((pcm) => live.current?.send({ type: "mic_frame", start_ms: startMs, pcm }));
    setOnAir(true);
  };
  const up = () => {
    if (!onAir || releaseTimer.current) return;
    releaseTimer.current = window.setTimeout(() => {
      releaseTimer.current = null;
      setOnAir(false);
      chirp(900, 30);
      mic.finish();
      live.current!.send({ type: "mic_end" }); // under 0.3 s the hub treats it as a tap, not a call
    }, TAIL_MS);
  };

  useEffect(() => {
    const kd = (e: KeyboardEvent) => { if (e.code === "Space" && !e.repeat && document.activeElement?.tagName !== "INPUT") { e.preventDefault(); down(); } };
    const ku = (e: KeyboardEvent) => { if (e.code === "Space") { e.preventDefault(); up(); } };
    addEventListener("keydown", kd);
    addEventListener("keyup", ku);
    return () => { removeEventListener("keydown", kd); removeEventListener("keyup", ku); };
  });

  // ---- derived state

  const others = Object.keys(keyed).filter((s) => s !== station);
  const alertFresh = alert && Date.now() - alert.at < 4000 ? alert : null;
  const steppedOnMe = alertFresh && alertFresh.stations.includes(station);
  const letter = me?.name?.slice(-1) ?? "A";
  const color = PLANE_COLORS[letter] ?? "#2dd4bf";
  const lines4say = useMemo(() => sayLines(me?.spoken ?? station, station.startsWith("H")), [me, station]);
  const sync = live.current?.sync;
  const lastFirstAudio = ear?.latency?.tts_first_audio_ms;
  const pttState = conn !== "open" ? "off" : onAir ? (others.length ? "clash" : "air") : others.length ? "busy" : "idle";
  const pttText = {
    off: "Reconnecting...",
    idle: mic.ready ? "HOLD TO TALK" : "Mic off",
    air: "ON AIR",
    busy: `${others.map(nameOf).join(" and ")} talking`,
    clash: "TALKED OVER",
  }[pttState];

  return (
    <main className="fly" style={{ ["--plane" as any]: color }}>
      <header>
        <div className="me">
          <b>You are {me?.name ?? station}</b>
          <span>{me?.spoken ?? ""} · radio {me ? "118.7" : ""}</span>
        </div>
        <span className={`dot ${conn}`} title={conn} />
      </header>

      {alertFresh && (
        <div className={`alert ${steppedOnMe ? "mine" : ""}`} role="alert">
          <b>Stepped on!</b> {alertFresh.stations.map(nameOf).join(" and ")} talked at the same time.
          <small> Unstep saw it {alertFresh.uplink_ms} ms after the second key went down.</small>
        </div>
      )}

      {ear && (
        <section className="ear">
          <div className="ear-head"><span>Only you can hear this</span><span>left ear</span></div>
          <p>{ear.text.replace(/^\[chime\]\s*/, "")}</p>
          <button className="ghost" onClick={() => playWav(earAudio.current)}>Play again</button>
        </section>
      )}

      <Readback trace={trace} />

      <button
        className={`ptt ${pttState}`}
        onPointerDown={(e) => { (e.target as Element).setPointerCapture?.(e.pointerId); down(); }}
        onPointerUp={up}
        onPointerCancel={up}
        onContextMenu={(e) => e.preventDefault()}
        disabled={conn !== "open"}
      >
        <span className="ptt-main">{pttText}</span>
        {onAir && <span className="ptt-sub">{((live.current!.now() - pressAt.current) / 1000).toFixed(1)} s</span>}
        {!onAir && pttState === "busy" && <span className="ptt-sub">You can still talk. Real radios don't stop you.</span>}
      </button>

      <section className="chips">
        <h2>Tap to say on the radio</h2>
        {lines4say.map((l) => (
          <button key={l.text} onClick={() => live.current?.send({ type: "say", text: l.text })}>
            {l.label}{l.note && <small> ({l.note})</small>}
          </button>
        ))}
      </section>

      <section className="chips ask">
        <h2>Ask Unstep (not on the radio)</h2>
        {ASK_LINES.map((q) => <button key={q} onClick={() => live.current?.send({ type: "ask", text: q })}>{q.replace("Unstep, ", "")}</button>)}
        <form onSubmit={(e) => { e.preventDefault(); if (ask.trim()) { live.current?.send({ type: "ask", text: ask }); setAsk(""); } }}>
          <input value={ask} onChange={(e) => setAsk(e.target.value)} placeholder="Ask anything about your flight" />
        </form>
      </section>

      <button className="ghost" onClick={() => setDetails((d) => !d)}>{details ? "Hide" : "Show"} timings and log</button>
      {details && (
        <section className="details">
          <dl>
            <dt>Clock vs tower</dt><dd>{sync ? `${sync.offset} ms offset, ±${Math.ceil(sync.rtt / 2)} ms (${sync.samples} pings)` : "syncing"}</dd>
            <dt>Round trip</dt><dd>{sync ? `${sync.rtt} ms` : "-"}</dd>
            <dt>Your key reached the tower</dt><dd>{uplink !== null ? `${uplink} ms after you pressed` : "press to measure"}</dd>
            <dt>Advisory first audio</dt><dd>{lastFirstAudio !== undefined ? `${Math.round(lastFirstAudio)} ms` : "-"}</dd>
          </dl>
          <ol className="log">
            {lines.slice(-12).map((l, i) => <li key={i}><b>{l.party}</b> {l.text}</li>)}
          </ol>
          <button className="ghost" onClick={onLeave}>Leave this plane</button>
        </section>
      )}
      {toast && <div className="toast">{toast}</div>}
    </main>
  );
}

function Readback({ trace }: { trace: Trace | null }) {
  if (!trace) return null;
  const last = trace.readbacks[trace.readbacks.length - 1];
  const view: Record<string, [string, string]> = {
    detected: ["wait", "Unstep noticed you missed a call. Checking with the tower..."],
    proposed: ["wait", "Unstep found what the tower said. Checking it is safe to resend..."],
    needs_you: ["wait", "The tower controller is deciding. Stand by."],
    auto_relayed: ["wait", "Resending the tower's own words to you now."],
    approved: ["wait", "The tower approved it. Listen."],
    delivered: ["go", "Now read it back: hold to talk, or tap the first line below."],
    confirmed: ["ok", "Read back correctly. You're safe."],
    readback_wrong: ["bad", `Read back wrong${last ? `: "${last.readback_text}"` : ""}. Listen and try again.`],
    rejected: ["bad", "The tower asked you to say again."],
    expired: ["bad", "No decision in time. Nothing was sent. Ask the tower to say again."],
  };
  const [kind, text] = view[trace.status] ?? ["wait", trace.status];
  return <div className={`state ${kind}`}>{kind === "ok" ? "✓ " : kind === "bad" ? "✗ " : ""}{text}</div>;
}
