// Beam is drawn for a laptop. On bigger screens the whole page (text, spacing,
// icons, windows) grows together, so it never looks like a little cube on a
// big monitor. Phones and laptops are left exactly as designed.
const FROM = 1280; // widths up to here draw at 1x
const AT_1080P = 1920; // ...growing to 1.3x here
const MAX = 1.4; // and never past this, so huge screens don't look silly

export function scaleFor(width: number): number {
  if (width <= FROM) return 1;
  return Math.min(MAX, 1 + ((width - FROM) / (AT_1080P - FROM)) * 0.3);
}

/** Keeps --zoom on the page in step with the window's width. */
export function followScreenSize() {
  const apply = () => document.documentElement.style.setProperty("--zoom", String(scaleFor(window.innerWidth)));
  apply();
  window.addEventListener("resize", apply);
}
