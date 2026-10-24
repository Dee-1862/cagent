// Eyes-free pilot mode (C2): in the demo the pilot wears AirPods and does not look at the
// phone, so every screen cue also has an earcon. Placeholders until Rishit's side sends the
// wording; each cue is a short tone pattern in the LEFT ear, Unstep's side, so it is never
// mistaken for the radio (which plays in both ears).

import { audio } from "./audio";

export type Cue =
  | "joined" | "on_air" | "busy" | "stepped_on_me" | "stepped_on_others" | "advisory"
  | "readback_ok" | "readback_wrong" | "conn_lost" | "conn_back" | "mic_off";

type Note = [hz: number, ms: number, gap?: number];

/** Tone patterns: rising = good, falling = bad, repeated = urgent. */
export const PATTERNS: Record<Cue, Note[]> = {
  joined: [[660, 90, 40], [880, 120]],
  on_air: [[1400, 30]],
  busy: [[440, 120, 60], [440, 120]],
  stepped_on_me: [[1200, 70, 40], [900, 70, 40], [1200, 70, 40], [900, 70]],
  stepped_on_others: [[700, 60, 60], [700, 60]],
  advisory: [], // the hub's advisory already starts with its chime
  readback_ok: [[660, 80, 30], [990, 140]],
  readback_wrong: [[700, 120, 40], [470, 200]],
  conn_lost: [[330, 250]],
  conn_back: [[500, 80, 30], [750, 80]],
  mic_off: [[300, 120, 60], [300, 120]],
};

/** Total length of a pattern in ms (for tests and for not stacking cues). */
export function patternMs(cue: Cue): number {
  return PATTERNS[cue].reduce((t, [, ms, gap = 0]) => t + ms + gap, 0);
}

let busyUntil = 0;

export function cue(name: Cue): void {
  const notes = PATTERNS[name];
  if (!notes.length) return;
  try {
    const c = audio();
    let t = Math.max(c.currentTime + 0.01, busyUntil);
    const pan = typeof c.createStereoPanner === "function" ? c.createStereoPanner() : null;
    if (pan) { pan.pan.value = -1; pan.connect(c.destination); }
    for (const [hz, ms, gap = 0] of notes) {
      const o = c.createOscillator();
      const g = c.createGain();
      o.frequency.value = hz;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.08, t + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, t + ms / 1000);
      o.connect(g).connect(pan ?? c.destination);
      o.start(t);
      o.stop(t + ms / 1000 + 0.02);
      t += (ms + gap) / 1000;
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
