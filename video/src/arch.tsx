// 75-110 s. How it works: the real pipeline as a flowchart. One stepped-on call (magenta) travels from the
// Cessna's radio through the cockpit, the ground hub and back; the tower's own transcript (cyan) joins it.
// The camera visits each stage while the sidebar says, in plain words, what each sponsor does and why.
import React from "react";
import {AbsoluteFill, Easing, interpolate} from "remotion";
import {K, b612, fadeOut, head, mono, ramp, useT} from "./ui";

export const A0 = 75, A1 = 110;
type P = [number, number];
const NW = 300, NH = 84;

const N: Record<string, {x: number; y: number; label: string; sub: string; tag?: string}> = {
  tower: {x: 520, y: 150, label: "TOWER MICROPHONE", sub: "the controller"},
  cessna: {x: 900, y: 150, label: "CESSNA 1-2-3 RADIO", sub: "receives 118.700"},
  heli: {x: 1280, y: 150, label: "HELICOPTER 4-5-6", sub: "keys up at the same time"},
  overlap: {x: 520, y: 470, label: "OVERLAP DETECTOR", sub: "squeal + timing on board"},
  inkc: {x: 900, y: 470, label: "INK-2", sub: "what the cockpit heard", tag: "CARTESIA"},
  moss: {x: 1280, y: 470, label: "AIRCRAFT MEMORY", sub: "its own clearances", tag: "MOSS"},
  rec: {x: 1660, y: 470, label: "RECOVERED", sub: "“hold short runway 33”"},
  cloud: {x: 2080, y: 470, label: "MOSS CLOUD", sub: "flight log, on landing", tag: "MOSS"},
  inkt: {x: 520, y: 800, label: "INK-2", sub: "tower transcript · key terms", tag: "CARTESIA"},
  rules: {x: 900, y: 800, label: "RULES · PERCOLATOR", sub: "FAA JO 7110.65", tag: "ELASTIC"},
  wf: {x: 1280, y: 800, label: "WORKFLOW", sub: "Intercept ‖ Compliance agents", tag: "ELASTIC AGENT BUILDER"},
  ctrl: {x: 1660, y: 800, label: "CONTROLLER", sub: "approves · one tap"},
  audit: {x: 2080, y: 800, label: "AUDIT · ES|QL", sub: "every decision, queryable", tag: "ELASTIC"},
  sonic: {x: 1660, y: 1140, label: "SONIC", sub: "private advisory · left ear", tag: "CARTESIA"},
  rb: {x: 1280, y: 1140, label: "PILOT READBACK", sub: "spoken reply"},
  check: {x: 900, y: 1140, label: "READBACK CHECK", sub: "Ink-2 vs the instruction", tag: "CARTESIA"},
  move: {x: 520, y: 1140, label: "AIRCRAFT MAY MOVE", sub: "only after a correct readback"},
  clear: {x: 2080, y: 1140, label: "CLEARANCE AGENT", sub: "flight plan · geo · memory", tag: "ELASTIC AGENT BUILDER"},
};
const L = (k: string) => [N[k].x - NW / 2, N[k].y] as P, R = (k: string) => [N[k].x + NW / 2, N[k].y] as P;
const T = (k: string) => [N[k].x, N[k].y - NH / 2] as P, B = (k: string) => [N[k].x, N[k].y + NH / 2] as P;

// edges as polylines; dashed ones are supporting paths
const E: Record<string, {pts: P[]; dash?: boolean}> = {
  bus: {pts: [[400, 270], [1400, 270]]},
  tower_bus: {pts: [B("tower"), [520, 270]]}, cessna_bus: {pts: [B("cessna"), [900, 270]]}, heli_bus: {pts: [B("heli"), [1280, 270]]},
  bus_overlap: {pts: [[900, 270], [900, 350], [520, 350], T("overlap")]},
  overlap_inkc: {pts: [R("overlap"), L("inkc")]}, inkc_moss: {pts: [R("inkc"), L("moss")]}, moss_rec: {pts: [R("moss"), L("rec")]},
  moss_cloud: {pts: [T("moss"), [1280, 380], [2080, 380], T("cloud")], dash: true},
  tower_inkt: {pts: [L("tower"), [300, 150], [300, 800], L("inkt")]},
  inkt_rules: {pts: [R("inkt"), L("rules")]}, rules_wf: {pts: [R("rules"), L("wf")]},
  rec_wf: {pts: [B("rec"), [1660, 640], [1280, 640], T("wf")]},
  wf_ctrl: {pts: [R("wf"), L("ctrl")]}, ctrl_audit: {pts: [R("ctrl"), L("audit")], dash: true},
  clear_ctrl: {pts: [T("clear"), [2080, 990], [1760, 990], [1760, 842]], dash: true},
  ctrl_sonic: {pts: [B("ctrl"), T("sonic")]},
  sonic_rb: {pts: [L("sonic"), R("rb")]}, rb_check: {pts: [L("rb"), R("check")]}, check_move: {pts: [L("check"), R("move")]},
};
const plen = (pts: P[]) => pts.slice(1).reduce((a, p, i) => a + Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]), 0);
const along = (pts: P[], f: number): P => {
  let d = plen(pts) * Math.min(Math.max(f, 0), 1);
  for (let i = 1; i < pts.length; i++) {
    const s = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    if (d <= s) return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * (d / s), pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * (d / s)];
    d -= s;
  }
  return pts[pts.length - 1];
};

