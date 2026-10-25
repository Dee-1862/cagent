// Design system for the film: flat near-black, hairlines, glass-cockpit colour meanings (magenta = the active
// instruction, cyan = ATC data, green = confirmed, amber = caution, red = warning), B612 (the typeface Airbus
// designed for cockpit displays) for data, Archivo for headlines. No glass cards, no glows.
import React, {createContext, useContext} from "react";
import {Easing, interpolate, useCurrentFrame} from "remotion";
import {loadFont as loadArchivo} from "@remotion/google-fonts/Archivo";
import {loadFont as loadB612} from "@remotion/google-fonts/B612";
import {loadFont as loadB612Mono} from "@remotion/google-fonts/B612Mono";

export const head = loadArchivo("normal", {weights: ["500", "600", "700", "800"]}).fontFamily;
export const b612 = loadB612("normal", {weights: ["400", "700"]}).fontFamily;
export const mono = loadB612Mono("normal", {weights: ["400", "700"]}).fontFamily;

export const FPS = 30;
export const K = {
  bg: "#050607", ink: "#E9EBEE", dim: "#868D96", faint: "#1A1E23", hair: "#323840",
  magenta: "#FF4FD8", cyan: "#3FD5FF", green: "#46E07A", amber: "#FFB020", red: "#FF4545",
};

// Sections are written on their own clock; Remap places them on the film's timeline (shifted or sped up).
const TimeMap = createContext<((t: number) => number) | null>(null);
export const useT = () => {
  const t = useCurrentFrame() / FPS, map = useContext(TimeMap);
  return map ? map(t) : t;
};
export type Seg = [number, number, number, number];   // film from, film to, section from, section to
export const Remap: React.FC<{segs: Seg[]; children: React.ReactNode}> = ({segs, children}) => {
  const t = useCurrentFrame() / FPS;
  if (t < segs[0][0] || t >= segs[segs.length - 1][1]) return null;
  const map = (x: number) => {
    const [a, b, oa, ob] = segs.find(([a, b]) => x >= a && x < b) ?? segs[segs.length - 1];
    return oa + ((x - a) * (ob - oa)) / (b - a);
  };
  return <TimeMap.Provider value={map}>{children}</TimeMap.Provider>;
};
// a moment on a section's own clock, placed on the film's timeline
export const toFilm = (segs: Seg[], x: number) => {
  const [a, b, oa, ob] = segs.find(([, , oa, ob]) => x >= oa && x <= ob) ?? segs[0];
  return a + ((x - oa) * (b - a)) / (ob - oa);
};
const out = Easing.bezier(0.16, 1, 0.3, 1);
export const ramp = (t: number, a: number, b: number, e = out) =>
  interpolate(t, [a, b], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: e});
export const fadeOut = (t: number, a: number, d = 0.3) => 1 - ramp(t, a, a + d, Easing.linear);

// subtitle: a hard wipe from the left, small tag above, no word-by-word effects
export const Sub: React.FC<{t: number; from: number; to: number; text: React.ReactNode; tag?: string; tagColor?: string; bottom?: number}> =
  ({t, from, to, text, tag, tagColor = K.dim, bottom = 64}) => {
    if (t < from || t > to) return null;              // gone before the next line starts: no cross-fades of text
    const p = ramp(t, from, from + 0.35);
    return (
      <div style={{position: "absolute", left: 96, bottom, opacity: fadeOut(t, to - 0.22, 0.22), maxWidth: 1400}}>
        {tag && <div style={{fontFamily: mono, fontSize: 17, color: tagColor, marginBottom: 8, letterSpacing: 1}}>{tag}</div>}
        <div style={{fontFamily: head, fontWeight: 500, fontSize: 40, lineHeight: 1.18, color: K.ink, clipPath: `inset(0 ${(1 - p) * 100}% 0 0)`}}>{text}</div>
      </div>
    );
  };

