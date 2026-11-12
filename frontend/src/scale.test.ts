// Spec for how big Beam draws itself on a given screen width.
import { describe, expect, it } from "vitest";
import { scaleFor } from "./scale";

describe("scaleFor", () => {
  it.each([
    [390, 1], // phone
    [1024, 1], // tablet / small laptop
    [1280, 1], // laptop: unchanged from today
  ])("leaves %ipx at actual size", (width, scale) => {
    expect(scaleFor(width)).toBe(scale);
  });

  it("grows smoothly past 1280px", () => {
    expect(scaleFor(1600)).toBeCloseTo(1.15, 5);
  });

  it("is 1.3 on a 1080p monitor", () => {
    expect(scaleFor(1920)).toBeCloseTo(1.3, 5);
  });

  it.each([2560, 3840])("stops at 1.4 on %ipx", (width) => {
    expect(scaleFor(width)).toBe(1.4);
  });
});
