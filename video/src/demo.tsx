// 38-75 s. One complete flow, live, as a broadcast split screen: the ATC console (left) and the Cessna pilot's
// EFB, the tablet pilots carry in the cockpit (right). Cameras move inside each pane; annotations are pinned to
// the UI through the same camera so they stay on their targets.
import React from "react";
import {AbsoluteFill, Easing, OffthreadVideo, Sequence, staticFile} from "remotion";
import {Annot, FPS, K, PaneLabel, Sub, fadeOut, ramp, useT} from "./ui";
import timeline from "../public/footage/timeline.json";
import audio from "../public/footage/audio.json";
import durs from "../public/data/sfx_dur.json";

// seconds into the console recording of a story beat (scripts/capture_demo_footage.py writes the marks)
const m = (name: string) => {
  const hit = timeline.marks.find((x) => x.beat.startsWith(name));
  if (!hit) throw new Error(`no beat "${name}" in timeline.json`);
  return (hit.t - timeline.starts.console) / 1000;
};

export const D0 = 38, D1 = 75;
type Cam = [number, number, number, number][];
type Shot = {from: number; to: number; src: [number, number]; con: Cam; efb: Cam; dim?: number};

const CON = {x: 40, y: 110, w: 1440, h: 810};                     // console pane, 1920x1080 source
const EFB = {x: 1520, y: 110, w: 810 * (430 / 932), h: 810};        // EFB pane, 430x932 source
const EFB_WIDE = {x: 1000, y: 110, w: 860, h: 810};                 // during the advisory: wider, not zoomed
const efbBox = (t: number) => {
  const p = ramp(t, 52.1, 52.8) * (1 - ramp(t, 60.9, 61.5));
  const l = (a: number, b: number) => a + (b - a) * p;
  return {x: l(EFB.x, EFB_WIDE.x), y: EFB.y, w: l(EFB.w, EFB_WIDE.w), h: EFB.h};
};

const SHOTS: Shot[] = [
  {from: 38, to: 45, src: [m("holding short 33"), m("TALKED OVER")], con: [[38, 1.15, 600, 560], [41.5, 1.45, 330, 520], [44.2, 1.45, 330, 520], [45, 1.75, 960, 1000]], efb: [[38, 1, 215, 466]]},
  {from: 45, to: 52, src: [m("TALKED OVER"), m("controller approves") + 0.25], con: [[45, 1.75, 960, 1000], [47.1, 1.75, 960, 1000], [48.3, 1.9, 1730, 330], [52, 1.9, 1730, 330]], efb: [[45, 1, 215, 466]]},
  {from: 52, to: 61.5, src: [m("controller approves") + 0.25, m("readback of the advisory") + 5.3], con: [[52, 1.0, 960, 540]], efb: [[52, 1, 215, 466], [52.8, 1, 215, 700], [57.2, 1, 215, 700], [58.0, 1, 215, 780], [61.5, 1, 215, 780]], dim: 0.6},
  {from: 61.5, to: 69, src: [m("tower: Cessna 123 line up"), m("readback N123AB corrected") + 0.9], con: [[61.5, 1.15, 900, 560], [66.2, 1.15, 900, 560], [67.1, 1.8, 1730, 330], [69, 1.8, 1730, 330]], efb: [[61.5, 1, 215, 466]]},
  {from: 69, to: 75, src: [m("readback N123AB corrected") + 0.9, m("Plane A airborne") + 0.3], con: [[69, 1.2, 1300, 540], [70.2, 1.8, 1730, 330], [72.6, 1.8, 1730, 330], [73.4, 1.1, 600, 520], [75, 1.15, 600, 520]], efb: [[69, 1, 215, 466]]},
];
// output time of a moment in the recording
export const outOf = (src: number) => {
  const sh = SHOTS.find((x) => src >= x.src[0] && src <= x.src[1]);
  if (!sh) return null;
  return sh.from + ((src - sh.src[0]) * (sh.to - sh.from)) / (sh.src[1] - sh.src[0]);
};
// the room's real sounds that the edit plays: [index in audio.json, volume]
const PICK: [number, number][] = [[3, 1], [4, 0.95], [9, 1.1], [10, 1], [11, 1.1], [13, 1], [15, 0.9]];  // 12 is shown as a caption  // 14 and 16 would talk over 15 in the sped-up shot
// placed where they happened, but never on top of the previous voice (sped-up shots would stack them)
export const DEMO_SOUNDS: [string, number, number][] = (() => {
  const out: [string, number, number][] = [];
  let free = 0;
  for (const [i, v] of PICK) {
    const at = outOf((audio[i].t - timeline.starts.console) / 1000);
    if (at === null) continue;
    const id = audio[i].file.replace("audio/", "").replace(".wav", "");
    const start = i === 4 ? at : Math.max(at, free + 0.15);       // 4 is the helicopter talking over the tower: overlap is the point
    out.push([id, start, v]);
    free = Math.max(free, start + ((durs as Record<string, number>)[id] ?? 3));
  }
  return out;
})();

