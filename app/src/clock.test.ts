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

import { downsample } from "./mic";

describe("mic frames", () => {
  it("keeps the remainder so 100 ms frames add up to the whole clip", () => {
    const ratio = 44100 / 16000;
    const input = new Float32Array(44100).fill(0.5);
    let carry = new Float32Array(0);
    let out = 0;
    for (let i = 0; i < input.length; i += 4410) {
      const all = new Float32Array(carry.length + 4410);
      all.set(carry);
      all.set(input.subarray(i, i + 4410), carry.length);
      const { pcm, used } = downsample(all, ratio);
      carry = all.slice(used);
      out += pcm.length;
    }
    expect(Math.abs(out - 16000)).toBeLessThanOrEqual(1);
  });
});

import { hubFromLocation } from "./hub";

describe("which hub the page talks to", () => {
  const at = (href: string) => new URL(href) as unknown as Location;
  it("a copy served by a hub uses that hub, even with a baked-in address", () => {
    expect(hubFromLocation(at("https://192.168.1.5:8765/pilot/"))?.http).toBe("https://192.168.1.5:8765");
  });
  it("a ?hub= link wins", () => {
    expect(hubFromLocation(at("https://x.vercel.app/?hub=https://h.onrender.com&token=t"))).toEqual(
      { http: "https://h.onrender.com", ws: "wss://h.onrender.com", token: "t" });
  });
});

describe("public demo default", () => {
  it("a Vercel address uses the public Render hub with no settings", () => {
    const loc = new URL("https://cagent-abc123-dee-1862s-projects.vercel.app/") as unknown as Location;
    expect(hubFromLocation(loc)?.http).toBe("https://unstep.onrender.com");
  });
});
