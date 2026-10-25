// What Unstep does, before any detail: a team of AI agents that works the radio with the controller.
// Six jobs, each with the sponsor that powers it; the controller approves everything.
import React from "react";
import {AbsoluteFill} from "remotion";
import {K, b612, fadeOut, head, mono, ramp, useT} from "./ui";

export const J0 = 43.8, J1 = 63.8;

export const JOBS: [string, string, string, string][] = [
  ["01", "Listens", "to every transmission, tower and cockpit, as live text.", "CARTESIA INK-2"],
  ["02", "Catches", "calls that were stepped on, and recovers the words that were lost.", "MOSS · CARTESIA"],
  ["03", "Checks", "every readback. A wrong runway is flagged before anyone moves.", "CARTESIA · ELASTIC"],
  ["04", "Drafts", "the next clearance from the flight plan and live runway status.", "ELASTIC AGENT BUILDER"],
  ["05", "Speaks", "privately to one pilot, in their ear and in their language.", "CARTESIA SONIC"],
  ["06", "Records", "every decision for audit, and writes the shift briefing.", "ELASTIC"],
];
const ROW0 = 46.4, STEP = 1.9;

export const Jobs: React.FC = () => {
  const t = useT();
  if (t < J0 || t >= J1) return null;
  const active = Math.min(JOBS.length - 1, Math.max(0, Math.floor((t - ROW0) / STEP)));
  const all = t >= ROW0 + JOBS.length * STEP;
  return (
    <AbsoluteFill style={{background: K.bg, opacity: ramp(t, J0, J0 + 0.3) * fadeOut(t, J1 - 0.3, 0.3)}}>
      <div style={{position: "absolute", left: 160, top: 96, fontFamily: mono, fontSize: 18, color: K.dim}}>WHAT UNSTEP DOES</div>
      <div style={{position: "absolute", left: 160, top: 136, width: 1500, fontFamily: head, fontWeight: 700, fontSize: 54, lineHeight: 1.12, letterSpacing: -1.2, color: K.ink,
        clipPath: `inset(0 ${(1 - ramp(t, J0 + 0.3, J0 + 0.9)) * 100}% 0 0)`}}>
        A team of AI agents that works the radio <span style={{color: K.cyan}}>with</span> the controller.
      </div>
      <div style={{position: "absolute", left: 160, top: 280, width: 1600}}>
        {JOBS.map(([n, verb, rest, who], i) => {
          const at = ROW0 + i * STEP, p = ramp(t, at, at + 0.4);
          const lit = all || i === active;
          return (
            <div key={n} style={{display: "grid", gridTemplateColumns: "70px 290px 1fr 270px", alignItems: "baseline", padding: "20px 0",
              borderTop: `1px solid ${K.hair}`, opacity: p * (lit ? 1 : 0.45), transform: `translateY(${(1 - p) * 14}px)`}}>
              <div style={{fontFamily: mono, fontSize: 20, color: K.dim}}>{n}</div>
              <div style={{fontFamily: head, fontWeight: 700, fontSize: 48, letterSpacing: -1, color: lit && !all ? K.cyan : K.ink}}>{verb}</div>
              <div style={{fontFamily: b612, fontSize: 25, color: "#C9CED4", lineHeight: 1.35, paddingRight: 20, whiteSpace: "nowrap"}}>{rest}</div>
              <div style={{fontFamily: mono, fontSize: 16, color: K.dim, textAlign: "right"}}>{who}</div>
            </div>
          );
        })}
      </div>
      <div style={{position: "absolute", left: 160, bottom: 80, fontFamily: head, fontWeight: 600, fontSize: 40, color: K.ink,
        clipPath: `inset(0 ${(1 - ramp(t, ROW0 + JOBS.length * STEP + 0.3, ROW0 + JOBS.length * STEP + 0.9)) * 100}% 0 0)`}}>
        The controller approves everything. <span style={{color: K.dim}}>The agents never act alone.</span>
      </div>
    </AbsoluteFill>
  );
};
