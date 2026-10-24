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

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && wake) void keepAwake();
});
