import { useEffect, useRef, useState } from "react";
import { Check, Copy, Eye, EyeOff } from "lucide-react";

/** Copies text, confirming in place; if the clipboard is blocked, selects the field so Cmd/Ctrl+C works. */
function useCopy(text: string, field: React.RefObject<HTMLInputElement | null>) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      field.current?.select();
      return;
    }
    setCopied(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 2200);
  }
  return { copied, copy };
}

function CopyButton({ copied, onClick, label = "Copy link" }: { copied: boolean; onClick: () => void; label?: string }) {
  return (
    <button type="button" className={`button button-primary share-copy${copied ? " is-copied" : ""}`} onClick={onClick}>
      {copied ? <Check size={18} strokeWidth={2.5} /> : <Copy size={18} strokeWidth={2.25} />}
      <span>{copied ? "Copied" : label}</span>
    </button>
  );
}

const withoutScheme = (url: string) => url.replace(/^https?:\/\//, "");

/** A finished link, with a copy button that confirms in place. */
export function ShareLink({
  url,
  label = "Your link",
  id = "share-url",
  fresh = false,
  short = false,
}: {
  url: string;
  label?: string;
  id?: string;
  /** Just arrived: the field gets the brief sun ring. */
  fresh?: boolean;
  /** Show it without the scheme (the copy is still the full link). */
  short?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const { copied, copy } = useCopy(url, inputRef);

  return (
    <div className={`share${fresh ? " is-fresh" : ""}`}>
      <label className="share-label" htmlFor={id}>
        {label}
      </label>
      <div className="share-field">
        <input
          id={id}
          ref={inputRef}
          className="share-input"
          value={short ? withoutScheme(url) : url}
          readOnly
          onFocus={(e) => e.currentTarget.select()}
        />
        <CopyButton copied={copied} onClick={copy} />
      </div>
      <p className="sr-only" aria-live="polite">
        {copied ? "Link copied to clipboard" : ""}
      </p>
    </div>
  );
}

/**
 * A link that works like a key: hidden until asked for, like an API key, so it
 * isn't the first thing copied by reflex or shown on a shared screen.
 */
export function SecretLink({ url, label, hint, id }: { url: string; label: string; hint: string; id: string }) {
  const [shown, setShown] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const { copied, copy } = useCopy(url, inputRef);
  // keep the part people recognise, hide the part that grants access; short enough
  // that the dots are visible in the field, so it reads as hidden rather than cut off
  const masked = `${new URL(url).host}/r/…/${"•".repeat(6)}`;

  return (
    <div className="share is-secret">
      <label className="share-label" htmlFor={id}>
        {label}
      </label>
      <div className="share-field">
        <input
          id={id}
          ref={inputRef}
          className="share-input"
          value={shown ? withoutScheme(url) : masked}
          readOnly
          aria-describedby={`${id}-hint`}
          onFocus={(e) => shown && e.currentTarget.select()}
        />
        <button
          type="button"
          className="icon-button share-reveal"
          onClick={() => setShown((s) => !s)}
          aria-label={shown ? "Hide link" : "Show link"}
          aria-pressed={shown}
        >
          {shown ? <EyeOff size={18} strokeWidth={2.25} /> : <Eye size={18} strokeWidth={2.25} />}
        </button>
        <CopyButton copied={copied} onClick={copy} />
      </div>
      <p className="share-hint" id={`${id}-hint`}>
        {hint}
      </p>
      <p className="sr-only" aria-live="polite">
        {copied ? "Private link copied to clipboard" : ""}
      </p>
    </div>
  );
}