// the magenta call: [edge, start, end]
const RUN: [string, number, number][] = [
  ["cessna_bus", 77.2, 77.6], ["bus_overlap", 77.6, 78.5], ["overlap_inkc", 78.6, 79.2], ["inkc_moss", 84.3, 85.1], ["moss_rec", 86.2, 86.9],
  ["rec_wf", 91.3, 92.4], ["wf_ctrl", 100.6, 101.3], ["ctrl_sonic", 101.9, 102.6], ["sonic_rb", 103.0, 103.7], ["rb_check", 104.0, 104.6], ["check_move", 104.9, 105.5],
];
const TOWER_RUN: [string, number, number][] = [["tower_inkt", 77.4, 79.0], ["inkt_rules", 91.3, 91.9], ["rules_wf", 92.4, 93.0]];
const LIT: Record<string, number> = {cessna: 77.2, heli: 77.2, tower: 77.4, overlap: 78.5, inkc: 79.2, inkt: 79.0, moss: 85.1, rec: 86.9, cloud: 88.4,
  rules: 91.9, wf: 93.0, audit: 96.6, clear: 98.0, ctrl: 101.3, sonic: 102.6, rb: 103.7, check: 104.6, move: 105.5};

// camera: [t, scale (screen px per diagram unit), focus x, focus y]; the diagram area is the left 1300 px
const CAM: [number, number, number, number][] = [
  [75, 0.54, 1200, 650], [76.6, 0.54, 1200, 650], [77.6, 0.88, 760, 470], [83.4, 0.88, 760, 470],
  [84.4, 0.88, 1480, 430], [90.4, 0.88, 1480, 430], [91.4, 0.78, 1350, 830], [99.8, 0.78, 1350, 830],
  [100.8, 0.8, 1180, 1000], [105.6, 0.8, 1180, 1000], [106.6, 0.54, 1200, 650], [110, 0.54, 1200, 650],
];
const camAt = (t: number) => {
  for (let i = 1; i < CAM.length; i++) if (t <= CAM[i][0]) {
    const [t0, s0, x0, y0] = CAM[i - 1], [t1, s1, x1, y1] = CAM[i];
    const k = Easing.inOut(Easing.cubic)(Math.min(1, Math.max(0, (t - t0) / (t1 - t0))));
    return [s0 + (s1 - s0) * k, x0 + (x1 - x0) * k, y0 + (y1 - y0) * k];
  }
  return CAM[CAM.length - 1].slice(1);
};

// sidebar copy, one stage at a time
const STAGES: {from: number; to: number; step: string; name: string; lead: string; points: [number, string][]; why?: string}[] = [
  {from: 75.2, to: 77.4, step: "HOW IT WORKS", name: "One call, end to end", lead: "The stepped-on “hold short” from the demo, through the real system.", points: []},
  {from: 77.6, to: 83.8, step: "01 · HEAR", name: "Cartesia Ink-2", lead: "Listens to every radio, live.", points: [
    [78.4, "Turns the tower and every cockpit into text while they talk."],
    [79.6, "Tuned for airport words: runway numbers, taxiways, “niner”."],
    [80.8, "The words arrive about 150 ms after the speaker lets go of the mic."]],
    why: "Why Cartesia: on a radio, everything is voice. Every later step starts from these words."},
  {from: 84.4, to: 90.8, step: "02 · RECALL", name: "Moss", lead: "Each aircraft remembers what it was told.", points: [
    [85.0, "Every instruction an aircraft receives is kept in its own memory, on board."],
    [86.3, "The Cessna only caught “…runway 3…”. Moss searches its memory with that scrap and finds “hold short runway 33”."],
    [88.0, "It takes 0.56 milliseconds, with no internet round trip in the way."]]},
  {from: 91.4, to: 100.2, step: "03 · CHECK", name: "Elastic Agent Builder", lead: "The rulebook and the agents.", points: [
    [92.0, "The controller's rulebook (FAA Order JO 7110.65) lives in Elastic, and each instruction is matched to its rule."],
    [93.8, "AI agents built in Elastic Agent Builder run side by side: one confirms the tower really said it, one cites the rule."],
    [95.8, "Every decision is logged, so anyone can audit it later."],
    [97.4, "Another agent asks “is the runway clear?” using live aircraft positions. Answer in 1 ms."]]},
  {from: 100.8, to: 106.0, step: "04 · DECIDE, THEN SPEAK", name: "Controller → Cartesia Sonic", lead: "A person approves. One pilot hears it.", points: [
    [101.4, "Nothing reaches a pilot without the controller's tap."],
    [102.6, "Sonic speaks it in that cockpit only, in the pilot's left ear, within 141 ms."],
    [103.9, "The pilot's readback is checked before the aircraft may move."]]},
];

