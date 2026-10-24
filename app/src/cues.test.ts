import { describe, expect, it } from "vitest";
import { PATTERNS, patternMs, readbackCue } from "./cues";

describe("eyes-free cues", () => {
  it("every cue is short enough not to hide the radio", () => {
    for (const name of Object.keys(PATTERNS) as (keyof typeof PATTERNS)[]) expect(patternMs(name)).toBeLessThanOrEqual(400);
  });
  it("good rises, bad falls", () => {
    const ok = PATTERNS.readback_ok, bad = PATTERNS.readback_wrong;
    expect(ok[ok.length - 1][0]).toBeGreaterThan(ok[0][0]);
    expect(bad[bad.length - 1][0]).toBeLessThan(bad[0][0]);
  });
  it("plays a readback cue only when the status changes", () => {
    expect(readbackCue("confirmed", "delivered")).toBe("readback_ok");
    expect(readbackCue("readback_wrong", "delivered")).toBe("readback_wrong");
    expect(readbackCue("confirmed", "confirmed")).toBeNull();
    expect(readbackCue("delivered", "approved")).toBeNull();
  });
});