const camAt = (cam: Cam, t: number) => {
  if (t <= cam[0][0]) return cam[0];
  for (let i = 1; i < cam.length; i++) if (t <= cam[i][0]) {
    const [t0, z0, x0, y0] = cam[i - 1], [t1, z1, x1, y1] = cam[i];
    const k = Easing.inOut(Easing.cubic)((t - t0) / Math.max(0.001, t1 - t0));
    return [t, z0 + (z1 - z0) * k, x0 + (x1 - x0) * k, y0 + (y1 - y0) * k];
  }
  return cam[cam.length - 1];
};
// where a source pixel lands on screen in a pane under its camera
const view = (cam: Cam, t: number, sw: number, sh: number, box: {x: number; y: number; w: number; h: number}) => {
  const [, z, fx, fy] = camAt(cam, t);
  const k = box.w / sw;
  const vw = box.w / (k * z), vh = Math.min(sh, box.h / (k * z));   // the part of the source the pane shows
  const cx = Math.min(Math.max(fx, vw / 2), sw - vw / 2), cy = Math.min(Math.max(fy, vh / 2), sh - vh / 2);
  const ox = cx - vw / 2, oy = cy - vh / 2;
  return {z, k, ox, oy, at: (px: number, py: number) => [box.x + (px - ox) * z * k, box.y + (py - oy) * z * k] as const};
};

const Pane: React.FC<{src: string; sw: number; sh: number; box: typeof CON; cam: Cam; t: number; start: number; rate: number; dim?: number}> =
  ({src, sw, sh, box, cam, t, start, rate, dim = 0}) => {
    const v = view(cam, t, sw, sh, box);
    return (
      <div style={{position: "absolute", left: box.x, top: box.y, width: box.w, height: box.h, overflow: "hidden", outline: `1px solid ${K.hair}`}}>
        <div style={{position: "absolute", width: sw, height: sh, transformOrigin: "0 0", transform: `scale(${v.k * v.z}) translate(${-v.ox}px, ${-v.oy}px)`}}>
          <OffthreadVideo src={staticFile(src)} startFrom={Math.round(start * FPS)} playbackRate={rate} muted style={{width: sw, height: sh}} />
        </div>
        {dim > 0 && <div style={{position: "absolute", inset: 0, background: K.bg, opacity: dim}} />}
      </div>
    );
  };

