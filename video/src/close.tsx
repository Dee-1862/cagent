// 110-120 s. The principle, then the name rising from the same cyan line the title used.
import React from "react";
import {AbsoluteFill} from "remotion";
import {K, b612, head, mono, ramp, useT} from "./ui";

export const C0 = 110;

export const Close: React.FC = () => {
  const t = useT();
  if (t < C0) return null;
  const end = t >= 114.4;
  const wipe = (a: number, b: number) => `inset(0 ${(1 - ramp(t, a, b)) * 100}% 0 0)`;
  return (
    <AbsoluteFill style={{background: K.bg, opacity: ramp(t, C0, C0 + 0.3)}}>
      {!end && (
        <div style={{position: "absolute", left: 160, top: 300, opacity: 1 - ramp(t, 114.0, 114.4)}}>
          <div style={{fontFamily: head, fontWeight: 800, fontSize: 132, letterSpacing: -4, lineHeight: 1.02, color: K.ink, clipPath: wipe(110.2, 110.8)}}>Agents propose.</div>
          <div style={{fontFamily: head, fontWeight: 800, fontSize: 132, letterSpacing: -4, lineHeight: 1.02, color: K.cyan, clipPath: wipe(110.9, 111.5)}}>Controllers decide.</div>
        </div>
      )}
      {end && (
        <>
          <svg width={1920} height={1080} style={{position: "absolute", inset: 0}}>
            <rect x={170} y={759} width={1580 * ramp(t, 114.4, 115.1)} height={2} fill={K.cyan} />
          </svg>
          <div style={{position: "absolute", left: 162, top: 546, height: 268, overflow: "hidden"}}>
            <div style={{fontFamily: head, fontWeight: 800, fontSize: 228, letterSpacing: -7, color: K.ink, lineHeight: 0.92, transform: `translateY(${(1 - ramp(t, 114.9, 115.6)) * 268}px)`}}>Unstep</div>
          </div>
          <div style={{position: "absolute", left: 170, top: 794, fontFamily: b612, fontSize: 36, color: K.ink, clipPath: wipe(115.6, 116.2)}}>Every call, heard.</div>
          <div style={{position: "absolute", left: 170, top: 868, fontFamily: mono, fontSize: 19, color: K.dim, opacity: ramp(t, 116.4, 116.9)}}>
            CARTESIA · MOSS · ELASTIC — CAL HACKS 13.0
          </div>
          <div style={{position: "absolute", left: 170, bottom: 42, fontFamily: mono, fontSize: 14, color: "#4A515A", opacity: ramp(t, 116.8, 117.3)}}>
            News footage: ABC News and local news reports · Music: ArctSound, Pastichio_Piano_Music (Pixabay) · 3D aircraft: Poly Pizza (CC-BY)
          </div>
        </>
      )}
    </AbsoluteFill>
  );
};
