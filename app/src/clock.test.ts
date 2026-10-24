import { describe, expect, it } from "vitest";
import { bestOffset } from "./clock";
import { sayable, sayLines } from "./phrases";

describe("clock sync", () => {
  it("uses the fastest round trip", () => {
    // Hub is 1000 ms ahead. The slow sample has a skewed one-way delay.
    const s = bestOffset([
      { t0: 0, t1: 1300, t3: 400 },
      { t0: 1000, t1: 2010, t3: 1020 },
    ]);
    expect(s).toEqual({ offset: 1000, rtt: 20, samples: 2 });
  });
  it("has nothing to say without samples", () => {
    expect(bestOffset([])).toBeNull();
  });
});

describe("phrases", () => {
  it("speaks digits the ATC way", () => {
    expect(sayable("Piper 7-8-9")).toBe("Piper seven eight niner");
    expect(sayable("Cessna 1-2-3")).toBe("Cessna one two three");
  });
  it("has a deliberately wrong readback for the demo", () => {
    expect(sayLines("Cessna 1-2-3", false)[1].text).toContain("two three, Cessna one two three");
  });
});
