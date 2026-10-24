import { describe, expect, it } from "vitest";
import { addCaption, addLevel, addOverlap, empty, prune, streamStart, wordTimes, xOf } from "./wave";

describe("radio waveform state", () => {
  it("bars land at their hub time, 50 ms apart", () => {
    const w = addLevel(empty(), { station: "N123AB", t_ms: 1000, step_ms: 50, rms: [0.1, 0.2] });
    expect(w.bars.N123AB).toEqual([{ t: 1000, rms: 0.1 }, { t: 1050, rms: 0.2 }]);
  });
  it("a newer caption with the same id replaces the old one and keeps the start", () => {
    const id = "N123AB-1761339120000";
    expect(streamStart(id)).toBe(1761339120000);
    let w = addCaption(empty(), { id, station: "N123AB", words: [{ text: "Tower,", kind: null, at_ms: null }], final: false, source: "stt", lag_ms: 500, ts: 1761339121000 });
    w = addCaption(w, { id, station: "N123AB", words: [{ text: "Tower,", kind: null, at_ms: null }, { text: "Cessna", kind: "callsign", at_ms: null }], final: true, source: "stt", lag_ms: 100, ts: 1761339122100 });
    expect(Object.keys(w.captions)).toHaveLength(1);
    expect(w.captions[id].final).toBe(true);
    const [a, b] = wordTimes(w.captions[id]);
    expect(a).toBeGreaterThan(1761339120000);
    expect(b).toBeLessThan(1761339122000); // before it was heard: arrival minus lag
    expect(b).toBeGreaterThan(a);
  });
  it("TTS words use their own times", () => {
    const w = addCaption(empty(), { id: "tx-1", station: "atc", words: [{ text: "Cessna", kind: "callsign", at_ms: 5000 }], final: false, source: "tts", lag_ms: null, ts: 5010 });
    expect(wordTimes(w.captions["tx-1"])).toEqual([5000]);
  });
  it("overlaps merge and old things scroll out", () => {
    let w = addOverlap(empty(), { start: 1000, end: null, stations: ["atc", "H456"] });
    w = addOverlap(w, { start: 1100, end: 2400, stations: ["atc", "H456"] });
    expect(w.overlaps).toEqual([{ start: 1000, end: 2400, stations: ["atc", "H456"] }]);
    w = addLevel(w, { station: "atc", t_ms: 1000, step_ms: 50, rms: [0.1] });
    expect(prune(w, 100_000).bars).toEqual({});
    expect(prune(w, 100_000).overlaps).toEqual([]);
  });
  it("now sits at the playhead and the past is to its left", () => {
    expect(xOf(10_000, 10_000, 1000)).toBe(780);
    expect(xOf(7_000, 10_000, 1000)).toBe(280);
  });
});
