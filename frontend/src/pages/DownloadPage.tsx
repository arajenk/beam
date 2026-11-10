import { useEffect, useState } from "react";
import { ArrowDownToLine, ArrowRight } from "lucide-react";
import { fileDownloadUrl, getShareInfo, type SharedFile } from "../api";
import { formatBytes } from "../format";
import { FileIcon } from "../components/FileIcon";
import { FileRow } from "../components/FileRow";
import { ReportForm } from "../components/ReportForm";
import { Window } from "../components/Window";

type State = { phase: "loading" } | { phase: "ready"; files: SharedFile[] } | { phase: "missing" } | { phase: "error" };

// Gap between files in "Download all"; browsers drop downloads started too close together.
const DOWNLOAD_GAP_MS = 800;

/**
 * Downloads each file in turn through a hidden iframe. Each one hits the API's
 * redirect and R2 answers with Content-Disposition: attachment, so the page
 * stays put. The first time, the browser asks to allow multiple downloads.
 */
function downloadAll(shareId: string, files: SharedFile[]) {
  files.forEach((f, i) => {
    window.setTimeout(() => {
      const frame = document.createElement("iframe");
      frame.hidden = true;
      frame.src = fileDownloadUrl(shareId, f.index);
      document.body.appendChild(frame);
      // long enough for the download to start; the iframe itself shows nothing
      window.setTimeout(() => frame.remove(), 60_000);
    }, i * DOWNLOAD_GAP_MS);
  });
}

export function DownloadPage({ shareId }: { shareId: string }) {
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    let live = true;
    getShareInfo(shareId).then(
      (info) => live && setState(info ? { phase: "ready", files: info.files } : { phase: "missing" }),
      () => live && setState({ phase: "error" }),
    );
    return () => {
      live = false;
    };
  }, [shareId]);

  useEffect(() => {
    if (state.phase !== "ready") return;
    document.title = state.files.length === 1 ? `${state.files[0].filename} · Beam` : `${state.files.length} files · Beam`;
  }, [state]);

  if (state.phase === "missing" || state.phase === "error") {
    const missing = state.phase === "missing";
    return (
      <Window title={missing ? "Link expired" : "Something went wrong"}>
        <div className="receive is-empty">
          <div className="receive-empty-art" aria-hidden="true">
            <FileIcon name="gone" size={72} className="receive-ghost" />
          </div>
          <h2 className="receive-name">{missing ? "These files aren’t here anymore" : "We couldn’t load these files"}</h2>
          <p className="receive-meta">
            {missing
              ? "Beam links last about a day. Ask the sender for a fresh link."
              : "Check your connection and reload the page."}
          </p>
          <a className="button button-quiet" href="/">
            <span>Send files of your own</span>
            <ArrowRight size={16} strokeWidth={2.25} />
          </a>
        </div>
      </Window>
    );
  }

  if (state.phase === "loading") {
    return (
      <Window title="Someone sent you files" meta={<span className="num">{shareId}</span>}>
        <div className="receive" aria-busy="true">
          <div className="skeleton skeleton-icon" />
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-line is-short" />
        </div>
      </Window>
    );
  }

  const { files } = state;

  // One file keeps the original big, centred layout.
  if (files.length === 1) {
    const [f] = files;
    return (
      <Window title="Someone sent you a file" meta={<span className="num">{shareId}</span>}>
        <div className="receive">
          <FileIcon name={f.filename} size={88} className="receive-icon" />
          <h2 className="receive-name">{f.filename}</h2>
          <p className="receive-meta">
            <span className="num">{formatBytes(f.size)}</span>
            <span aria-hidden="true">·</span>
            <span>Link expires about a day after it was sent</span>
          </p>
          <a className="button button-primary button-lg" href={fileDownloadUrl(shareId, f.index)} download>
            <ArrowDownToLine size={18} strokeWidth={2.25} />
            <span>Download</span>
          </a>
          <ReportForm shareId={shareId} />
        </div>
      </Window>
    );
  }

  const total = files.reduce((sum, f) => sum + f.size, 0);
  return (
    <Window title={`Someone sent you ${files.length} files`} meta={<span className="num">{shareId}</span>}>
      <div className="transfer">
        <div className="file-list">
          {files.map((f) => (
            <FileRow
              key={f.index}
              name={f.filename}
              size={f.size}
              status="done"
              compact
              action={
                <a
                  className="button button-quiet file-row-action"
                  href={fileDownloadUrl(shareId, f.index)}
                  download
                  aria-label={`Download ${f.filename}`}
                >
                  <ArrowDownToLine size={16} strokeWidth={2.25} />
                  <span>Download</span>
                </a>
              }
            />
          ))}
        </div>
        <div className="transfer-foot">
          <span className="num">
            {files.length} files · {formatBytes(total)} · Link expires about a day after it was sent
          </span>
          <button type="button" className="button button-primary" onClick={() => downloadAll(shareId, files)}>
            <ArrowDownToLine size={16} strokeWidth={2.25} />
            <span>Download all</span>
          </button>
        </div>
        <div className="receive-report">
          <ReportForm shareId={shareId} plural />
        </div>
      </div>
    </Window>
  );
}
