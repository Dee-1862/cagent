import { describe, expect, it } from "vitest";
import { PATTERNS, SPOKEN, cue, patternMs, pending, readbackCue, setAdvisory, setKeyDown, setSpeaker } from "./cues";

describe("eyes-free cues", () => {
  it("every cue is short enough not to hide the radio", () => {
    for (const name of Object.keys(PATTERNS) as (keyof typeof PATTERNS)[]) expect(patternMs(name)).toBeLessThanOrEqual(400);
  });
  it("good rises, bad falls", () => {
    const ok = PATTERNS.readback_ok[0];
    expect(ok.to!).toBeGreaterThan(ok.hz);
    const bad = PATTERNS.readback_wrong;
    expect(bad[bad.length - 1].hz).toBeLessThan(bad[0].hz);
    expect(PATTERNS.stepped_on_me[0].hz2).toBeTruthy(); // a clash
  });
  it("readback cues are never spoken twice (the cockpit already says them)", () => {
    expect(SPOKEN.readback_ok).toBeUndefined();
    expect(SPOKEN.readback_wrong).toBeUndefined();
  });
  it("plays a readback cue only when the status changes", () => {
    expect(readbackCue("confirmed", "delivered")).toBe("readback_ok");
    expect(readbackCue("readback_wrong", "delivered")).toBe("readback_wrong");
    expect(readbackCue("confirmed", "confirmed")).toBeNull();
    expect(readbackCue("delivered", "approved")).toBeNull();
  });
  it("waits while the pilot talks or an advisory speaks, then plays in order", () => {
    const said: string[] = [];
    setSpeaker((p) => said.push(p));
    setKeyDown(true);
    cue("busy");
    cue("stepped_on_me");
    expect(pending()).toEqual(["busy", "stepped_on_me"]);
    setAdvisory(true);
    setKeyDown(false);
    expect(pending()).toHaveLength(2); // the advisory is still speaking
    setAdvisory(false);
    expect(pending()).toHaveLength(0);
    expect(said).toEqual(["busy", "talked_over"]);
    setSpeaker(null);
  });
});
