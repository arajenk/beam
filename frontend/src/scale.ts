// Beam is drawn for a laptop. On bigger screens the whole page (text, spacing,
// icons, windows) grows a little, so it doesn't look like a little cube on a
// big monitor. Phones and laptops are left exactly as designed.
const FROM = 1280; // widths up to here draw at 1x
const PER_640PX = 0.05; // then +0.05 for every 640px: 1.05 at 1920, 1.1 at 2560
const MAX = 1.2; // and never past this, so huge screens don't look silly
// The empty send page at 1x, measured in Chrome: 686px of content plus the
// stage's top padding, clamp(24px, 9vh, 112px) in styles.css, which grows with
// the window. Growing past window height / that would push its bottom off screen.
const SEND_PAGE_CONTENT = 686;
const sendPageHeight = (windowHeight: number) => SEND_PAGE_CONTENT + Math.min(112, Math.max(24, 0.09 * windowHeight));

export function scaleFor(width: number, height: number): number {
  const byWidth = Math.min(MAX, 1 + (Math.max(0, width - FROM) / 640) * PER_640PX);
  const byHeight = height / sendPageHeight(height);
  // a short window scrolls at 1x, as before; it never shrinks
  return Math.max(1, Math.min(byWidth, byHeight));
}

/** Keeps --zoom on the page in step with the window's size. */
export function followScreenSize() {
  const apply = () =>
    document.documentElement.style.setProperty("--zoom", String(scaleFor(window.innerWidth, window.innerHeight)));
  apply();
  window.addEventListener("resize", apply);
}
