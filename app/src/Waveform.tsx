// Scrolling radio waveform (live captions): one lane per speaker, loudness bars, a red
// playhead at "now", second ticks, the words under the bars at the time they were spoken
// (interim faint, final solid), keywords coloured by kind, talked-over windows shaded red.

import { useEffect, useRef } from "react";
import { Wave, WINDOW_MS, wordTimes, xOf } from "./wave";

const KIND_COLOURS: Record<string, string> = { callsign: "#38bdf8", action: "#f472b6", runway: "#facc15", taxiway: "#a3e635" };
const BAR = "#fb923c";

export function Waveform({ wave, now, nameOf, height = 76 }: { wave: Wave; now: () => number; nameOf: (id: string) => string; height?: number }) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const latest = useRef(wave);
  latest.current = wave;

  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    let raf = 0, timer = 0, alive = true;
    const draw = () => {
      const c = canvas.current;
      if (!c || !alive) return;
      const w = latest.current, t = now();
      const lanes = Object.keys({ ...w.bars, ...Object.fromEntries(Object.values(w.captions).map((x) => [x.station, 1])) });
      const dpr = window.devicePixelRatio || 1, width = c.clientWidth, laneH = height;
      const total = 22 + Math.max(1, lanes.length) * laneH;
      if (c.width !== width * dpr || c.height !== total * dpr) { c.width = width * dpr; c.height = total * dpr; c.style.height = `${total}px`; }
      const g = c.getContext("2d");
      if (!g) return;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, width, total);
      // second ticks
      g.fillStyle = "#64748b"; g.font = "11px system-ui"; g.textBaseline = "top";
      for (let s = Math.floor((t - WINDOW_MS) / 1000) * 1000; s <= t + WINDOW_MS; s += 1000) {
        const x = xOf(s, t, width);
        if (x < 0 || x > width) continue;
        g.fillRect(x, 14, 1, 6);
        g.fillText(`${Math.round((s - t) / 1000)}s`, x + 2, 2);
      }
      // talked-over windows
      for (const o of w.overlaps) {
        const x0 = Math.max(0, xOf(o.start, t, width)), x1 = Math.min(width, xOf(o.end ?? t, t, width));
        if (x1 <= x0) continue;
        g.fillStyle = "rgba(239,68,68,0.22)"; g.fillRect(x0, 22, x1 - x0, total - 22);
        g.fillStyle = "#ef4444"; g.font = "bold 11px system-ui"; g.fillText("TALKED OVER", x0 + 3, 24);
      }
      lanes.forEach((station, i) => {
        const top = 22 + i * laneH, mid = top + laneH * 0.38;
        g.fillStyle = "#94a3b8"; g.font = "11px system-ui"; g.fillText(nameOf(station), 4, top + 2);
        // dotted line ahead of now
        g.strokeStyle = "#334155"; g.setLineDash([2, 4]); g.beginPath(); g.moveTo(xOf(t, t, width), mid); g.lineTo(width, mid); g.stroke(); g.setLineDash([]);
        g.fillStyle = BAR;
        for (const b of w.bars[station] ?? []) {
          const x = xOf(b.t, t, width);
          if (x < 0 || x > xOf(t, t, width)) continue;
          const h = Math.max(1, Math.min(laneH * 0.34, b.rms * laneH * 2.2));
          g.fillRect(x, mid - h, Math.max(1, (50 / WINDOW_MS) * width - 1), h * 2);
        }
        for (const cap of Object.values(w.captions)) {
          if (cap.station !== station) continue;
          const times = wordTimes(cap);
          g.font = `${cap.final ? "600" : "400"} 13px system-ui`;
          let lastEnd = -Infinity;
          cap.words.forEach((word, k) => {
            let x = xOf(times[k], t, width);
            if (x > xOf(t, t, width) || x < -80) return;
            x = Math.max(x, lastEnd + 3);
            g.globalAlpha = cap.final ? 1 : 0.55;
            g.fillStyle = word.kind ? KIND_COLOURS[word.kind] : "#e2e8f0";
            g.fillText(word.text, x, top + laneH * 0.7);
            lastEnd = x + g.measureText(word.text).width;
          });
          g.globalAlpha = 1;
        }
      });
      // playhead
      g.fillStyle = "#ef4444"; g.fillRect(xOf(t, t, width), 12, 2, total - 12);
    };
    const loop = () => { draw(); raf = requestAnimationFrame(loop); };
    if (reduced) { draw(); timer = window.setInterval(draw, 500); } else loop();
    return () => { alive = false; cancelAnimationFrame(raf); clearInterval(timer); };
  }, [now, nameOf, height]);

  const latestCaption = Object.values(wave.captions).sort((a, b) => b.ts - a.ts)[0];
  return (
    <figure className="waveform" aria-label="Radio waveform with live captions">
      <canvas ref={canvas} style={{ width: "100%", display: "block" }} />
      <figcaption>
        {latestCaption
          ? latestCaption.source === "tts"
            ? "Typed line: words at their spoken time (TTS timing)"
            : `Cartesia live caption${latestCaption.lag_ms != null ? `, ${Math.round(latestCaption.lag_ms)} ms behind speech` : ""}`
          : "Radio: waiting for someone to talk"}
      </figcaption>
    </figure>
  );
}
