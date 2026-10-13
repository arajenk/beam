// ─────────────────────────────────────────────────────────────────────────────
// Cloudflare Turnstile: proves a person (not a script) is starting an upload.
//
// The widget runs a challenge in the browser and hands back a token. The API
// checks that token with Cloudflare before signing anything. Tokens are
// single-use and expire after 5 minutes, so we get a fresh one per upload.
// The widget stays hidden unless Cloudflare decides it needs a click.
// ─────────────────────────────────────────────────────────────────────────────

type Turnstile = {
  render: (container: HTMLElement, options: Record<string, unknown>) => string;
  execute: (widgetId: string) => void;
  reset: (widgetId: string) => void;
  remove: (widgetId: string) => void;
};

declare global {
  interface Window {
    turnstile?: Turnstile;
  }
}

// Public by design. Defaults to Cloudflare's always-pass test key for local dev.
const SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY ?? "1x00000000000000000000AA";
const SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

let loading: Promise<Turnstile> | null = null;

function load(): Promise<Turnstile> {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  loading ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SCRIPT_URL;
    script.async = true;
    script.onload = () => (window.turnstile ? resolve(window.turnstile) : reject(new Error("Turnstile missing")));
    script.onerror = () => {
      loading = null;
      reject(new Error("Couldn't load Turnstile"));
    };
    document.head.appendChild(script);
  });
  return loading;
}

let widget: { id: string; container: HTMLElement } | null = null;
let pending: { resolve: (token: string) => void; reject: (err: Error) => void } | null = null;

const settle = (fn: (p: NonNullable<typeof pending>) => void) => {
  if (pending) fn(pending);
  pending = null;
};

/** Runs the challenge in `container` and resolves with a fresh token. */
export async function getTurnstileToken(container: HTMLElement): Promise<string> {
  const ts = await load();
  settle((p) => p.reject(new Error("Superseded")));

  return new Promise((resolve, reject) => {
    pending = { resolve, reject };
    // The page may have re-mounted since last time, so render into the current container.
    if (!widget || widget.container !== container || !container.isConnected) {
      if (widget) ts.remove(widget.id);
      const id = ts.render(container, {
        sitekey: SITE_KEY,
        execution: "execute",
        appearance: "interaction-only",
        callback: (token: string) => settle((p) => p.resolve(token)),
        "error-callback": () => settle((p) => p.reject(new Error("Turnstile failed"))),
        "expired-callback": () => settle((p) => p.reject(new Error("Turnstile expired"))),
      });
      widget = { id, container };
    } else {
      // the last token was spent on the previous upload
      ts.reset(widget.id);
    }
    ts.execute(widget.id);
  });
}
