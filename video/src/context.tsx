// 15-32.5 s. Context for someone who has never thought about air traffic control: who controllers are, how much
// they carry, and how short-staffed they are. Every number on screen names its source.
import React from "react";
import {AbsoluteFill, OffthreadVideo, Sequence, interpolate, staticFile} from "remotion";
import {FPS, K, b612, fadeOut, head, mono, ramp, useT} from "./ui";

export const X0 = 15, X1 = 36;
export const NEWS = [22.5, 31.3] as const;

// a radar scope: rings, a sweep, aircraft that brighten as the beam passes
const Radar: React.FC<{t: number; o: number}> = ({t, o}) => {
  const cx = 1400, cy = 540, R = 360, a = ((t * 75) % 360) * (Math.PI / 180);
  const blips = Array.from({length: 22}, (_, i) => {
    const ang = (i * 137.5) % 360, r = 70 + ((i * 53) % 270);
    const drift = (t - X0) * (0.4 + (i % 5) * 0.12);
    const th = ((ang + drift) * Math.PI) / 180;
    return {x: cx + Math.cos(th) * r, y: cy + Math.sin(th) * r, th: ((ang + drift) % 360 + 360) % 360, id: i};
  });
  const beam = ((a * 180) / Math.PI) % 360;
  return (
    <svg width={1920} height={1080} style={{position: "absolute", inset: 0, opacity: o}}>
      {[1, 2, 3, 4].map((k) => <circle key={k} cx={cx} cy={cy} r={(R * k) / 4} fill="none" stroke={K.hair} />)}
      <line x1={cx - R} y1={cy} x2={cx + R} y2={cy} stroke={K.faint} /><line x1={cx} y1={cy - R} x2={cx} y2={cy + R} stroke={K.faint} />
      <path d={`M${cx},${cy} L${cx + Math.cos(a) * R},${cy + Math.sin(a) * R} A${R},${R} 0 0,0 ${cx + Math.cos(a - 0.5) * R},${cy + Math.sin(a - 0.5) * R} Z`} fill={K.green} opacity={0.12} />
      <line x1={cx} y1={cy} x2={cx + Math.cos(a) * R} y2={cy + Math.sin(a) * R} stroke={K.green} strokeWidth={2} opacity={0.8} />
      {blips.map((b) => {
        const since = ((beam - b.th) % 360 + 360) % 360;                 // degrees since the beam passed
        const glow = Math.max(0.25, 1 - since / 300);
        return <g key={b.id} opacity={glow}>
          <rect x={b.x - 4} y={b.y - 4} width={8} height={8} fill={K.green} />
          <text x={b.x + 10} y={b.y + 4} fill={K.green} fontFamily={mono} fontSize={13}>{["UAL", "DAL", "AAL", "SWA", "N", "JBU"][b.id % 6]}{100 + b.id * 37}</text>
        </g>;
      })}
    </svg>
  );
};

const Stat: React.FC<{t: number; at: number; big: string; label: string; src: string; y: number}> = ({t, at, big, label, src, y}) => {
  const p = ramp(t, at, at + 0.45);
  return (
    <div style={{position: "absolute", left: 160, top: y, display: "flex", alignItems: "baseline", gap: 40, opacity: p, transform: `translateY(${(1 - p) * 16}px)`}}>
      <div style={{fontFamily: head, fontWeight: 800, fontSize: 104, color: K.ink, letterSpacing: -3, width: 470}}>{big}</div>
      <div>
        <div style={{fontFamily: b612, fontSize: 34, color: K.ink, maxWidth: 900}}>{label}</div>
        <div style={{fontFamily: mono, fontSize: 16, color: K.dim, marginTop: 8}}>{src}</div>
      </div>
    </div>
  );
};

