const UNITS = ["B", "KB", "MB", "GB", "TB"];

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  let i = 0;
  let v = n;
  while (v >= 1024 && i < UNITS.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 100 ? Math.round(v) : v.toFixed(1)} ${UNITS[i]}`;
}

export type FileKind = "image" | "video" | "audio" | "doc" | "sheet" | "archive" | "code" | "other";

const KINDS: Record<string, FileKind> = {
  png: "image", jpg: "image", jpeg: "image", gif: "image", webp: "image", heic: "image", svg: "image",
  mp4: "video", mov: "video", mkv: "video", webm: "video", avi: "video",
  mp3: "audio", wav: "audio", flac: "audio", m4a: "audio", ogg: "audio",
  pdf: "doc", doc: "doc", docx: "doc", txt: "doc", md: "doc", pages: "doc", key: "doc", ppt: "doc", pptx: "doc",
  xls: "sheet", xlsx: "sheet", csv: "sheet", numbers: "sheet",
  zip: "archive", rar: "archive", "7z": "archive", tar: "archive", gz: "archive", dmg: "archive", iso: "archive",
  js: "code", ts: "code", py: "code", json: "code", html: "code", css: "code", sh: "code", go: "code", rs: "code",
};

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

export function kindOf(name: string): FileKind {
  return KINDS[extensionOf(name)] ?? "other";
}
