import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertCircle, ArrowUpFromLine, Plus, RotateCcw, Send } from "lucide-react";
import { checkShare, startShare, UploadError, type FileState, type ShareHandle, type UploadTarget } from "../api";
import { formatBytes } from "../format";
import { FileIcon } from "./FileIcon";
import { FileRow } from "./FileRow";
import { prepareTurnstile, takeTurnstileToken } from "../turnstile";

type State =
  // choosing files; nothing has touched the network yet
  | { phase: "pick"; staged: File[]; note?: string; error?: string }
  // the API accepted the share (or is about to); files upload one by one
  | { phase: "send"; staged: File[]; shareId: string | null; files: FileState[] };

const settledStatus = (s: FileState) => s.status === "done" || s.status === "failed" || s.status === "cancelled";

export type SenderView = { title: string; highlighted: boolean; body: ReactNode };

/**
 * Picking, sending and progress for one share, used by the send page and by
 * file requests. It owns the state; the caller decides the frame through
 * `children`, and what a finished send shows through `done`.
 */
export function Sender({
  target,
  check,
  idleHeading,
  idleSub,
  done,
  doneFoot,
  readyTitle = "Ready to share",
  onSettled,
  children,
}: {
  /** Where the files go, built when Send is pressed. */
  target?: () => UploadTarget;
  /** false holds the send back; the caller shows why (e.g. on its own field). */
  check?: () => boolean;
  idleHeading: string;
  idleSub: string;
  /** Under the files once something made it, e.g. the share link. */
  done: (shareId: string) => ReactNode;
  /** The finished send's footer text. */
  doneFoot: string;
  /** The window title once something made it. */
  readyTitle?: string;
  onSettled?: () => void;
  children: (view: SenderView) => ReactNode;
}) {
  const [state, setState] = useState<State>({ phase: "pick", staged: [] });
  const [dragging, setDragging] = useState(false);
  const handle = useRef<ShareHandle | null>(null);
  const input = useRef<HTMLInputElement>(null);
  // Turnstile renders here; empty unless Cloudflare wants a click.
  const challenge = useRef<HTMLDivElement>(null);
  const dragDepth = useRef(0);
  const sending = state.phase === "send";

  // Picking files takes a few seconds; solve the Turnstile challenge meanwhile.
  function prepare() {
    if (challenge.current) prepareTurnstile(challenge.current);
  }

  function add(incoming: FileList | File[]) {
    const list = Array.from(incoming);
    if (list.length === 0) return;
    setState((s) => {
      if (s.phase !== "pick") return s;
      const staged = [...s.staged, ...list];
      const problem = checkShare(staged);
      if (problem) {
        const total = formatBytes(staged.reduce((sum, f) => sum + f.size, 0));
        return { ...s, note: undefined, error: `${problem} That would make ${staged.length} files, ${total}.` };
      }
      return { phase: "pick", staged };
    });
  }

  function remove(index: number) {
    setState((s) => (s.phase === "pick" ? { phase: "pick", staged: s.staged.filter((_, i) => i !== index) } : s));
  }

  function send() {
    if (state.phase !== "pick" || state.staged.length === 0) return;
    if (check && !check()) return;
    const staged = state.staged;
    const h = startShare(
      staged,
      (files) => {
        if (handle.current !== h) return;
        // everything cancelled: nothing to share, so go back to picking
        if (files.every((f) => f.status === "cancelled")) {
          handle.current = null;
          h.dispose();
          setState({ phase: "pick", staged: [], note: "Upload cancelled. Nothing was sent." });
          return;
        }
        setState((s) => (s.phase === "send" ? { ...s, files } : s));
      },
      () => (challenge.current ? takeTurnstileToken(challenge.current) : Promise.reject(new Error("No challenge slot"))),
      target?.(),
    );
    handle.current = h;
    setState({
      phase: "send",
      staged,
      shareId: null,
      files: staged.map((f, index) => ({ index, filename: f.name, size: f.size, loaded: 0, status: "queued" })),
    });
    h.started.then(
      ({ shareId }) => setState((s) => (s.phase === "send" && handle.current === h ? { ...s, shareId } : s)),
      (err: unknown) => {
        if (handle.current !== h) return;
        handle.current = null;
        const kind = err instanceof UploadError ? err.kind : "failed";
        const error =
          kind === "limit"
            ? "Beam’s upload limit for today has been reached. Try again tomorrow."
            : kind === "verification"
              ? "We couldn’t check that you’re a person. Try again."
              : kind === "closed"
                ? "This request just closed, so it can’t take any more files."
                : kind === "missing"
                  ? "This request isn’t here anymore."
                  : kind === "too-large" && err instanceof UploadError
                    ? err.message
                    : "The upload didn’t go through. Check your connection and try again.";
        // keep the files picked, so trying again is one click
        setState({ phase: "pick", staged, error });
      },
    );
  }

  function reset() {
    handle.current?.dispose();
    handle.current = null;
    setState({ phase: "pick", staged: [] });
  }

  // Accept a drop anywhere on the page, not just inside the panel.
  useEffect(() => {
    const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (!sending) prepare();
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
      if (!sending && e.dataTransfer?.files) add(e.dataTransfer.files);
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

  useEffect(() => () => handle.current?.dispose(), []);

  const choose = () => {
    prepare();
    input.current?.click();
  };

  const settled = state.phase === "send" && state.files.every(settledStatus);
  const doneFiles = state.phase === "send" ? state.files.filter((f) => f.status === "done") : [];
  const failed = state.phase === "send" ? state.files.filter((f) => f.status === "failed") : [];
  // the result appears once nothing is still going, and only if something made it
  const ready = settled && doneFiles.length > 0;
  const stagedSize = state.phase === "pick" ? state.staged.reduce((sum, f) => sum + f.size, 0) : 0;

  // tell the caller once per finished send, e.g. so a request page can refresh its list
  const reported = useRef(false);
  useEffect(() => {
    if (settled && !reported.current) {
      reported.current = true;
      onSettled?.();
    }
    if (!settled) reported.current = false;
  }, [settled, onSettled]);

  const title =
    state.phase === "pick"
      ? state.staged.length > 0
        ? `${state.staged.length} ${state.staged.length === 1 ? "file" : "files"} to send`
        : ""
      : ready
        ? readyTitle
        : settled
          ? "Upload failed"
          : "Sending…";

  const body = (
    <>
      <input
        ref={input}
        type="file"
        multiple
        hidden
        onChange={(e) => {
          if (e.target.files) add(e.target.files);
          e.target.value = "";
        }}
      />

      {state.phase === "pick" && state.staged.length === 0 && (
        <div className={`drop${dragging ? " is-dragging" : ""}`}>
          <div className="drop-art" aria-hidden="true">
            <FileIcon name="photo.jpg" size={64} className="drop-file drop-file-a" />
            <FileIcon name="notes.pdf" size={72} className="drop-file drop-file-b" />
            <FileIcon name="project.zip" size={64} className="drop-file drop-file-c" />
          </div>
          <h2 className="drop-heading">{dragging ? "Let go to add them" : idleHeading}</h2>
          <p className="drop-sub">{idleSub}</p>
          <button type="button" className="button button-primary button-lg" onClick={choose}>
            <ArrowUpFromLine size={18} strokeWidth={2.25} />
            <span>Choose files</span>
          </button>
          {state.error && <ErrorNotice message={state.error} />}
          {state.note && (
            <p className="notice" role="status">
              {state.note}
            </p>
          )}
        </div>
      )}

      {state.phase === "pick" && state.staged.length > 0 && (
        <div className={`transfer${dragging ? " is-dragging" : ""}`}>
          <div className="file-list">
            {state.staged.map((f, i) => (
              <FileRow key={i} name={f.name} size={f.size} status="staged" onRemove={() => remove(i)} compact />
            ))}
          </div>
          {state.error && <ErrorNotice message={state.error} />}
          <div className="transfer-foot">
            <span className="num">
              {formatBytes(stagedSize)} of 10 GB · {state.staged.length} of 10 files
            </span>
            <div className="transfer-actions">
              {state.staged.length < 10 && (
                <button type="button" className="button button-quiet" onClick={choose}>
                  <Plus size={16} strokeWidth={2.25} />
                  <span>Add files</span>
                </button>
              )}
              <button type="button" className="button button-primary" onClick={send}>
                <Send size={16} strokeWidth={2.25} />
                <span>Send</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {state.phase === "send" && (
        <div className={`transfer${ready ? " is-done" : ""}`}>
          <div className="file-list">
            {state.files
              .filter((f) => !(settled && f.status === "cancelled"))
              .map((f) => (
                <FileRow
                  key={f.index}
                  name={f.filename}
                  size={f.size}
                  loaded={f.loaded}
                  status={f.status}
                  onCancel={() => handle.current?.cancel(f.index)}
                  onRetry={() => handle.current?.retry(f.index)}
                  compact={state.files.length > 1}
                />
              ))}
          </div>

          {ready && state.shareId && done(state.shareId)}

          {settled && failed.length > 0 && (
            <p className="notice notice-error" role="alert">
              <AlertCircle size={18} strokeWidth={2.25} />
              <span>
                {ready
                  ? `${failed.length === 1 ? "1 file" : `${failed.length} files`} didn’t go through. Retry, or carry on without ${failed.length === 1 ? "it" : "them"}.`
                  : "Nothing went through. Check your connection and retry."}
              </span>
            </p>
          )}

          {!settled && <p className="transfer-hint">Keep this tab open until it’s done.</p>}

          <div className="transfer-foot">
            <span>{ready ? doneFoot : ""}</span>
            {settled ? (
              <button type="button" className="button button-quiet" onClick={reset}>
                <RotateCcw size={16} strokeWidth={2.25} />
                <span>Send more</span>
              </button>
            ) : (
              <button type="button" className="button button-quiet" onClick={() => handle.current?.cancelAll()}>
                <span>Cancel all</span>
              </button>
            )}
          </div>
        </div>
      )}

      <div ref={challenge} className="challenge" />
    </>
  );

  return children({ title, highlighted: dragging && !sending, body });
}

export function ErrorNotice({ message }: { message: string }) {
  return (
    <p className="notice notice-error" role="alert">
      <AlertCircle size={18} strokeWidth={2.25} />
      <span>{message}</span>
    </p>
  );
}
