import { describe, expect, it } from "vitest";
import { pcm16ToFloat } from "./audio";

describe("streamed advisory audio", () => {
  it("decodes little-endian pcm_s16le to floats", () => {
    const bytes = new Uint8Array([0x00, 0x00, 0xff, 0x7f, 0x00, 0x80, 0x00, 0x40]);
    const b64 = btoa(String.fromCharCode(...bytes));
    const f = Array.from(pcm16ToFloat(b64));
    expect(f[0]).toBe(0);
    expect(f[1]).toBeCloseTo(32767 / 32768, 5);
    expect(f[2]).toBe(-1);
    expect(f[3]).toBe(0.5);
  });
});
