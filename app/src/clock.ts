// Clock sync with the hub, NTP style. Every key press and mic clip is stamped in hub
// time, so the hub's overlap math is not off by the phone's clock drift.

export type Sample = { t0: number; t1: number; t3: number }; // sent, hub received, reply back

export type Sync = { offset: number; rtt: number; samples: number };

/** Hub time = local time + offset. Uses the fastest round trip: its error is at most rtt / 2. */
export function bestOffset(samples: Sample[]): Sync | null {
  if (samples.length === 0) return null;
  const best = samples.reduce((a, b) => (b.t3 - b.t0 < a.t3 - a.t0 ? b : a));
  return { offset: Math.round(best.t1 - (best.t0 + best.t3) / 2), rtt: best.t3 - best.t0, samples: samples.length };
}