// leader-line annotation, like an engineering drawing: a ring on the thing, a line, a label block
export const Annot: React.FC<{t: number; from: number; to: number; ax: number; ay: number; lx: number; ly: number; color?: string; label: string; body?: string; w?: number}> =
  ({t, from, to, ax, ay, lx, ly, color = K.cyan, label, body, w = 430}) => {
    if (t < from || t > to) return null;
    const dl = ramp(t, from, from + 0.45);
    const tx = ramp(t, from + 0.3, from + 0.7);
    const right = lx >= ax;
    const len = Math.hypot(lx - ax, ly - ay);
    return (
      <div style={{position: "absolute", inset: 0, opacity: fadeOut(t, to - 0.22, 0.22)}}>
        <svg width={1920} height={1080} style={{position: "absolute", inset: 0}}>
          <circle cx={ax} cy={ay} r={9} fill="none" stroke={color} strokeWidth={2} opacity={ramp(t, from, from + 0.15)} />
          <line x1={ax} y1={ay} x2={lx} y2={ly} stroke={color} strokeWidth={1.5} strokeDasharray={len} strokeDashoffset={len * (1 - dl)} />
          <line x1={lx} y1={ly} x2={lx + (right ? 22 : -22) * dl} y2={ly} stroke={color} strokeWidth={1.5} />
        </svg>
        <div style={{position: "absolute", top: ly - 16, left: right ? lx + 30 : undefined, right: right ? undefined : 1920 - lx + 30, width: w,
          textAlign: right ? "left" : "right", clipPath: right ? `inset(0 ${(1 - tx) * 100}% 0 0)` : `inset(0 0 0 ${(1 - tx) * 100}%)`}}>
          <div style={{display: "inline-block", background: "rgba(5,6,7,.88)", padding: "6px 10px"}}>
            <div style={{fontFamily: mono, fontSize: 16, fontWeight: 700, color, letterSpacing: 0.6}}>{label}</div>
            {body && <div style={{fontFamily: b612, fontSize: 21, color: K.ink, lineHeight: 1.3, marginTop: 4}}>{body}</div>}
          </div>
        </div>
      </div>
    );
  };

// a pane label, top-left of a screen region
export const PaneLabel: React.FC<{x: number; y: number; text: string; dot?: string; o?: number}> = ({x, y, text, dot = K.green, o = 1}) => (
  <div style={{position: "absolute", left: x, top: y, display: "flex", alignItems: "center", gap: 10, fontFamily: mono, fontSize: 16, color: K.dim, opacity: o, letterSpacing: 0.8}}>
    <div style={{width: 7, height: 7, background: dot}} />{text}
  </div>
);

// small aircraft (nose up), helicopter and tower glyphs for the diagrams
export const Plane: React.FC<{x: number; y: number; rot?: number; s?: number; color?: string}> = ({x, y, rot = 0, s = 1.6, color = K.ink}) => (
  <g transform={`translate(${x},${y}) rotate(${rot}) scale(${s})`}>
    <path d="M0,-20 L3,-12 L3,-4 L18,2 L18,6 L3,3 L2,14 L7,18 L7,21 L0,19 L-7,21 L-7,18 L-2,14 L-3,3 L-18,6 L-18,2 L-3,-4 L-3,-12 Z" fill={color} />
  </g>
);
export const Heli: React.FC<{x: number; y: number; s?: number; color?: string; spin?: number}> = ({x, y, s = 1.6, color = K.ink, spin = 0}) => (
  <g transform={`translate(${x},${y}) scale(${s})`}>
    <ellipse cx={0} cy={0} rx={6} ry={9} fill={color} />
    <rect x={-1.2} y={8} width={2.4} height={16} fill={color} />
    <rect x={-5} y={22} width={10} height={2} fill={color} />
    <g transform={`rotate(${spin})`}><rect x={-20} y={-1} width={40} height={2} fill={color} opacity={0.8} /><rect x={-1} y={-20} width={2} height={40} fill={color} opacity={0.8} /></g>
  </g>
);
export const Tower: React.FC<{x: number; y: number; color?: string}> = ({x, y, color = K.ink}) => (
  <g transform={`translate(${x},${y})`}>
    <rect x={-16} y={-34} width={32} height={14} fill="none" stroke={color} strokeWidth={2.5} />
    <rect x={-5} y={-20} width={10} height={34} fill={color} />
    <rect x={-14} y={14} width={28} height={3} fill={color} />
  </g>
);
