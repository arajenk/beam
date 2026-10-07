import { useEffect, useState } from "react";
import { ArrowDownToLine, ArrowRight } from "lucide-react";
import { downloadUrl, getFileInfo, type FileInfo } from "../api";
import { formatBytes } from "../format";
import { FileIcon } from "../components/FileIcon";
import { Window } from "../components/Window";

type State = { phase: "loading" } | { phase: "ready"; info: FileInfo } | { phase: "missing" } | { phase: "error" };

export function DownloadPage({ fileId }: { fileId: string }) {
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    let live = true;
    getFileInfo(fileId).then(
      (info) => live && setState(info ? { phase: "ready", info } : { phase: "missing" }),
      () => live && setState({ phase: "error" }),
    );
    return () => {
      live = false;
    };
  }, [fileId]);

  useEffect(() => {
    if (state.phase === "ready") document.title = `${state.info.filename} · Beam`;
  }, [state]);

  if (state.phase === "missing" || state.phase === "error") {
    const missing = state.phase === "missing";
    return (
      <Window title={missing ? "Link expired" : "Something went wrong"}>
        <div className="receive is-empty">
          <div className="receive-empty-art" aria-hidden="true">
            <FileIcon name="gone" size={72} className="receive-ghost" />
          </div>
          <h2 className="receive-name">{missing ? "This file isn’t here anymore" : "We couldn’t load this file"}</h2>
          <p className="receive-meta">
            {missing
              ? "Beam links last about a day. Ask the sender for a fresh link."
              : "Check your connection and reload the page."}
          </p>
          <a className="button button-quiet" href="/">
            <span>Send a file of your own</span>
            <ArrowRight size={16} strokeWidth={2.25} />
          </a>
        </div>
      </Window>
    );
  }

  return (
    <Window title="Someone sent you a file" meta={<span className="num">{fileId}</span>}>
      <div className="receive" aria-busy={state.phase === "loading"}>
        {state.phase === "loading" ? (
          <>
            <div className="skeleton skeleton-icon" />
            <div className="skeleton skeleton-line" />
            <div className="skeleton skeleton-line is-short" />
          </>
        ) : (
          <>
            <FileIcon name={state.info.filename} size={88} className="receive-icon" />
            <h2 className="receive-name">{state.info.filename}</h2>
            <p className="receive-meta">
              <span className="num">{formatBytes(state.info.size)}</span>
              <span aria-hidden="true">·</span>
              <span>Link expires about a day after it was sent</span>
            </p>
            <a className="button button-primary button-lg" href={downloadUrl(fileId)} download>
              <ArrowDownToLine size={18} strokeWidth={2.25} />
              <span>Download</span>
            </a>
          </>
        )}
      </div>
    </Window>
  );
}