export const Demo: React.FC = () => {
  const t = useT();
  if (t < D0 || t >= D1) return null;
  const shot = SHOTS.find((s) => t >= s.from && t < s.to)!;
  const rate = (shot.src[1] - shot.src[0]) / (shot.to - shot.from);
  const dim = shot.dim ? shot.dim * ramp(t, shot.from, shot.from + 0.5) * fadeOut(t, shot.to - 0.4, 0.4) : 0;
  const con = (px: number, py: number) => view(shot.con, t, 1920, 1080, CON).at(px, py);
  const efb = (px: number, py: number) => view(shot.efb, t, 430, 932, efbBox(t)).at(px, py);
  const [cessX, cessY] = con(70, 368), [heliX, heliY] = con(340, 380);
  const [toX, toY] = con(1016, 1016), [missX, missY] = con(1660, 292), [whyX, whyY] = con(1640, 360), [okX, okY] = con(1655, 424);
  const [wrongX, wrongY] = con(1640, 296), [nextX, nextY] = con(1640, 202);
  const [advX, advY] = efb(40, 840), [rbX, rbY] = efb(40, 885);
  return (
    <AbsoluteFill style={{background: K.bg, opacity: ramp(t, D0, D0 + 0.3)}}>
      <PaneLabel x={CON.x} y={78} text="ATC CONSOLE · KUNS TOWER · 118.700 · RECORDED LIVE" dot={K.red} />
      <PaneLabel x={efbBox(t).x} y={78} text="COCKPIT · CESSNA 1-2-3 · EFB" dot={K.cyan} />
      {SHOTS.map((s, i) => {
        const r = (s.src[1] - s.src[0]) / (s.to - s.from);
        return (
          <Sequence key={i} from={Math.round(s.from * FPS)} durationInFrames={Math.round((s.to - s.from) * FPS)} layout="none">
            <Pane src="footage/console.mp4" sw={1920} sh={1080} box={CON} cam={s.con} t={t} start={s.src[0]} rate={r} dim={s === shot ? dim : 0} />
            <Pane src="footage/phoneA.mp4" sw={430} sh={932} box={efbBox(t)} cam={s.efb} t={t} start={s.src[0] + (timeline.starts.phoneA - timeline.starts.console) / 1000} rate={r} />
          </Sequence>
        );
      })}
      {/* annotations, pinned through the cameras */}
      <Annot t={t} from={38.7} to={41.4} ax={cessX} ay={cessY} lx={cessX + 120} ly={cessY - 120} color={K.ink} label="CESSNA 1-2-3" body="Holding short of runway 33." w={360} />
      <Annot t={t} from={41.7} to={44.6} ax={heliX} ay={heliY} lx={heliX + 150} ly={heliY + 140} color={K.red} label="HELICOPTER 4-5-6" body="Keys up while the tower is talking." w={380} />
      <Annot t={t} from={45.4} to={51.6} ax={toX} ay={toY} lx={toX - 260} ly={toY - 190} color={K.red} label="OVERLAP DETECTED" body="The Cessna's receiver heard two transmitters at once." w={420} />
      <Annot t={t} from={48.6} to={51.9} ax={missX} ay={missY} lx={missX - 420} ly={missY - 40} color={K.green} label="MOSS · THE CESSNA'S OWN MEMORY" body="Recovered “hold short runway 33” from its clearances." w={420} />
      <Annot t={t} from={49.5} to={51.9} ax={whyX} ay={whyY} lx={whyX - 420} ly={whyY + 110} color={K.amber} label="ELASTIC · FAA RULEBOOK" body="Hold short is restrictive (JO 7110.65 ¶3-7-2): a person decides." w={420} />
      {t >= 51.2 && t < 52 && <svg width={1920} height={1080} style={{position: "absolute", inset: 0}}>
        <circle cx={okX} cy={okY} r={30 + 40 * ramp(t, 51.2, 51.8)} fill="none" stroke={K.green} strokeWidth={3} opacity={1 - ramp(t, 51.4, 51.9)} />
      </svg>}
      <Annot t={t} from={53.6} to={58.0} ax={advX} ay={advY} lx={advX - 260} ly={advY - 220} color={K.magenta} label="CARTESIA SONIC · PRIVATE ADVISORY" body="Spoken only in this cockpit, in the pilot's left ear." w={440} />
      <Annot t={t} from={58.0} to={61.0} ax={rbX} ay={rbY} lx={rbX - 260} ly={rbY - 160} color={K.green} label="CARTESIA INK-2 · READBACK CHECK" body="The reply is transcribed and compared with the instruction." w={440} />
      <Annot t={t} from={67.2} to={68.9} ax={wrongX} ay={wrongY} lx={wrongX - 420} ly={wrongY + 60} color={K.red} label="WRONG READBACK" body="“Runway 13” is not “runway 33”. The aircraft is held." w={420} />
      <Annot t={t} from={(outOf(m("agent proposes takeoff unasked")) ?? 70.6) + 0.3} to={72.8} ax={nextX} ay={nextY} lx={nextX - 420} ly={nextY + 150} color={K.cyan} label="CLEARANCE AGENT · ELASTIC AGENT BUILDER" body="Proposes the next step unasked, from the flight plan, live runway occupancy and the last clearance." w={430} />

      <Sub t={t} from={38.3} to={41.6} tag="LIVE DEMO · JOB 02 · CATCH A STEPPED-ON CALL" tagColor={K.cyan} text="“Cessna 1-2-3, hold short runway 33.”" />
      <Sub t={t} from={41.7} to={44.9} text="At the same moment, the helicopter keys up." />
      <Sub t={t} from={45.2} to={48.4} tag="UNSTEP" tagColor={K.cyan} text="The Cessna's radio carried two voices. Unstep flags it and recovers the call." />
      <Sub t={t} from={48.5} to={51.9} text="Hold short is safety-critical, so the controller decides. One tap: approve." />
      <Sub t={t} from={52.3} to={57.8} tag="JOB 05 · SPEAK TO ONE PILOT" tagColor={K.cyan} text="Only the Cessna hears the recovered call, in the pilot's left ear." />
      <Sub t={t} from={57.9} to={61.3} text="The pilot reads it back. Unstep checks it: correct." />
      <Sub t={t} from={61.6} to={65.0} tag="JOB 03 · CHECK EVERY READBACK" tagColor={K.cyan} text="A new clearance: “Cessna 1-2-3, line up and wait runway 33.”" />
      <Sub t={t} from={65.1} to={68.9} text="The readback says “runway 13.” Flagged, and the aircraft stays put." />
      <Sub t={t} from={69.1} to={72.8} tag="JOB 04 · DRAFT THE NEXT CLEARANCE" tagColor={K.cyan} text="Lined up, runway clear: the agent proposes the next step on its own." />
      <Sub t={t} from={72.9} to={74.8} text="Sent. Read back. Airborne." />
    </AbsoluteFill>
  );
};
