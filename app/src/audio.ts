// Audio out: radio clips and Unstep's private advisories, decoded from base64 WAV.

let ctx: AudioContext | null = null;

export function audio(): AudioContext {
  if (!ctx) ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

export async function playWav(b64: string | null | undefined): Promise<void> {
  if (!b64) return;
  try {
    const c = audio();
    const bytes = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
    const buf = await c.decodeAudioData(bytes.buffer);
    const src = c.createBufferSource();
    src.buffer = buf;
    src.connect(c.destination);
    src.start();
  } catch (e) {
    console.warn("audio", e);
  }
}

// Streamed advisories (R14): mono pcm_s16le chunks, played back to back in the left ear
// as they arrive, so the pilot hears Unstep about one network hop after Cartesia's first audio.

type Stream = { next: number; at: number; pending: Map<number, Float32Array>; rate: number; sources: AudioBufferSourceNode[] };
const streams = new Map<string, Stream>();

export function pcm16ToFloat(b64: string): Float32Array {
  const bytes = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
  const view = new DataView(bytes.buffer);
  const out = new Float32Array(bytes.length >> 1);
  for (let i = 0; i < out.length; i++) out[i] = view.getInt16(i * 2, true) / 32768;
  return out;
}

/** Queue one chunk; chunks play in `seq` order even if they arrive out of order. */
export function streamChunk(id: string, seq: number, rate: number, b64: string): void {
  try {
    const c = audio();
    let s = streams.get(id);
    if (!s) streams.set(id, (s = { next: 0, at: 0, pending: new Map(), rate, sources: [] }));
    s.pending.set(seq, pcm16ToFloat(b64));
    while (s.pending.has(s.next)) {
      const samples = s.pending.get(s.next)!;
      s.pending.delete(s.next);
      s.next += 1;
      if (!samples.length) continue;
      const buf = c.createBuffer(2, samples.length, s.rate);
      buf.copyToChannel(samples, 0); // left ear only; the right channel stays silent
      const src = c.createBufferSource();
      src.buffer = buf;
      src.connect(c.destination);
      s.at = Math.max(s.at, c.currentTime + 0.02);
      src.start(s.at);
      s.at += buf.duration;
      s.sources.push(src);
    }
  } catch (e) {
    console.warn("audio stream", e);
  }
}

/** The line is complete, or was cut off: a cut-off line stops at once. */
export function streamEnd(id: string, cancelled: boolean): void {
  const s = streams.get(id);
  if (!s) return;
  if (!cancelled) { // late chunks may still be on their way: keep the stream a while
    setTimeout(() => streams.delete(id), 30_000);
    return;
  }
  for (const src of s.sources) { try { src.stop(); } catch { /* already done */ } }
  streams.delete(id);
}

/** Short press chirp, like a radio key click. */
export function chirp(freq = 1200, ms = 40): void {
  try {
    const c = audio();
    const o = c.createOscillator();
    const g = c.createGain();
    o.frequency.value = freq;
    g.gain.value = 0.05;
    o.connect(g).connect(c.destination);
    o.start();
    o.stop(c.currentTime + ms / 1000);
  } catch { /* no audio yet */ }
}

let wake: any = null;

/** Keep the screen on while flying; the lock drops when the tab is hidden, so take it again. */
export async function keepAwake(): Promise<void> {
  try {
    wake = await (navigator as any).wakeLock?.request("screen");
  } catch { /* not supported or not https */ }
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && wake) void keepAwake();
  });
}
