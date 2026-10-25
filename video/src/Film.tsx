// The film: each section is written on its own clock and placed here on the timeline (2:26).
import React from "react";
import {AbsoluteFill, Audio, OffthreadVideo, Sequence, interpolate, staticFile} from "remotion";
import {FPS, K, Remap, Seg, toFilm} from "./ui";
import {T0, Title} from "./title";
import {Why} from "./why";
import {DEMO_SOUNDS, Demo} from "./demo";
import {Arch} from "./arch";
import {Close} from "./close";
import {Context, NEWS, X1 as CONTEXT_END} from "./context";
import {Jobs} from "./jobs";
import {Features} from "./features";

export const TOTAL = 178.3;
const at = (sec: number) => Math.round(sec * FPS);

// where each section sits: [film from, film to, section from, section to]
const TITLE: Seg[] = [[CONTEXT_END, 43.8, 15.0, 22.8]];
const WHY: Seg[] = [[63.8, 78.8, 23, 38]];      // after "what Unstep does": one job up close
const DEMO_SHIFT = 40.8;                        // the demo at real speed: 38-75 on its clock = 78.8-115.8
const ARCH: Seg[] = [[115.8, 147.8, 75, 110]];
const CLOSE: Seg[] = [[170.8, 178.3, 110, 120]];
const BED: [number, number] = [15.3, 79.6];     // documentary piano under the story
export const SCORE_AT = 78.8;                   // the pulse enters with the live demo

// sounds: [file, start s on the film, volume]
const SOUNDS: [string, number, number][] = [
  ["title_collision", toFilm(TITLE, T0), 1],
  ["squelch", toFilm(TITLE, 19.25), 0.6],
  ["003", toFilm(WHY, 24.0), 0.95],             // tower: "Cessna 1-2-3, hold short runway 33"
  ["004", toFilm(WHY, 25.4), 0.9],              // helicopter keys up over it
  ["boom", toFilm(WHY, 30.15), 0.9],            // incursion
  ["squelch", toFilm(WHY, 31.5), 0.5],          // rewind
  ["squelch", toFilm(WHY, 34.5), 0.5],          // Unstep tells the Cessna
  ...DEMO_SOUNDS.map(([f, s, v]) => [f, s + DEMO_SHIFT, v] as [string, number, number]),
  ["boom", ARCH[0][0] - 0.05, 0.55],            // into how it works
  ["squelch", toFilm(ARCH, 77.6), 0.35], ["squelch", toFilm(ARCH, 84.4), 0.3], ["squelch", toFilm(ARCH, 91.4), 0.3], ["squelch", toFilm(ARCH, 100.8), 0.3],
  ["boom", toFilm(CLOSE, 114.35), 0.7],         // the name
  ["boom", 43.75, 0.5],                         // what Unstep does
  ...[0, 1, 2, 3, 4, 5].map((i) => ["squelch", 46.4 + i * 1.9, 0.28] as [string, number, number]),
  ["boom", 147.75, 0.5], ["squelch", 155.47, 0.35], ["squelch", 163.13, 0.35],   // what we used
];
// windows where speech plays and the music steps back
const SPEECH: [number, number][] = [[NEWS[0], NEWS[1]], ...SOUNDS.filter(([f]) => /^\d{3}$/.test(f)).map(([, s]) => [s, s + 4] as [number, number])];
const duck = (sec: number) => (SPEECH.some(([a, b]) => sec >= a && sec < b) ? 0.4 : 1);
const clampOpts = {extrapolateLeft: "clamp", extrapolateRight: "clamp"} as const;

export const Film: React.FC = () => (
  <AbsoluteFill style={{background: K.bg}}>
    <Sequence durationInFrames={at(15)}><OffthreadVideo src={staticFile("segment1.mp4")} /></Sequence>
    <Context />
    <Remap segs={TITLE}><Title /></Remap>
    <Jobs />
    <Remap segs={WHY}><Why /></Remap>
    <Sequence from={at(DEMO_SHIFT)} layout="none"><Demo /></Sequence>
    <Remap segs={ARCH}><Arch /></Remap>
    <Features />
    <Remap segs={CLOSE}><Close /></Remap>

    <Sequence from={at(BED[0])} durationInFrames={at(BED[1] - BED[0])}>
      <Audio src={staticFile("audio/bed.mp3")} volume={(f) => {
        const sec = BED[0] + f / FPS;
        return 0.55 * duck(sec) * interpolate(sec, [BED[0], BED[0] + 1.5, BED[1] - 1.3, BED[1]], [0, 1, 1, 0], clampOpts);
      }} />
    </Sequence>
    <Sequence from={at(SCORE_AT)}>
      <Audio src={staticFile("audio/score_long.wav")} volume={(f) => 0.5 * duck(SCORE_AT + f / FPS) * interpolate(SCORE_AT + f / FPS, [SCORE_AT, SCORE_AT + 1.2], [0, 1], clampOpts)} />
    </Sequence>
    {SOUNDS.map(([f, s, v], i) => (
      <Sequence key={i} from={at(s)}><Audio src={staticFile(`sfx/${f}.wav`)} volume={v} /></Sequence>
    ))}
  </AbsoluteFill>
);
