import { useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowUpFromLine, RotateCcw } from "lucide-react";
import { shareUrl, uploadFile, UploadError, MAX_SIZE, type UploadHandle, type UploadResult } from "../api";
import { formatBytes } from "../format";
import { FileIcon } from "../components/FileIcon";
import { FileRow } from "../components/FileRow";
import { ShareLink } from "../components/ShareLink";
import { Window } from "../components/Window";

type State =
  | { phase: "idle"; note?: string }
  | { phase: "uploading"; file: File; loaded: number; skipped: number }
  | { phase: "done"; result: UploadResult }
  | { phase: "error"; message: string };

export function SendPage() {
  const [state, setState] = useState<State>({ phase: "idle" });
  const [dragging, setDragging] = useState(false);
  const handle = useRef<UploadHandle | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const busy = state.phase === "uploading";
  // The bar only tracks browser → API; after 100% the API is still sending the file to R2.
  const finishing = state.phase === "uploading" && state.loaded >= state.file.size;

  function start(files: FileList | File[]) {
    const list = Array.from(files);
    if (list.length === 0 || busy) return;
    const file = list[0];
    if (file.size > MAX_SIZE) {
      setState({ phase: "error", message: `${file.name} is ${formatBytes(file.size)}. Beam takes files up to 10 GB.` });
      return;
    }
    setState({ phase: "uploading", file, loaded: 0, skipped: list.length - 1 });
    const h = uploadFile(file, ({ loaded }) =>
      setState((s) => (s.phase === "uploading" && s.file === file ? { ...s, loaded } : s)),
    );
    handle.current = h;
    h.promise.then(
      (result) => {
        handle.current = null;
        setState({ phase: "done", result });
      },
      (err: unknown) => {
        handle.current = null;
        if (err instanceof UploadError && err.kind === "cancelled") {
          setState({ phase: "idle", note: "Upload cancelled. Nothing was sent." });
        } else {
          setState({ phase: "error", message: "The upload didn’t go through. Check your connection and try again." });
        }
      },
    );
  }

  // Accept a drop anywhere on the page, not just inside the panel.
  useEffect(() => {
    const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragDepth.current += 1;
      setDragging(true);
    };
    const over = (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault();
    };
    const leave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      dragDepth.current = Math.max(0, dragDepth.current - 1);
      if (dragDepth.current === 0) setDragging(false);
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragDepth.current = 0;
      setDragging(false);
      if (e.dataTransfer?.files) start(e.dataTransfer.files);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  });

  useEffect(() => () => handle.current?.cancel(), []);

  const reset = () => setState({ phase: "idle" });
  const title =
    state.phase === "uploading" ? (finishing ? "Finishing…" : "Sending…") : state.phase === "done" ? "Ready to share" : "Send a file";

  return (
    <Window title={title} highlighted={dragging && !busy}>
      <input
        ref={input}
        type="file"
        hidden
        onChange={(e) => {
          if (e.target.files) start(e.target.files);
          e.target.value = "";
        }}
      />

      {(state.phase === "idle" || state.phase === "error") && (
        <div className={`drop${dragging ? " is-dragging" : ""}`}>
          <div className="drop-art" aria-hidden="true">
            <FileIcon name="photo.jpg" size={64} className="drop-file drop-file-a" />
            <FileIcon name="notes.pdf" size={72} className="drop-file drop-file-b" />
            <FileIcon name="project.zip" size={64} className="drop-file drop-file-c" />
          </div>
          <h2 className="drop-heading">{dragging ? "Let go to send it" : "Drop a file to send it"}</h2>
          <p className="drop-sub">You’ll get a link to share. It stops working after about a day.</p>
          <button type="button" className="button button-primary button-lg" onClick={() => input.current?.click()}>
            <ArrowUpFromLine size={18} strokeWidth={2.25} />
            <span>Choose a file</span>
          </button>
          {state.phase === "error" && (
            <p className="notice notice-error" role="alert">
              <AlertCircle size={18} strokeWidth={2.25} />
              <span>{state.message}</span>
            </p>
          )}
          {state.phase === "idle" && state.note && (
            <p className="notice" role="status">
              {state.note}
            </p>
          )}
        </div>
      )}

      {state.phase === "uploading" && (
        <div className="transfer">
          <FileRow
            name={state.file.name}
            size={state.file.size}
            loaded={state.loaded}
            status="uploading"
            onCancel={() => handle.current?.cancel()}
          />
          <p className="transfer-hint">
            {finishing
              ? "Saving your file, almost done."
              : state.skipped > 0
                ? `Sending the first file only. One file per link for now.`
                : "Keep this tab open until it’s done."}
          </p>
        </div>
      )}

      {state.phase === "done" && (
        <div className="transfer is-done">
          <FileRow name={state.result.filename} size={state.result.size} status="done" />
          <ShareLink url={shareUrl(state.result.fileId)} />
          <div className="transfer-foot">
            <span>Anyone with the link can download it for about a day.</span>
            <button type="button" className="button button-quiet" onClick={reset}>
              <RotateCcw size={16} strokeWidth={2.25} />
              <span>Send another</span>
            </button>
          </div>
        </div>
      )}
    </Window>
  );
}
