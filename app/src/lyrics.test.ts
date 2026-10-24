import { describe, expect, it } from "vitest";
import { caption, empty, lagLabel, note, tick, MAX_LINES } from "./lyrics";

const w = (s: string) => s.split(" ").map((text) => ({ text, kind: null as null }));
const msg = (text: string, final = false, lag: number | null = 180) => ({ id: "N123AB-1", station: "N123AB", words: w(text), final, lag_ms: lag });

describe("lyrics lines", () => {
  it("updates a line at most once per second, then the waiting text shows", () => {
    let s = caption(empty(), msg("Tower,"), 0, "You", true);
    s = caption(s, msg("Tower, Cessna"), 400, "You", true);
    expect(s.lines[0].words.map((x) => x.text)).toEqual(["Tower,"]);
    expect(s.lines[0].pending?.length).toBe(2);
    s = tick(s, 900);
    expect(s.lines[0].words).toHaveLength(1);
    s = tick(s, 1000);
    expect(s.lines[0].words).toHaveLength(2);
    expect(s.lines[0].pending).toBeNull();
  });
  it("the final caption replaces the interim at once, and a late interim can't undo it", () => {
    let s = caption(empty(), msg("Tower, Cess"), 0, "You", true);
    s = caption(s, msg("Tower, Cessna one two three", true, 97), 100, "You", true);
    expect(s.lines[0].final).toBe(true);
    expect(s.lines[0].words).toHaveLength(5);
    s = caption(s, msg("Tower, Cessna one"), 2000, "You", true);
    expect(s.lines[0].words).toHaveLength(5);
  });
  it("advisories and events are their own lines; old lines scroll away", () => {
    let s = note(empty(), "adv-1", "Unstep", "advisory", "From Tower: hold short Runway 33.", 0);
    s = note(s, "adv-1", "Unstep", "advisory", "duplicate", 10);
    expect(s.lines).toHaveLength(1);
    for (let i = 0; i < MAX_LINES + 3; i++) s = note(s, `e-${i}`, "", "event", "Talked over", i);
    expect(s.lines).toHaveLength(MAX_LINES);
  });
  it("advisories read plainly and the same one twice shows once", () => {
    let s = note(empty(), "a1", "Unstep", "advisory", "Advisory. Likely hold short runway tree tree.", 0);
    s = note(s, "a2", "Unstep", "advisory", "Advisory. Likely hold short runway tree tree.", 500);
    expect(s.lines).toHaveLength(1);
    expect(s.lines[0].words.map((x) => x.text).join(" ")).toBe("Likely hold short runway three three.");
  });
  it("typed lines say TTS timing", () => {
    const s = caption(empty(), { ...msg("Cessna"), source: "tts" as const, lag_ms: null }, 0, "Tower", false);
    expect(lagLabel(s)).toContain("TTS timing");
  });
  it("the lag label names your voice or speech", () => {
    expect(lagLabel(caption(empty(), msg("Tower,"), 0, "You", true))).toBe("Cartesia live caption · 180 ms behind your voice");
    expect(lagLabel(caption(empty(), msg("Tower,"), 0, "Tower", false))).toBe("Cartesia live caption · 180 ms behind speech");
    expect(lagLabel(empty())).toBeNull();
  });
});
