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

  start(): void {
    if (this.ctx?.state === "suspended") void this.ctx.resume();
    this.chunks = [];
    this.on = true;
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
    const ratio = this.ctx.sampleRate / 16000;
    const out = new Int16Array(Math.floor(all.length / ratio));
    for (let i = 0; i < out.length; i++) {
      const a = Math.floor(i * ratio);
      const b = Math.min(all.length, Math.floor((i + 1) * ratio));
      let sum = 0;
      for (let j = a; j < b; j++) sum += all[j];
      out[i] = Math.max(-1, Math.min(1, sum / Math.max(1, b - a))) * 32767;
    }
    const bytes = new Uint8Array(out.buffer);
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(bin);
  }
}
