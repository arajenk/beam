import { useEffect, useRef, useState, type FormEvent } from "react";
import { createRequest, UploadError } from "../api";
import { FileIcon } from "../components/FileIcon";
import { ErrorNotice } from "../components/Sender";
import { Window } from "../components/Window";
import { go } from "../route";
import { prepareTurnstile, takeTurnstileToken } from "../turnstile";

const NOTE_LIMIT = 500;
const NAME_LIMIT = 50;

/** /request: write a note, choose who can see what's sent, get the link. */
export function NewRequestPage() {
  const [note, setNote] = useState("");
  const [name, setName] = useState("");
  const [privateFiles, setPrivateFiles] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const challenge = useRef<HTMLDivElement>(null);
  const noteBox = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    document.title = "Request files · Beam";
  }, []);

  // Writing the note takes a while; solve the Turnstile challenge meanwhile.
  const prepare = () => {
    if (challenge.current) prepareTurnstile(challenge.current);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!note.trim()) {
      setError("Write a note so people know what to send.");
      noteBox.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    createRequest({ note: note.trim(), name, private: privateFiles }, () =>
      challenge.current ? takeTurnstileToken(challenge.current) : Promise.reject(new Error("No challenge slot")),
    ).then(
      ({ requestId, ownerKey }) => {
        // Land on the link they'll need again, so history, bookmarks and refresh all keep it.
        go(privateFiles ? `/r/${requestId}/${ownerKey}` : `/r/${requestId}`, "created");
      },
      (err: unknown) => {
        setBusy(false);
        setError(
          err instanceof UploadError && err.kind === "verification"
            ? "We couldn’t check that you’re a person. Try again."
            : "The request didn’t go through. Check your connection and try again.",
        );
      },
    );
  };

  return (
    <Window title="Request files">
      <form className="ask" onSubmit={submit} noValidate>
        <div className="ask-head">
          {/* the send page's file fan, so both sides of Beam open the same way */}
          <div className="drop-art" aria-hidden="true">
            <FileIcon name="photo.jpg" size={64} className="drop-file drop-file-a" />
            <FileIcon name="notes.pdf" size={72} className="drop-file drop-file-b" />
            <FileIcon name="project.zip" size={64} className="drop-file drop-file-c" />
          </div>
          <h2 className="ask-heading">Ask someone for files</h2>
          <p className="ask-sub">Write what you need and share the link. They send files straight to you, no account needed.</p>
        </div>

        <label className="field-label" htmlFor="ask-note">
          Note
        </label>
        <textarea
          id="ask-note"
          ref={noteBox}
          className="field field-note"
          value={note}
          maxLength={NOTE_LIMIT}
          rows={4}
          placeholder="Send me your slides for Friday’s presentation."
          onFocus={prepare}
          onChange={(e) => setNote(e.target.value)}
          aria-describedby="ask-note-count"
        />
        <p id="ask-note-count" className="field-count num">
          {note.length} / {NOTE_LIMIT}
        </p>

        <label className="field-label" htmlFor="ask-name">
          Your name <span className="field-optional">(optional)</span>
        </label>
        <input
          id="ask-name"
          className="field"
          value={name}
          maxLength={NAME_LIMIT}
          autoComplete="given-name"
          placeholder="So they know who’s asking"
          onFocus={prepare}
          onChange={(e) => setName(e.target.value)}
        />

        <div className="toggle-row">
          <div className="toggle-text">
            <span className="toggle-title" id="ask-private-label">
              Only I can see the files
            </span>
            <span className="toggle-desc" id="ask-private-desc">
              {privateFiles
                ? "People can send files, but only your private link shows them."
                : "Everyone with the link can send files and see what’s been sent."}
            </span>
          </div>
          <button
            type="button"
            role="switch"
            className="switch"
            aria-checked={privateFiles}
            aria-labelledby="ask-private-label"
            aria-describedby="ask-private-desc"
            onClick={() => setPrivateFiles((on) => !on)}
          >
            <span className="switch-knob" />
          </button>
        </div>

        {error && <ErrorNotice message={error} />}

        <div className="ask-foot">
          <span>The request takes files for about a day.</span>
          <button type="submit" className="button button-primary" disabled={busy}>
            {busy ? "Creating…" : "Create request"}
          </button>
        </div>
        <div ref={challenge} className="challenge" />
      </form>
    </Window>
  );
}
