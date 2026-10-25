// 15-23 s. The tower's real "Cessna 1-2-3, hold short runway 33" draws as its own waveform; the helicopter keys
// up 1.55 s in and the overlap turns to noise, taking "hold short runway 33" with it. A scan line repairs it,
// the words come back (the instruction in magenta), and the name resolves underneath.
import React from "react";
import {AbsoluteFill, random} from "remotion";
import waves from "../public/data/waves.json";
import {K, b612, head, mono, ramp, fadeOut, useT} from "./ui";

export const T0 = 15.4;          // the audio starts (sfx/title_collision.wav)
const OVER = 1.55;               // the helicopter keys up, seconds into the tower call
const HEAL = 19.25;              // the scan line starts
const X0 = 170, X1 = 1750, MID = 430, AMP = 150, RULE = 760;

export const Title: React.FC = () => {
  const t = useT();
  if (t < 15 || t > 23.1) return null;
  const tw = waves["003"];
  const n = tw.peaks.length;
  const cursor = t - T0;                                  // seconds of the call heard so far
  const healX = X0 + (X1 - X0) * ramp(t, HEAL, HEAL + 0.85);
  const xAt = (sec: number) => X0 + (X1 - X0) * (sec / tw.dur);
  const flat = ramp(t, 20.55, 21.15);                     // the repaired call flattens into one line: the rule the name stands on
  const drop = ramp(t, 20.55, 21.15);
  const frame = Math.floor(t * 30);
  const words = tw.words.map((w) => ({...w, w: w.w.trim().replace(/[.,]/g, "").toUpperCase()}));
  const placed: (typeof words[number] & {x: number})[] = [];
  for (const w of words) {                                  // under the moment it was spoken, never overlapping
    const prev = placed[placed.length - 1];
    placed.push({...w, x: Math.max(xAt(w.s), prev ? prev.x + prev.w.length * 21 + 26 : 0)});
  }
  return (
    <AbsoluteFill style={{background: K.bg, opacity: fadeOut(t, 22.75, 0.35)}}>
      <div style={{position: "absolute", left: X0, top: 120, fontFamily: mono, fontSize: 18, color: K.dim, letterSpacing: 0.8, opacity: ramp(t, 15.1, 15.5) * (1 - flat)}}>
        KUNS TOWER · 118.700 MHZ
      </div>
      <div style={{position: "absolute", inset: 0, transform: `translateY(${drop * (RULE - MID)}px)`}}>
        <svg width={1920} height={1080} style={{position: "absolute", inset: 0}}>
          <line x1={X0} y1={MID} x2={X1} y2={MID} stroke={K.hair} strokeWidth={1} />
          {tw.peaks.map((p, i) => {
            const sec = (i / n) * tw.dur;
            if (sec > cursor) return null;
            const x = X0 + ((X1 - X0) * i) / n;
            const hit = sec >= OVER && x > healX;           // still broken: noise where the carriers overlapped
            const h = (hit ? (0.25 + random(`n${i}-${frame}`) * 0.95) * AMP : Math.max(1.5, p * AMP)) * (1 - flat) + flat * 1;
            return <rect key={i} x={x} y={MID - h} width={2.2} height={h * 2} fill={hit ? K.red : K.cyan} opacity={hit ? 0.85 : 0.95} />;
          })}
          {/* the scan line */}
          {t >= HEAL && t <= HEAL + 0.95 && <rect x={healX - 1} y={MID - AMP - 40} width={2} height={AMP * 2 + 80} fill={K.magenta} />}
          {flat > 0.98 && <rect x={X0} y={MID - 1} width={X1 - X0} height={2} fill={K.cyan} />}
        </svg>
        {/* the words, placed under the moment they were spoken */}
        {placed.map((w, i) => {
          if (w.s > cursor) return null;
          const x = w.x;
          const lost = w.s >= OVER && x > healX;
          const instr = w.s >= OVER;
          return (
            <div key={i} style={{position: "absolute", left: x, top: MID + AMP + 46, fontFamily: mono, fontSize: 34, fontWeight: 700, opacity: 1 - flat,
              color: lost ? K.red : instr ? K.magenta : K.ink}}>
              {lost ? "█".repeat(Math.max(2, w.w.length - (frame % 3))) : w.w}
            </div>
          );
        })}
        <div style={{position: "absolute", left: xAt(OVER), top: MID - AMP - 70, fontFamily: mono, fontSize: 17, color: K.red, letterSpacing: 0.8,
          opacity: cursor > OVER + 0.2 && t < HEAL ? 1 : 0}}>
          ▲ SECOND TRANSMITTER KEYED · HELICOPTER 4-5-6
        </div>
      </div>
      {/* the name rises out of the line the call became */}
      <div style={{position: "absolute", left: X0 - 8, top: RULE - 214, height: 268, overflow: "hidden"}}>
        <div style={{fontFamily: head, fontWeight: 800, fontSize: 228, letterSpacing: -7, color: K.ink, lineHeight: 0.92,
          transform: `translateY(${(1 - ramp(t, 21.05, 21.75)) * 268}px)`}}>Unstep</div>
      </div>
      <div style={{position: "absolute", left: X0, top: RULE + 34, fontFamily: b612, fontSize: 34, color: K.dim, clipPath: `inset(0 ${(1 - ramp(t, 21.6, 22.2)) * 100}% 0 0)`}}>
        Agentic air traffic control. <span style={{color: K.ink}}>A second set of ears for every controller.</span>
      </div>
    </AbsoluteFill>
  );
};
