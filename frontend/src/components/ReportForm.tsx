import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertCircle, CheckCircle2, Flag } from "lucide-react";
import { ABUSE_EMAIL, ReportError, sendReport } from "../api";
import { prepareTurnstile, takeTurnstileToken } from "../turnstile";

const MAX_REASON = 2000;

type State =
  | { phase: "closed" }
  | { phase: "open"; error?: string }
  | { phase: "sending" }
  | { phase: "sent" };

/** "Report this file" under the Download button; opens a short form that emails the report to us. */
export function ReportForm({ fileId }: { fileId: string }) {
  const [state, setState] = useState<State>({ phase: "closed" });
  const [reason, setReason] = useState("");
  const [email, setEmail] = useState("");
  const challenge = useRef<HTMLDivElement>(null);
  const reasonBox = useRef<HTMLTextAreaElement>(null);

  // Writing a report takes a while; solve the Turnstile challenge meanwhile.
  useEffect(() => {
    if (state.phase === "open" && !state.error) {
      reasonBox.current?.focus();
      if (challenge.current) prepareTurnstile(challenge.current);
    }
  }, [state]);

  if (state.phase === "closed") {
    return (
      <button type="button" className="report-toggle" onClick={() => setState({ phase: "open" })}>
        <Flag size={14} strokeWidth={2.25} aria-hidden="true" />
        <span>Report this file</span>
      </button>
    );
  }

  if (state.phase === "sent") {
    return (
      <p className="notice report-done" role="status">
        <CheckCircle2 size={18} strokeWidth={2.25} />
        <span>Thanks. We’ll look into it.</span>
      </p>
    );
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!reason.trim()) return;
    setState({ phase: "sending" });
    sendReport(fileId, reason.trim(), email.trim(), () =>
      challenge.current ? takeTurnstileToken(challenge.current) : Promise.reject(new Error("No challenge slot")),
    ).then(
      () => setState({ phase: "sent" }),
      (err: unknown) => {
        const kind = err instanceof ReportError ? err.kind : "failed";
        const error =
          kind === "verification"
            ? "We couldn’t check that you’re a person. Try again."
            : `We couldn’t send your report. Email ${ABUSE_EMAIL} instead.`;
        setState({ phase: "open", error });
      },
    );
  };

  const sending = state.phase === "sending";
  return (
    <form className="report" onSubmit={submit}>
      <label className="report-label" htmlFor="report-reason">
        What’s wrong with this file?
      </label>
      <textarea
        id="report-reason"
        ref={reasonBox}
        className="report-field report-reason"
        required
        maxLength={MAX_REASON}
        rows={3}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        disabled={sending}
      />
      <label className="report-label" htmlFor="report-email">
        Your email <span className="report-optional">(optional, if you want a reply)</span>
      </label>
      <input
        id="report-email"
        className="report-field"
        type="email"
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        disabled={sending}
      />
      {state.phase === "open" && state.error && (
        <p className="notice notice-error" role="alert">
          <AlertCircle size={18} strokeWidth={2.25} />
          <span>{state.error}</span>
        </p>
      )}
      <div ref={challenge} className="challenge" />
      <div className="report-actions">
        <button type="button" className="button button-quiet" onClick={() => setState({ phase: "closed" })} disabled={sending}>
          Cancel
        </button>
        <button type="submit" className="button button-primary" disabled={sending || !reason.trim()}>
          {sending ? "Sending…" : "Send report"}
        </button>
      </div>
    </form>
  );
}
