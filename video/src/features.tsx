// What we used, sponsor by sponsor: every feature, what it does in Unstep, and the number we measured.
import React from "react";
import {AbsoluteFill} from "remotion";
import {K, b612, fadeOut, head, mono, ramp, useT} from "./ui";

export const F0 = 147.8, F1 = 170.8;
type Row = [string, string, string];
const D = (F1 - F0) / 3;
const SHEETS: {from: number; to: number; name: string; role: string; rows: Row[]; why: string}[] = [
  {from: F0, to: F0 + D, name: "Cartesia", role: "The ears and the voice", rows: [
    ["Ink-2 streaming speech-to-text", "Transcribes the tower and every cockpit while they talk", "final words 155 ms after release"],
    ["Key-term prompting", "39 aviation terms per cockpit: callsigns, runways, taxiways, “niner”, “hold short”", "heavy noise: callsigns 62.5% → 95.5%, runways 81.6% → 98.5%"],
    ["Sonic text-to-speech", "Speaks the recovered call to one pilot, left ear only", "first audio 86–201 ms"],
    ["Same voice, other languages", "The advisory repeated in Spanish, Hindi or French", "checked live"],
    ["Pronunciation dictionary · speed", "ATC words said the ATC way; corrections spoken slower", "0.85× for corrections"],
    ["Live captions · interruption", "Captions on every screen; the advisory stops when the pilot keys the mic", "captions 97 ms after release"],
  ], why: "Why Cartesia: on a radio, everything is voice. Tested on 200 transmissions through a simulated VHF channel, three voices, several noise levels."},
  {from: F0 + D, to: F0 + 2 * D, name: "Moss", role: "Each aircraft's memory", rows: [
    ["One in-process session per aircraft", "Every clearance and call a plane hears is indexed in its own memory, on board", "6 sessions · 0.2–0.4 ms reads"],
    ["Hybrid search", "The scrap the pilot did hear finds the full instruction, by meaning and by exact words", "right clearance 1.0 · unrelated speech 0.0"],
    ["Metadata filters · sorting", "Only this aircraft, only tower calls, newest first: the Clearance agent's “last call”", "0.56 ms"],
    ["Ask your memory, by voice", "“What was my last clearance?” answered from Moss and spoken by Sonic", "under 1 ms"],
    ["Save to disk · load on restart", "The memory survives a restart without downloading anything", "restored in 21 ms"],
    ["Moss Cloud sync", "Each finished flight's log is pushed to the cloud", "survives restarts, verified live"],
  ], why: "Why Moss: the cockpit already heard half the call. Moss finds the rest in the aircraft's own memory, in under a millisecond, without leaving the plane."},
  {from: F0 + 2 * D, to: F1, name: "Elastic", role: "The agent platform, on Serverless", rows: [
    ["Agent Builder", "8 agents: Intercept, Compliance, Ground, Readback Auditor, Audit, Coach and two fast variants", "configured over our own indexes"],
    ["Workflows", "Agents run in parallel on every stepped-on call; a shift briefing every 8 h; a nightly review", "7 workflows, event-driven and scheduled"],
    ["Percolator rules", "Each instruction and readback matched to its FAA rule (JO 7110.65, the controller's rulebook)", "readback matched in 3 ms"],
    ["Hybrid search · Jina rerank", "Finds the exact FAA paragraph to cite on every decision card", "reranked citation in ~1 s"],
    ["geo_shape · flight plans · Kibana Maps", "“Is the runway clear?” from live positions; the Clearance agent's plan; incursions flagged; a live map", "1 ms"],
    ["ES|QL · MCP", "Safety analytics and the audit trail, asked in plain English; tools exposed over MCP", "every decision auditable"],
  ], why: "Why Elastic: the rulebook, the flight plans, the airport map and every decision live in one place, and the agents act on them."},
];

export const Features: React.FC = () => {
  const t = useT();
  if (t < F0 || t >= F1) return null;
  const sh = SHEETS.find((s) => t >= s.from && t < s.to)!;
  return (
    <AbsoluteFill style={{background: K.bg}}>
      <div key={sh.name} style={{position: "absolute", inset: 0, opacity: ramp(t, sh.from, sh.from + 0.3) * fadeOut(t, sh.to - 0.25, 0.25)}}>
        <div style={{position: "absolute", left: 120, top: 84, fontFamily: mono, fontSize: 18, color: K.dim}}>WHAT WE USED · {sh.role.toUpperCase()}</div>
        <div style={{position: "absolute", left: 120, top: 116, fontFamily: head, fontWeight: 800, fontSize: 96, letterSpacing: -3, color: K.ink,
          clipPath: `inset(0 ${(1 - ramp(t, sh.from + 0.1, sh.from + 0.6)) * 100}% 0 0)`}}>{sh.name}</div>
        <div style={{position: "absolute", left: 120, top: 270, width: 1680}}>
          <div style={{display: "grid", gridTemplateColumns: "470px 1fr 470px", padding: "0 0 10px", fontFamily: mono, fontSize: 15, color: K.dim, opacity: ramp(t, sh.from + 0.4, sh.from + 0.7)}}>
            <div>FEATURE</div><div>WHAT IT DOES IN UNSTEP</div><div>MEASURED</div>
          </div>
          {sh.rows.map(([f, what, num], i) => {
            const p = ramp(t, sh.from + 0.55 + i * 0.32, sh.from + 0.9 + i * 0.32);
            return (
              <div key={i} style={{display: "grid", gridTemplateColumns: "470px 1fr 470px", alignItems: "baseline", padding: "17px 0", borderTop: `1px solid ${K.hair}`,
                opacity: p, transform: `translateY(${(1 - p) * 12}px)`}}>
                <div style={{fontFamily: b612, fontWeight: 700, fontSize: 25, color: K.ink, paddingRight: 24}}>{f}</div>
                <div style={{fontFamily: b612, fontSize: 23, color: "#C9CED4", lineHeight: 1.35, paddingRight: 30}}>{what}</div>
                <div style={{fontFamily: mono, fontSize: 19, color: K.cyan, lineHeight: 1.4}}>{num}</div>
              </div>
            );
          })}
          <div style={{borderTop: `1px solid ${K.hair}`, paddingTop: 18, fontFamily: b612, fontSize: 22, color: K.ink, lineHeight: 1.4, opacity: ramp(t, sh.from + 2.6, sh.from + 3.0)}}>{sh.why}</div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
