import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";

/** The finished link, with a copy button that confirms in place. */
export function ShareLink({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      // Clipboard blocked: select the text so Cmd/Ctrl+C works.
      inputRef.current?.select();
      return;
    }
    setCopied(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 2200);
  }

  return (
    <div className="share">
      <label className="share-label" htmlFor="share-url">
        Your link
      </label>
      <div className="share-field">
        <input
          id="share-url"
          ref={inputRef}
          className="share-input"
          value={url}
          readOnly
          onFocus={(e) => e.currentTarget.select()}
        />
        <button type="button" className={`button button-primary share-copy${copied ? " is-copied" : ""}`} onClick={copy}>
          {copied ? <Check size={18} strokeWidth={2.5} /> : <Copy size={18} strokeWidth={2.25} />}
          <span>{copied ? "Copied" : "Copy link"}</span>
        </button>
      </div>
      <p className="sr-only" aria-live="polite">
        {copied ? "Link copied to clipboard" : ""}
      </p>
    </div>
  );
}
