/** Beam's mark: a file leaving a tray, drawn in the same hand as the file icons. */
export function BeamMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect x="1" y="1" width="30" height="30" rx="8" fill="#2F6BFF" />
      <path d="M11 6.5 H18.5 L22 10 V19.5 A1 1 0 0 1 21 20.5 H11 A1 1 0 0 1 10 19.5 V7.5 A1 1 0 0 1 11 6.5 Z" fill="#FFFFFF" />
      <path d="M18.5 6.5 V10 H22" fill="#FFD23F" />
      <path d="M6.5 18 V23.5 A2 2 0 0 0 8.5 25.5 H23.5 A2 2 0 0 0 25.5 23.5 V18" fill="none" stroke="#FFFFFF" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
