// Spec for how big Beam draws itself on a given screen.
import { describe, expect, it } from "vitest";
import { scaleFor } from "./scale";

const TALL = 3000; // tall enough that only the width matters

// The empty send page at 1x, measured in Chrome: 686px of content plus the
// stage's top padding, clamp(24px, 9vh, 112px), which depends on the window.
const sendPageHeight = (windowHeight: number) => 686 + Math.min(112, Math.max(24, 0.09 * windowHeight));

describe("scaleFor by width", () => {
  it.each([
    [390, 1], // phone
    [1024, 1], // tablet / small laptop
    [1280, 1], // laptop: unchanged
  ])("leaves %ipx at actual size", (width, scale) => {
    expect(scaleFor(width, TALL)).toBe(scale);
  });

  it("is about 1.05 on a 1080p monitor", () => {
    expect(scaleFor(1920, TALL)).toBeCloseTo(1.05, 5);
  });

  it("is 1.1 on a 1440p monitor", () => {
    expect(scaleFor(2560, TALL)).toBeCloseTo(1.1, 5);
  });

  it.each([3840, 5120])("stops at 1.2 on %ipx", (width) => {
    expect(scaleFor(width, TALL)).toBe(1.2);
  });
});

describe("scaleFor by height", () => {
  it.each([800, 850, 1000])("never grows the send page past the bottom of a %ipx window", (height) => {
    // wide but short: width alone would say 1.2
    expect(scaleFor(3840, height) * sendPageHeight(height)).toBeLessThanOrEqual(height);
  });

  it("never shrinks below actual size on a short window", () => {
    expect(scaleFor(1920, 500)).toBe(1);
  });

  it("leaves the width's scale alone when there's room", () => {
    expect(scaleFor(1920, 950)).toBeCloseTo(1.05, 5);
  });
});
