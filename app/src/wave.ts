// State for the scrolling radio waveform: loudness bars, caption words placed at their
// spoken time, and talked-over windows, all on the hub clock. Pure functions, unit tested.

export type Kind = "callsign" | "action" | "runway" | "taxiway" | null;
export type CaptionWord = { text: string; kind: Kind; at_ms: number | null };
export type Bar = { t: number; rms: number };
export type Caption = { id: string; station: string; start: number; words: CaptionWord[]; final: boolean; source: "stt" | "tts"; lag_ms: number | null; ts: number };
export type Overlap = { start: number; end: number | null; stations: string[] };
export type Wave = { bars: Record<string, Bar[]>; captions: Record<string, Caption>; overlaps: Overlap[] };

export const WINDOW_MS = 6000;
export const empty = (): Wave => ({ bars: {}, captions: {}, overlaps: [] });

/** "N123AB-1761339120000" -> 1761339120000; a tx id has no start in it. */
export function streamStart(id: string): number | null {
  const m = id.match(/-(\d{12,})$/);
  return m ? Number(m[1]) : null;
}

export function addLevel(w: Wave, m: { station: string; t_ms: number; step_ms: number; rms: number[] }): Wave {
  const bars = (w.bars[m.station] ?? []).concat(m.rms.map((rms, i) => ({ t: m.t_ms + i * m.step_ms, rms })));
  return { ...w, bars: { ...w.bars, [m.station]: bars } };
}

export function addCaption(w: Wave, m: { id: string; station: string; words: CaptionWord[]; final: boolean; source: "stt" | "tts"; lag_ms: number | null; ts: number }): Wave {
  const prev = w.captions[m.id];
  const start = prev?.start ?? streamStart(m.id) ?? m.words.find((x) => x.at_ms != null)?.at_ms ?? m.ts;
  return { ...w, captions: { ...w.captions, [m.id]: { ...m, start } } };
}

export function addOverlap(w: Wave, o: Overlap): Wave {
  const same = w.overlaps.findIndex((x) => Math.abs(x.start - o.start) < 300);
  const overlaps = same >= 0 ? w.overlaps.map((x, i) => (i === same ? { ...x, end: o.end ?? x.end, stations: o.stations } : x)) : [...w.overlaps, o];
  return { ...w, overlaps };
}

/** Drop what has scrolled out of the window. */
export function prune(w: Wave, now: number, windowMs = WINDOW_MS): Wave {
  const from = now - windowMs * 1.5;
  const bars: Record<string, Bar[]> = {};
  for (const [k, v] of Object.entries(w.bars)) { const kept = v.filter((b) => b.t >= from); if (kept.length) bars[k] = kept; }
  const captions: Record<string, Caption> = {};
  for (const [k, c] of Object.entries(w.captions)) if (c.ts >= from) captions[k] = c;
  return { bars, captions, overlaps: w.overlaps.filter((o) => (o.end ?? now) >= from) };
}

/** Hub time of each word: its own `at_ms` (TTS), else spread evenly from the stream start to
 *  when the text was heard (arrival minus Cartesia's lag), which is where it was spoken. */
export function wordTimes(c: Caption): number[] {
  const heardAt = c.ts - (c.lag_ms ?? 0);
  const n = c.words.length;
  return c.words.map((w, i) => w.at_ms ?? c.start + ((heardAt - c.start) * (i + 0.5)) / Math.max(1, n));
}

/** x position (0..width) of hub time t, with "now" at the playhead fraction. */
export function xOf(t: number, now: number, width: number, playhead = 0.78, windowMs = WINDOW_MS): number {
  return width * playhead + ((t - now) / windowMs) * width;
}
