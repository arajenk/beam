import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { AlertCircle, ArrowDownToLine, ArrowRight, Bookmark, Lock, RotateCw } from "lucide-react";
import {
  getRequestInfo,
  requestFileUrl,
  requestPageUrl,
  requestTarget,
  type RequestInfo,
  type RequestSend,
} from "../api";
import { formatBytes } from "../format";
import { FileIcon } from "../components/FileIcon";
import { FileRow } from "../components/FileRow";
import { ReportForm } from "../components/ReportForm";
import { Sender } from "../components/Sender";
import { SecretLink, ShareLink } from "../components/ShareLink";
import { Window } from "../components/Window";
import { downloadInTurn } from "../download";
import { navigate } from "../route";

type State = { phase: "loading" } | { phase: "ready"; info: RequestInfo } | { phase: "missing" } | { phase: "error" };

const NAME_LIMIT = 50;

/**
 * /r/{id} and /r/{id}/{key}. One page, several views of the same request:
 * the requester's own link (files only), a group link (files and the send box),
 * the public link of a private request (send box only), closed, and gone.
 */
export function RequestPage({
  requestId,
  ownerKey,
  justCreated,
}: {
  requestId: string;
  ownerKey?: string;
  justCreated: boolean;
}) {
  const [state, setState] = useState<State>({ phase: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [sender, setSender] = useState("");
  const [nameMissing, setNameMissing] = useState(false);
  const nameField = useRef<HTMLInputElement>(null);

  // "just created" is for the first view only: a reload is a revisit, not an arrival
  useEffect(() => {
    if (justCreated) window.history.replaceState(null, "", window.location.href);
  }, [justCreated]);

  const fetchInfo = useCallback(
    () =>
      getRequestInfo(requestId, ownerKey).then(
        (info) => setState(info ? { phase: "ready", info } : { phase: "missing" }),
        // keep what's on screen if a refresh fails; only an empty page shows the error
        () => setState((s) => (s.phase === "ready" ? s : { phase: "error" })),
      ),
    [requestId, ownerKey],
  );

  useEffect(() => {
    void fetchInfo();
  }, [fetchInfo]);

  const load = useCallback(() => {
    setRefreshing(true);
    void fetchInfo().finally(() => setRefreshing(false));
  }, [fetchInfo]);

  const who = state.phase === "ready" ? (state.info.name ?? "Someone") : "Someone";
  useEffect(() => {
    if (state.phase === "ready") {
      document.title = state.info.isOwner && state.info.private ? "Your request · Beam" : `${who} requested files · Beam`;
    }
  }, [state, who]);

  if (state.phase === "missing" || state.phase === "error") {
    const missing = state.phase === "missing";
    return (
      <Window title={missing ? "Request not found" : "Something went wrong"}>
        <div className="receive is-empty">
          <div className="receive-empty-art" aria-hidden="true">
            <FileIcon name="gone" size={72} className="receive-ghost" />
          </div>
          <h2 className="receive-name">{missing ? "This request isn’t here anymore" : "We couldn’t load this request"}</h2>
          <p className="receive-meta">
            {missing
              ? "Requests last about a day. Ask whoever sent it for a fresh link."
              : "Check your connection and reload the page."}
          </p>
          {missing && (
            <a className="button button-quiet" href="/request" onClick={navigate}>
              <span>Make your own request</span>
              <ArrowRight size={16} strokeWidth={2.25} />
            </a>
          )}
        </div>
      </Window>
    );
  }

  if (state.phase === "loading") {
    return (
      <Window title="Loading request…">
        <div className="req" aria-busy="true">
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-note" />
          <div className="skeleton skeleton-line is-short" />
        </div>
      </Window>
    );
  }

  const { info } = state;
  // the requester's own link to a private request: they collect, they don't send
  const ownerView = info.isOwner && info.private;
  const canSend = info.open && !ownerView;
  // everyone may see the files (switch off), so the page has two jobs: see what's in, add to it
  const groupView = !info.private && canSend;

  const ask = (
    <div className="req-ask">
      <h2 className="req-heading">{ownerView || justCreated ? "You asked for files" : `${who} requested files`}</h2>
      <p className="req-note-label">Note</p>
      <blockquote className="req-note">{info.note}</blockquote>
      <p className="req-note-source">Written by the requester, not by Beam.</p>
    </div>
  );

  const closedNotice = !info.open && (
    <p className="notice" role="status">
      <Lock size={18} strokeWidth={2.25} />
      <span>
        This request is closed. It stopped taking files {closedWhen(info.closesAt)}
        {info.sends && info.sends.length > 0 ? ", but what was sent is still here for now." : "."}
      </span>
    </p>
  );

  const publicCreatedLinks = !info.private && justCreated && (
    <div className="req-links">
      <ShareLink url={requestPageUrl(requestId)} label="Link to send to others" id="request-link" fresh short />
      <BookmarkNotice text="Bookmark this page to come back to the files. Beam has no account to remember it for you." />
    </div>
  );

  const files = (heading: boolean) =>
    info.sends !== null && (
      <SentFiles
        sends={info.sends}
        requestId={requestId}
        ownerKey={ownerKey}
        refreshing={refreshing}
        onRefresh={load}
        heading={heading}
      />
    );

  const report = !info.isOwner && (
    <div className="receive-report req-report">
      <ReportForm shareId={requestId} kind="request" />
    </div>
  );

  // Owner of a private request: setup on the left, what came in on the right.
  if (ownerView) {
    return (
      <div className="tiles">
        <Window title="Your request">
          <div className="req">
            <OwnerLinks requestId={requestId} ownerKey={ownerKey!} justCreated={justCreated} />
            {ask}
            {closedNotice}
          </div>
        </Window>
        <Window title="Sent so far">
          <div className="req req-tile">{files(false)}</div>
        </Window>
      </div>
    );
  }

  // Closed: nothing to send, so one window with whatever may be seen.
  if (!canSend) {
    return (
      <Window title="File request">
        <div className="req">
          {ask}
          {closedNotice}
          {info.sends && info.sends.length > 0 && files(true)}
        </div>
        <div className="req-closed">
          <p>Want files from someone yourself?</p>
          <a className="button button-quiet" href="/request" onClick={navigate}>
            <span>Make your own request</span>
            <ArrowRight size={16} strokeWidth={2.25} />
          </a>
        </div>
        {report}
      </Window>
    );
  }

  const nameBox = (
    <div className="req-from">
      <label className="field-label" htmlFor="sender-name">
        Your name
      </label>
      <input
        id="sender-name"
        ref={nameField}
        className={`field${nameMissing ? " is-invalid" : ""}`}
        value={sender}
        maxLength={NAME_LIMIT}
        autoComplete="name"
        placeholder={info.name ? `So ${info.name} knows who sent the files` : "So they know who sent the files"}
        aria-invalid={nameMissing}
        aria-describedby={nameMissing ? "sender-name-error" : undefined}
        onChange={(e) => {
          setSender(e.target.value);
          if (e.target.value.trim()) setNameMissing(false);
        }}
      />
      {nameMissing && (
        <p className="field-error" id="sender-name-error" role="alert">
          <AlertCircle size={16} strokeWidth={2.25} aria-hidden="true" />
          <span>Add your name, then press Send again.</span>
        </p>
      )}
    </div>
  );

  return (
    <Sender
      target={() => requestTarget(requestId, sender.trim())}
      check={() => {
        if (sender.trim()) return true;
        setNameMissing(true);
        nameField.current?.focus();
        return false;
      }}
      idleHeading={info.name ? `Drop files to send them to ${info.name}` : "Drop files to send them"}
      idleSub={
        info.private
          ? `Up to 10 files, 10 GB in total. Only ${info.name ?? "the requester"} can see what you send.`
          : "Up to 10 files, 10 GB in total. Everyone with this link can see what’s sent."
      }
      doneFoot="Files stay for about a day after they’re sent."
      readyTitle="Sent"
      onSettled={info.private ? undefined : load}
      done={() => (
        <div className="req-sent" role="status">
          <p className="req-sent-title">Upload complete</p>
          <p className="req-sent-sub">
            {info.private
              ? `Sent to ${info.name ?? "the requester"}. Only they can see it.`
              : `Sent to ${info.name ?? "the requester"}. It’s in the list${groupView ? "" : " above"}.`}
          </p>
          <a className="button button-quiet req-sent-route" href="/" onClick={navigate}>
            <span>Send files of your own</span>
            <ArrowRight size={16} strokeWidth={2.25} />
          </a>
        </div>
      )}
    >
      {({ title, highlighted, body }) =>
        groupView ? (
          // Group link: what's been asked for and sent on the left, your own send on the right.
          <div className="tiles">
            <Window title="File request">
              <div className="req">
                {publicCreatedLinks}
                {ask}
                {files(true)}
              </div>
              {report}
            </Window>
            <Window title={title || "Send files"} highlighted={highlighted}>
              <section className="req-send is-tile" aria-label="Send files">
                {nameBox}
                {body}
              </section>
            </Window>
          </div>
        ) : (
          // Public link of a private request: read the note, send. One job, one window.
          <Window title="File request" highlighted={highlighted}>
            <div className="req">{ask}</div>
            <section className="req-send" aria-label="Send files">
              {nameBox}
              {body}
            </section>
            {report}
          </Window>
        )
      }
    </Sender>
  );
}

function OwnerLinks({ requestId, ownerKey, justCreated }: { requestId: string; ownerKey: string; justCreated: boolean }) {
  return (
    <div className="req-links">
      <SecretLink
        url={requestPageUrl(requestId, ownerKey)}
        label="Your private link"
        id="owner-link"
        hint="Keep this one to yourself. Anyone with it can see and download what’s sent."
      />
      {justCreated && (
        <BookmarkNotice text="Bookmark this page now. It’s your only way back to the files, and Beam can’t recover it." />
      )}
      <ShareLink url={requestPageUrl(requestId)} label="Link to send to others" id="request-link" fresh={justCreated} short />
    </div>
  );
}

function BookmarkNotice({ text }: { text: string }) {
  return (
    <p className="notice req-bookmark" role="status">
      <Bookmark size={18} strokeWidth={2.25} />
      <span>{text}</span>
    </p>
  );
}

function SentFiles({
  sends,
  requestId,
  ownerKey,
  refreshing,
  onRefresh,
  heading,
}: {
  sends: RequestSend[];
  requestId: string;
  ownerKey?: string;
  refreshing: boolean;
  onRefresh: () => void;
  /** Off when the window's title bar already says "Sent so far". */
  heading: boolean;
}) {
  const all = sends.flatMap((s) => s.files.map((f) => ({ send: s, file: f })));
  const total = all.reduce((sum, x) => sum + x.file.size, 0);
  const url = (s: RequestSend, index: number) => requestFileUrl(requestId, s.shareId, index, ownerKey);

  let content: ReactNode;
  if (sends.length === 0) {
    content = (
      <div className="req-empty">
        <FileIcon name="waiting" size={44} className="receive-ghost" />
        <p>Nothing sent yet. Files show up here as people send them.</p>
      </div>
    );
  } else {
    content = (
      <div className="req-sends">
        {sends.map((s) => (
          <div className="req-send-group" key={s.shareId}>
            <p className="req-sender">
              <span className="req-sender-name">{s.sender}</span>
              <span className="num">
                {s.files.length} {s.files.length === 1 ? "file" : "files"} ·{" "}
                {formatBytes(s.files.reduce((sum, f) => sum + f.size, 0))}
              </span>
            </p>
            <div className="file-list">
              {s.files.map((f) => (
                <FileRow
                  key={f.index}
                  name={f.filename}
                  size={f.size}
                  status="done"
                  compact
                  action={
                    <a
                      className="button button-quiet file-row-action"
                      href={url(s, f.index)}
                      download
                      aria-label={`Download ${f.filename} from ${s.sender}`}
                    >
                      <ArrowDownToLine size={16} strokeWidth={2.25} />
                      <span>Download</span>
                    </a>
                  }
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <section className="req-files" aria-label="Files sent so far">
      <div className="req-files-head">
        {heading ? (
          <h3 className="req-files-title">Sent so far</h3>
        ) : (
          <p className="req-files-count num">
            {all.length === 0 ? "No files yet" : all.length === 1 ? `1 file · ${formatBytes(total)}` : ""}
          </p>
        )}
        <button type="button" className="button button-quiet" onClick={onRefresh} disabled={refreshing}>
          <RotateCw size={15} strokeWidth={2.25} className={refreshing ? "is-spinning" : undefined} />
          <span>Refresh</span>
        </button>
      </div>
      {content}
      {all.length > 1 && (
        <div className="transfer-foot req-files-foot">
          <span className="num">
            {all.length} files · {formatBytes(total)}
          </span>
          <button
            type="button"
            className="button button-primary"
            onClick={() => downloadInTurn(all.map((x) => url(x.send, x.file.index)))}
          >
            <ArrowDownToLine size={16} strokeWidth={2.25} />
            <span>Download all</span>
          </button>
        </div>
      )}
    </section>
  );
}

function closedWhen(closesAt: number) {
  const d = new Date(closesAt * 1000);
  return `at ${d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} on ${d.toLocaleDateString([], {
    weekday: "long",
  })}`;
}
