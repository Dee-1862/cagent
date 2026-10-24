// Spotify-lyrics style caption lines for the pilot screen. Pure and unit tested.
// One line per transmission (caption id), plus Unstep's private advisories and "Talked over"
// events. A line's text changes at most once per second so it reads smoothly; the final
// caption replaces the interim one at once.

export type Kind = "callsign" | "action" | "runway" | "taxiway" | null;
export type Word = { text: string; kind: Kind };
export type Line = {
  id: string;
  who: string;          // "You", "Tower", "Plane B", "Unstep"
  kind: "radio" | "advisory" | "event";
  words: Word[];
  final: boolean;
  shownAt: number;      // when the visible text last changed
  pending: Word[] | null; // newer text waiting for its one-second slot
  lagMs: number | null;
  mine: boolean;
  source?: "stt" | "tts";
};
export type Lyrics = { lines: Line[] };

export const THROTTLE_MS = 1000;
export const MAX_LINES = 8;
export const empty = (): Lyrics => ({ lines: [] });

const keep = (lines: Line[]) => lines.slice(-MAX_LINES);

export function caption(
  s: Lyrics,
  m: { id: string; station: string; words: { text: string; kind: Kind }[]; final: boolean; lag_ms: number | null; source?: "stt" | "tts" },
  now: number, who: string, mine: boolean,
): Lyrics {
  const words = m.words.map((w) => ({ text: w.text, kind: w.kind }));
  const i = s.lines.findIndex((l) => l.id === m.id);
  if (i < 0) {
    return { lines: keep([...s.lines, { id: m.id, who, kind: "radio", words, final: m.final, shownAt: now, pending: null, lagMs: m.lag_ms, mine, source: m.source }]) };
  }
  const line = s.lines[i];
  if (line.final && !m.final) return s; // a late interim never replaces the final text
  const due = m.final || now - line.shownAt >= THROTTLE_MS;
  const next: Line = due
    ? { ...line, words, final: m.final, shownAt: now, pending: null, lagMs: m.lag_ms ?? line.lagMs }
    : { ...line, pending: words, lagMs: m.lag_ms ?? line.lagMs };
  return { lines: s.lines.map((l, k) => (k === i ? next : l)) };
}

/** Show waiting text whose one-second slot has come. Call about every 250 ms. */
export function tick(s: Lyrics, now: number): Lyrics {
  if (!s.lines.some((l) => l.pending && now - l.shownAt >= THROTTLE_MS)) return s;
  return { lines: s.lines.map((l) => (l.pending && now - l.shownAt >= THROTTLE_MS ? { ...l, words: l.pending, pending: null, shownAt: now } : l)) };
}

// Words the advisory voice says the ICAO way, shown the plain way on screen.
const SPOKEN_FORMS: Record<string, string> = { tree: "three", fife: "five", fower: "four" };

/** On-screen form of a spoken advisory: no leading "Advisory." (the voice says it), "tree" as "three". */
export function readable(text: string): string {
  return text.replace(/^\s*Advisory\.\s*/i, "")
    .replace(/\b(tree|fife|fower)\b/gi, (w) => SPOKEN_FORMS[w.toLowerCase()] ?? w);
}

export const DUPLICATE_MS = 8000;

export function note(s: Lyrics, id: string, who: string, kind: "advisory" | "event", text: string, now: number): Lyrics {
  if (s.lines.some((l) => l.id === id)) return s;
  const shown = kind === "advisory" ? readable(text) : text;
  const same = kind === "advisory" && s.lines.some((l) => l.kind === kind && now - l.shownAt < DUPLICATE_MS && l.words.map((w) => w.text).join(" ") === shown);
  if (same) return s; // the same advisory twice in a row reads as noise
  const words = shown.split(/\s+/).filter(Boolean).map((t) => ({ text: t, kind: null as Kind }));
  return { lines: keep([...s.lines, { id, who, kind, words, final: true, shownAt: now, pending: null, lagMs: null, mine: false }]) };
}

/** The label under the card, from the newest radio line with a measured lag. */
export function lagLabel(s: Lyrics): string | null {
  const latest = [...s.lines].reverse().find((l) => l.kind === "radio");
  if (latest?.source === "tts") return "Typed line · words shown at their spoken time (TTS timing)";
  const line = [...s.lines].reverse().find((l) => l.kind === "radio" && l.lagMs != null);
  if (!line) return null;
  return `Cartesia live caption · ${Math.round(line.lagMs!)} ms behind ${line.mine ? "your voice" : "speech"}`;
}
