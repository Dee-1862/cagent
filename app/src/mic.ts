// Push-to-talk microphone: records while the button is held, sends one 16 kHz PCM clip.

export class Mic {
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private chunks: Float32Array[] = [];
  private on = false;
  level = 0;

  static available(): boolean {
    return !!navigator.mediaDevices?.getUserMedia && window.isSecureContext;
  }

  /** Ask for the mic once, inside the "Turn on my radio" tap. */
  async enable(): Promise<boolean> {
    if (this.stream) return true;
    if (!Mic.available()) return false;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      this.ctx = new AudioContext();
      const src = this.ctx.createMediaStreamSource(this.stream);
      const node = this.ctx.createScriptProcessor(2048, 1, 1);
      node.onaudioprocess = (e) => {
        const data = e.inputBuffer.getChannelData(0);
        let peak = 0;
        for (let i = 0; i < data.length; i += 16) peak = Math.max(peak, Math.abs(data[i]));
        this.level = peak;
        if (this.on) this.chunks.push(new Float32Array(data));
      };
      src.connect(node);
      node.connect(this.ctx.destination);
      return true;
    } catch {
      return false;
    }
  }

  get ready(): boolean { return !!this.stream; }

  /** Starts recording. With onFrame, sends about 100 ms of 16 kHz PCM at a time while held (P3). */
  start(onFrame?: (b64: string) => void): void {
    if (this.ctx?.state === "suspended") void this.ctx.resume();
    this.chunks = [];
    this.flushed = 0;
    this.carry = new Float32Array(0);
    this.on = true;
    this.onFrame = onFrame ?? null;
    if (onFrame) this.timer = window.setInterval(() => this.flush(), 100);
  }

  /** Stops a streamed recording: sends what is left. The hub then gets mic_end. */
  finish(): void {
    this.on = false;
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    this.flush();
    this.onFrame = null;
  }

  private flushed = 0;
  private carry = new Float32Array(0);
  private timer: number | null = null;
  private onFrame: ((b64: string) => void) | null = null;

  private flush(): void {
    if (!this.ctx || !this.onFrame || this.flushed >= this.chunks.length) return;
    const fresh = this.chunks.slice(this.flushed);
    this.flushed = this.chunks.length;
    const total = this.carry.length + fresh.reduce((n, c) => n + c.length, 0);
    const all = new Float32Array(total);
    all.set(this.carry);
    let o = this.carry.length;
    for (const c of fresh) { all.set(c, o); o += c.length; }
    const { pcm, used } = downsample(all, this.ctx.sampleRate / 16000);
    this.carry = all.slice(used); // input samples that don't fill a whole output sample yet
    if (pcm.length) this.onFrame(toBase64(pcm));
  }

  /** Stops recording. Returns base64 16 kHz mono PCM16, or null for a clip under 0.3 s. */
  stop(): string | null {
    this.on = false;
    if (!this.ctx) return null;
    const total = this.chunks.reduce((n, c) => n + c.length, 0);
    if (total < this.ctx.sampleRate * 0.3) return null;
    const all = new Float32Array(total);
    let o = 0;
    for (const c of this.chunks) { all.set(c, o); o += c.length; }
    return toBase64(downsample(all, this.ctx.sampleRate / 16000).pcm);
  }
}

/** Averages input samples down to 16 kHz PCM16. `used` is how many input samples were consumed. */
export function downsample(input: Float32Array, ratio: number): { pcm: Int16Array; used: number } {
  const n = Math.floor(input.length / ratio);
  const out = new Int16Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * ratio);
    const b = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = a; j < b; j++) sum += input[j];
    out[i] = Math.max(-1, Math.min(1, sum / Math.max(1, b - a))) * 32767;
  }
  return { pcm: out, used: Math.floor(n * ratio) };
}

function toBase64(pcm: Int16Array): string {
  const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}