export const Arch: React.FC = () => {
  const t = useT();
  if (t < A0 || t > A1) return null;
  const [s, fx, fy] = camAt(t);
  const tx = 650 - fx * s, ty = 540 - fy * s;
  const draw = ramp(t, A0 + 0.1, A0 + 1.6);
  const lit = (k: string) => t >= (LIT[k] ?? 999);
  const runOf = (run: [string, number, number][], color: string) => run.map(([e, a, b]) => {
    const pts = E[e].pts, len = plen(pts), p = ramp(t, a, b, Easing.inOut(Easing.quad));
    if (t < a) return null;
    const [px, py] = along(pts, p);
    return (
      <g key={`${color}-${e}`}>
        <polyline points={pts.map((q) => q.join(",")).join(" ")} fill="none" stroke={color} strokeWidth={3.5} strokeDasharray={len} strokeDashoffset={len * (1 - p)} />
        {p < 1 && <rect x={px - 9} y={py - 9} width={18} height={18} fill={color} />}
      </g>
    );
  });
  const final = ramp(t, 106.6, 107.4);
  return (
    <AbsoluteFill style={{background: K.bg, opacity: ramp(t, A0, A0 + 0.3) * fadeOut(t, A1 - 0.3)}}>
      <div style={{position: "absolute", left: 0, top: 0, width: 1300, height: 1080, overflow: "hidden",
        maskImage: "linear-gradient(90deg, transparent 0, black 70px, black 1150px, transparent 1290px), linear-gradient(180deg, transparent 0, black 60px, black 1010px, transparent 1080px)",
        maskComposite: "intersect", WebkitMaskComposite: "source-in"} as React.CSSProperties}>
        <svg width={1300} height={1080}>
          <g transform={`translate(${tx},${ty}) scale(${s})`}>
            {/* lanes */}
            {[["RADIO · 118.700 MHZ", 150], ["COCKPIT · ON BOARD", 470], ["GROUND · ATC HUB", 800], ["BACK TO THE COCKPIT", 1140]].map(([name, y], i) => (
              <g key={i} opacity={draw}>
                <text x={20} y={(y as number) - 60} fill={K.dim} fontFamily={mono} fontSize={22}>{name}</text>
                {i > 0 && <line x1={0} y1={(y as number) - 110} x2={2300} y2={(y as number) - 110} stroke={K.hair} strokeDasharray="4 10" />}
              </g>
            ))}
            {Object.entries(E).map(([k, e]) => {
              const len = plen(e.pts);
              return <polyline key={k} points={e.pts.map((q) => q.join(",")).join(" ")} fill="none" stroke={K.hair} strokeWidth={2}
                strokeDasharray={e.dash ? "8 8" : `${len}`} strokeDashoffset={e.dash ? 0 : len * (1 - draw)} opacity={e.dash ? draw : 1} />;
            })}
            <text x={1410} y={276} fill={K.dim} fontFamily={mono} fontSize={18} opacity={draw}>118.700 SHARED</text>
            {runOf(TOWER_RUN, K.cyan)}
            {runOf(RUN, K.magenta)}
            {Object.entries(N).map(([k, n], i) => {
              const on = lit(k), appear = ramp(t, A0 + 0.2 + i * 0.05, A0 + 0.7 + i * 0.05);
              const sideHot = (k === "cloud" || k === "audit" || k === "clear") && on;
              const col = k === "heli" && on ? K.red : on ? (k === "move" || k === "ctrl" ? K.green : sideHot ? K.cyan : K.magenta) : K.hair;
              return (
                <g key={k} opacity={appear}>
                  {n.tag && <text x={n.x - NW / 2} y={n.y - NH / 2 - 12} fill={K.dim} fontFamily={mono} fontSize={16}>{n.tag}</text>}
                  <rect x={n.x - NW / 2} y={n.y - NH / 2} width={NW} height={NH} fill={K.bg} stroke={col} strokeWidth={on ? 3 : 1.5} />
                  <text x={n.x - NW / 2 + 18} y={n.y - 6} fill={on ? K.ink : K.dim} fontFamily={mono} fontWeight={700} fontSize={22}>{n.label}</text>
                  <text x={n.x - NW / 2 + 18} y={n.y + 24} fill={K.dim} fontFamily={b612} fontSize={17}>{n.sub}</text>
                </g>
              );
            })}
            {/* the two agents inside the workflow, side by side */}
            {[["INTERCEPT ✓ the tower said it", 93.6, 870], ["COMPLIANCE ✓ ¶3-7-2, restrictive", 94.4, 905]].map(([txt, at, y], i) => (
              <text key={i} x={N.wf.x - NW / 2} y={y as number} fill={K.green} fontFamily={mono} fontSize={18} opacity={ramp(t, at as number, (at as number) + 0.3)}>{txt}</text>
            ))}
            {t >= 101.3 && <text x={N.ctrl.x - NW / 2} y={N.ctrl.y + 72} fill={K.green} fontFamily={mono} fontSize={18}>APPROVED</text>}
            {t >= 97.4 && <text x={N.clear.x - NW / 2} y={N.clear.y + 72} fill={K.cyan} fontFamily={mono} fontSize={18} opacity={ramp(t, 97.4, 97.8)}>RUNWAY CLEAR · geo_shape 1 ms</text>}
            {t >= 87.9 && <text x={N.moss.x - NW / 2} y={N.moss.y + 72} fill={K.magenta} fontFamily={mono} fontSize={18} opacity={ramp(t, 87.9, 88.3)}>MATCH · 0.56 ms</text>}
          </g>
        </svg>
      </div>

      {/* sidebar */}
      <div style={{position: "absolute", left: 1320, top: 0, width: 1, height: 1080, background: K.hair}} />
      {STAGES.map((st, i) => {
        if (t < st.from || t > st.to + 0.3) return null;
        const p = ramp(t, st.from, st.from + 0.45);
        return (
          <div key={i} style={{position: "absolute", left: 1370, top: 150, width: 470, opacity: fadeOut(t, st.to), clipPath: `inset(0 ${(1 - p) * 100}% 0 0)`}}>
            <div style={{fontFamily: mono, fontSize: 18, color: K.dim}}>{st.step}</div>
            <div style={{fontFamily: head, fontWeight: 700, fontSize: 52, color: K.ink, marginTop: 14, lineHeight: 1.05, letterSpacing: -1}}>{st.name}</div>
            <div style={{fontFamily: b612, fontSize: 25, color: K.ink, marginTop: 18, lineHeight: 1.35}}>{st.lead}</div>
            <div style={{marginTop: 30}}>
              {st.points.map(([at, txt], j) => (
                <div key={j} style={{display: "flex", gap: 14, marginBottom: 20, opacity: ramp(t, at, at + 0.35), transform: `translateY(${(1 - ramp(t, at, at + 0.35)) * 10}px)`}}>
                  <div style={{width: 10, height: 2, background: K.magenta, marginTop: 13, flex: "none"}} />
                  <div style={{fontFamily: b612, fontSize: 21, color: "#C9CED4", lineHeight: 1.4}}>{txt}</div>
                </div>
              ))}
            </div>
            {st.why && <div style={{fontFamily: b612, fontSize: 19, color: K.dim, borderTop: `1px solid ${K.hair}`, paddingTop: 16, lineHeight: 1.45, opacity: ramp(t, st.from + 3.2, st.from + 3.6)}}>{st.why}</div>}
          </div>
        );
      })}
      {t >= 106.4 && (
        <div style={{position: "absolute", left: 1370, top: 280, width: 470, opacity: final}}>
          <div style={{fontFamily: mono, fontSize: 18, color: K.dim}}>MEASURED LIVE</div>
          <div style={{fontFamily: head, fontWeight: 800, fontSize: 170, color: K.ink, letterSpacing: -6, lineHeight: 1, marginTop: 10}}>2.9 s</div>
          <div style={{fontFamily: b612, fontSize: 24, color: K.ink, marginTop: 18, lineHeight: 1.4}}>From the end of the stepped-on call to the pilot hearing the fix, with the controller's approval included.</div>
        </div>
      )}
    </AbsoluteFill>
  );
};
