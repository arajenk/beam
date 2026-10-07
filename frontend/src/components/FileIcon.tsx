import { extensionOf, kindOf, type FileKind } from "../format";

const COLORS: Record<FileKind, string> = {
  image: "#22966A",
  video: "#6D4BD8",
  audio: "#E2702A",
  doc: "#2F6BFF",
  sheet: "#0E8A8A",
  archive: "#B98A00",
  code: "#3A4350",
  other: "#6A7280",
};

function Glyph({ kind, color }: { kind: FileKind; color: string }) {
  switch (kind) {
    case "image":
      return (
        <g>
          <circle cx="30" cy="20" r="3.2" fill={color} opacity="0.55" />
          <path d="M11 34 L19 24 L25 30 L29 26 L37 34 Z" fill={color} opacity="0.8" />
        </g>
      );
    case "video":
      return (
        <g>
          <rect x="11" y="15" width="26" height="19" rx="3" fill={color} opacity="0.14" />
          <path d="M21 19.5 L29.5 24.5 L21 29.5 Z" fill={color} />
        </g>
      );
    case "audio":
      return (
        <g stroke={color} strokeWidth="2.4" strokeLinecap="round">
          {[13, 17.5, 22, 26.5, 31, 35].map((x, i) => {
            const h = [5, 11, 16, 9, 13, 6][i];
            return <line key={x} x1={x} x2={x} y1={25 - h / 2} y2={25 + h / 2} />;
          })}
        </g>
      );
    case "archive":
      return (
        <g fill={color}>
          {[12, 17, 22, 27].map((y, i) => (
            <rect key={y} x={i % 2 ? 24 : 21} y={y} width="3" height="3" rx="0.6" />
          ))}
          <rect x="20.5" y="31" width="7" height="5" rx="1.2" />
        </g>
      );
    case "code":
      return (
        <g fill="none" stroke={color} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 18 L12 24.5 L18 31" />
          <path d="M30 18 L36 24.5 L30 31" />
          <path d="M26 16.5 L22 32.5" opacity="0.6" />
        </g>
      );
    case "sheet":
      return (
        <g stroke={color} strokeWidth="1.6" opacity="0.85">
          <rect x="11" y="14" width="26" height="21" rx="1.5" fill="none" />
          <line x1="11" x2="37" y1="21" y2="21" />
          <line x1="11" x2="37" y1="28" y2="28" />
          <line x1="20" x2="20" y1="14" y2="35" />
        </g>
      );
    default:
      return (
        <g stroke={color} strokeWidth="2.2" strokeLinecap="round" opacity="0.5">
          <line x1="12" x2="36" y1="16" y2="16" />
          <line x1="12" x2="33" y1="22" y2="22" />
          <line x1="12" x2="36" y1="28" y2="28" />
          <line x1="12" x2="27" y1="34" y2="34" />
        </g>
      );
  }
}

/** A drawn document icon, tinted and labelled by file type. */
export function FileIcon({ name, size = 56, className }: { name: string; size?: number; className?: string }) {
  const kind = kindOf(name);
  const color = COLORS[kind];
  const ext = (extensionOf(name) || "file").slice(0, 4).toUpperCase();

  return (
    <svg
      className={className}
      width={size}
      height={size * 1.25}
      viewBox="0 0 48 60"
      aria-hidden="true"
      style={{ overflow: "visible" }}
    >
      <path
        d="M6 3.5 H31 L42.5 15 V55 A2.5 2.5 0 0 1 40 57.5 H6 A2.5 2.5 0 0 1 3.5 55 V6 A2.5 2.5 0 0 1 6 3.5 Z"
        fill="#FFFFFF"
        stroke="#C9CED6"
        strokeWidth="1.2"
      />
      <path d="M31 3.5 V12.5 A2.5 2.5 0 0 0 33.5 15 H42.5 Z" fill={color} opacity="0.22" stroke="#C9CED6" strokeWidth="1.2" strokeLinejoin="round" />
      <Glyph kind={kind} color={color} />
      <rect x="7.5" y="42" width="33" height="11" rx="2.6" fill={color} />
      <text
        x="24"
        y="50.2"
        textAnchor="middle"
        className="file-icon-label"
        fontWeight="800"
        fontSize="7.4"
        letterSpacing="0.06em"
        fill="#FFFFFF"
      >
        {ext}
      </text>
    </svg>
  );
}