export const Context: React.FC = () => {
  const t = useT();
  if (t < X0 || t >= X1) return null;
  const wipe = (a: number) => `inset(0 ${(1 - ramp(t, a, a + 0.5)) * 100}% 0 0)`;
  const count = Math.round(interpolate(t, [19.2, 20.4], [0, 45000], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}));
  const radar = ramp(t, 15.1, 15.8) * fadeOut(t, NEWS[0] - 0.3, 0.3);
  return (
    <AbsoluteFill style={{background: K.bg}}>
      <Radar t={t} o={radar} />
      {t < 19 && (
        <div style={{position: "absolute", left: 160, top: 380, width: 900, opacity: fadeOut(t, 18.7, 0.3)}}>
          <div style={{fontFamily: head, fontWeight: 700, fontSize: 64, lineHeight: 1.1, letterSpacing: -1.5, color: K.ink, clipPath: wipe(15.3)}}>Every flight you take is guided by a voice on the radio.</div>
          <div style={{fontFamily: head, fontWeight: 700, fontSize: 64, lineHeight: 1.1, letterSpacing: -1.5, color: K.cyan, marginTop: 18, clipPath: wipe(17.0)}}>An air traffic controller.</div>
        </div>
      )}
      {t >= 19 && t < NEWS[0] && (
        <div style={{position: "absolute", left: 160, top: 330, opacity: ramp(t, 19, 19.3) * fadeOut(t, NEWS[0] - 0.3, 0.3)}}>
          <div style={{fontFamily: head, fontWeight: 800, fontSize: 200, letterSpacing: -8, color: K.ink, lineHeight: 1, fontVariantNumeric: "tabular-nums"}}>{count.toLocaleString("en-US")}</div>
          <div style={{fontFamily: b612, fontSize: 32, color: K.ink, marginTop: 16}}>flights a day in U.S. airspace.</div>
          <div style={{fontFamily: b612, fontSize: 32, color: K.cyan, marginTop: 6, opacity: ramp(t, 20.6, 21.0)}}>Controllers keep every one of them apart.</div>
          <div style={{fontFamily: mono, fontSize: 16, color: K.dim, marginTop: 18}}>SOURCE: FAA</div>
        </div>
      )}
      <Sequence from={Math.round(NEWS[0] * FPS)} durationInFrames={Math.round((NEWS[1] - NEWS[0]) * FPS)}>
        <OffthreadVideo src={staticFile("news_we.mp4")} volume={1.25} />
      </Sequence>
      {t >= NEWS[0] && t < NEWS[1] && (
        <>
          <div style={{position: "absolute", left: 96, top: 72, fontFamily: mono, fontSize: 17, color: "#cfd3d8", background: "rgba(0,0,0,.6)", padding: "6px 10px"}}>WASHINGTON EXAMINER · OCT 2025</div>
          <div style={{position: "absolute", left: 96, bottom: 72, maxWidth: 1500, fontFamily: head, fontWeight: 500, fontSize: 42, color: K.ink, textShadow: "0 2px 18px rgba(0,0,0,.9)", opacity: ramp(t, NEWS[0] + 0.2, NEWS[0] + 0.6)}}>
            “The agency's short 3,500 controllers compared to its goal, with many already on mandatory overtime and six-day weeks.”
          </div>
        </>
      )}
      {t >= NEWS[1] && (
        <div style={{opacity: fadeOut(t, X1 - 0.3, 0.3)}}>
          <Stat t={t} at={31.5} big="20 of 30" label="certified controllers on staff at Washington's Reagan National." src="NATCA VIA FOX 5 DC · 2025" y={250} />
          <Stat t={t} at={32.5} big="24 of 38" label="positions filled at the radar facility that guides Newark." src="FAA VIA FOX BUSINESS · 2025" y={450} />
          <Stat t={t} at={33.5} big="6 × 10 h" label="six days a week, ten-hour days, for years at a time." src="NATCA VIA CNN · 2025" y={650} />
        </div>
      )}
    </AbsoluteFill>
  );
};
