// The hold-to-talk button's "on air" face: a Voice Memos style waveform. Warm orange
// rounded bars scroll right to left from the live mic level, a red playhead with dots sits
// at 60% width, a dotted flat line runs ahead of it, a time ruler (00:02, 00:04 ...) on top,
// elapsed time in the corner. Bars turn red while someone else is keyed (talked over).

import { useEffect, useRef } from "react";

export type Sample = { t: number; level: number; clash: boolean };
const WINDOW_MS = 5000, PLAYHEAD = 0.6, STEP_MS = 50;

export function mmss(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function VoiceMemo({ startedAt, now, level, clash }: {
  startedAt: number; now: () => number; level: () => number; clash: () => boolean;
}) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const samples = useRef<Sample[]>([]);

  useEffect(() => {
    samples.current = [];
    let smooth = 0;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const sampler = window.setInterval(() => {
      // peak level, eased: rises at once, falls gently, square-rooted so speech fills the lane
      smooth = Math.max(Math.sqrt(Math.min(1, level())), smooth * 0.8);
      samples.current.push({ t: now(), level: smooth, clash: clash() });
      if (samples.current.length > 400) samples.current.shift();
    }, STEP_MS);
    let raf = 0, timer = 0, alive = true;
    const draw = () => {
      const c = canvas.current;
      if (!c || !alive) return;
      const dpr = window.devicePixelRatio || 1, W = c.clientWidth, H = c.clientHeight;
      if (c.width !== Math.round(W * dpr) || c.height !== Math.round(H * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
      const g = c.getContext("2d");
      if (!g) return;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, W, H);
      const t = now(), px = W * PLAYHEAD, mid = H * 0.58, xOf = (at: number) => px - ((t - at) / WINDOW_MS) * px;
      // ruler: a tick every second, labels every 2 s, counted from the press
      g.fillStyle = "#8b8f98"; g.font = "12px system-ui"; g.textBaseline = "top"; g.textAlign = "center";
      for (let s = Math.ceil((t - startedAt - WINDOW_MS) / 1000); ; s++) {
        const at = startedAt + s * 1000, x = xOf(at);
        if (x > W) break;
        if (s < 0 || x < 0) continue;
        g.fillRect(x, 22, 1, s % 2 === 0 ? 8 : 4);
        if (s % 2 === 0 && s > 0 && x > 24 && x < W - 24) g.fillText(mmss(s * 1000), x, 4);
      }
      // dotted line ahead of now
      g.strokeStyle = "#5b5f68"; g.setLineDash([2, 5]); g.lineWidth = 2;
      g.beginPath(); g.moveTo(px, mid); g.lineTo(W, mid); g.stroke(); g.setLineDash([]);
      // bars
      const barW = Math.max(2, (STEP_MS / WINDOW_MS) * px * 0.62);
      for (const s of samples.current) {
        const x = xOf(s.t);
        if (x < -barW || x > px) continue;
        const h = Math.max(3, Math.min(H * 0.3, s.level * H * 0.3));
        g.fillStyle = s.clash ? "#ef4444" : "#f59e3b";
        const r = Math.min(barW / 2, 3);
        g.beginPath();
        (g as any).roundRect ? (g as any).roundRect(x - barW / 2, mid - h, barW, h * 2, r) : g.rect(x - barW / 2, mid - h, barW, h * 2);
        g.fill();
      }
      // playhead with dots
      g.fillStyle = "#ef4444";
      g.fillRect(px - 1, 30, 2, H - 40);
      g.beginPath(); g.arc(px, 30, 4, 0, Math.PI * 2); g.arc(px, H - 10, 4, 0, Math.PI * 2); g.fill();
      // elapsed
      g.textAlign = "right"; g.fillStyle = "#e5e7eb"; g.font = "600 13px system-ui";
      g.fillText(`${mmss(t - startedAt)}.${Math.floor(((t - startedAt) % 1000) / 100)}`, W - 10, H - 22);
    };
    const loop = () => { draw(); raf = requestAnimationFrame(loop); };
    if (reduced) { draw(); timer = window.setInterval(draw, 250); } else loop();
    return () => { alive = false; clearInterval(sampler); clearInterval(timer); cancelAnimationFrame(raf); };
  }, [startedAt, now, level, clash]);

  return <canvas ref={canvas} className="memo" aria-label="Recording: your voice on the radio" />;
}
