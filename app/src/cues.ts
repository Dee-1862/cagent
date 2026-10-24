// Eyes-free pilot mode (C2): in the demo the pilot wears AirPods and does not look at the
// phone, so every screen cue also has an earcon, and some a short spoken line in Unstep's
// own voice (the hub speaks it, see `say` below). Wording agreed with Rishit's side (R20).
// Earcons play in the LEFT ear, Unstep's side; the radio plays in both ears. Rule: never
// over the pilot's own transmission or an advisory: cues wait in a queue until both end.

import { audio } from "./audio";

export type Cue =
  | "joined" | "on_air" | "busy" | "stepped_on_me" | "stepped_on_others" | "advisory"
  | "readback_ok" | "readback_wrong" | "conn_lost" | "conn_back" | "mic_off";

/** hz2: a second tone at the same time (a clash); to: glide to this pitch. */
export type Note = { hz: number; ms: number; gap?: number; hz2?: number; to?: number; wave?: OscillatorType; gain?: number };

export const PATTERNS: Record<Cue, Note[]> = {
  joined: [{ hz: 660, ms: 90, gap: 40 }, { hz: 880, ms: 120 }], // two rising notes
  on_air: [{ hz: 1400, ms: 25, wave: "square", gain: 0.04 }], // one short click
  busy: [{ hz: 180, ms: 110, gap: 50, wave: "square", gain: 0.05 }, { hz: 180, ms: 110, wave: "square", gain: 0.05 }], // low double buzz
  stepped_on_me: [{ hz: 900, hz2: 955, ms: 140, gap: 40 }, { hz: 900, hz2: 955, ms: 140 }], // two notes clashing
  stepped_on_others: [{ hz: 900, hz2: 955, ms: 120, gain: 0.03 }], // one soft clash
  advisory: [], // the hub's advisory already starts with its chime
  readback_ok: [{ hz: 600, to: 900, ms: 180 }], // single rising note
  readback_wrong: [{ hz: 700, ms: 120, gap: 40 }, { hz: 470, ms: 180 }], // two falling notes
  conn_lost: [{ hz: 600, to: 300, ms: 260 }], // falling tone
  conn_back: [{ hz: 300, to: 600, ms: 220 }], // rising tone
  mic_off: [{ hz: 220, ms: 200 }], // low single note
};

/** Spoken lines (R20), said by the hub in Unstep's voice. Readback cues have none: the cockpit already speaks them. */
export const SPOKEN: Partial<Record<Cue, string>> = {
  joined: "joined", // the hub says "You are Plane X."
  busy: "busy",
  stepped_on_me: "talked_over",
  conn_back: "back_online",
  mic_off: "mic_off",
};

export function patternMs(cue: Cue): number {
  return PATTERNS[cue].reduce((t, n) => t + n.ms + (n.gap ?? 0), 0);
}

// ---- queue: nothing over the pilot's own key or an advisory

let keyDown = false;
let advisoryActive = 0;
let say: ((phrase: string) => void) | null = null;
const queue: Cue[] = [];
let busyUntil = 0;

export function setSpeaker(fn: ((phrase: string) => void) | null): void { say = fn; }
export function setKeyDown(down: boolean): void { keyDown = down; flush(); }
export function setAdvisory(active: boolean): void { advisoryActive = Math.max(0, advisoryActive + (active ? 1 : -1)); flush(); }
export function blocked(): boolean { return keyDown || advisoryActive > 0; }

/** Play a cue now, or queue it while the pilot talks or an advisory speaks. "Connection lost" plays at once. */
export function cue(name: Cue): void {
  if (name === "on_air" || name === "conn_lost" || !blocked()) return play(name);
  if (!queue.includes(name)) queue.push(name);
}

export function pending(): Cue[] { return [...queue]; }

function flush(): void {
  while (!blocked() && queue.length) play(queue.shift()!);
}

function play(name: Cue): void {
  const notes = PATTERNS[name];
  if (notes.length) tones(notes);
  const phrase = SPOKEN[name];
  if (phrase && say && name !== "conn_lost") say(phrase);
}

function tones(notes: Note[]): void {
  try {
    const c = audio();
    let t = Math.max(c.currentTime + 0.01, busyUntil);
    const pan = typeof c.createStereoPanner === "function" ? c.createStereoPanner() : null;
    if (pan) { pan.pan.value = -1; pan.connect(c.destination); }
    for (const n of notes) {
      const end = t + n.ms / 1000;
      for (const hz of n.hz2 ? [n.hz, n.hz2] : [n.hz]) {
        const o = c.createOscillator();
        const g = c.createGain();
        o.type = n.wave ?? "sine";
        o.frequency.setValueAtTime(hz, t);
        if (n.to) o.frequency.linearRampToValueAtTime(n.to * (hz / n.hz), end);
        g.gain.setValueAtTime(0.0001, t);
        g.gain.exponentialRampToValueAtTime(n.gain ?? 0.08, t + 0.01);
        g.gain.exponentialRampToValueAtTime(0.0001, end);
        o.connect(g).connect(pan ?? c.destination);
        o.start(t);
        o.stop(end + 0.02);
      }
      t = end + (n.gap ?? 0) / 1000;
    }
    busyUntil = t;
  } catch { /* no audio yet */ }
}

/** Which cue a readback trace status should play, if any. */
export function readbackCue(status: string | undefined, previous: string | undefined): Cue | null {
  if (!status || status === previous) return null;
  if (status === "confirmed") return "readback_ok";
  if (status === "readback_wrong") return "readback_wrong";
  return null;
}
