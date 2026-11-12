import { useEffect, useState, type MouseEvent } from "react";

// A handful of routes don't need a router library: real URLs (so back,
// refresh and bookmarks work) plus pushState for moves inside the app.
export type Route =
  | { page: "send" }
  | { page: "terms" }
  | { page: "download"; shareId: string }
  | { page: "request" }
  | { page: "requested"; requestId: string; ownerKey?: string };

const ID = "[A-Za-z0-9_-]+";

export function parseRoute(path: string): Route {
  const share = path.match(new RegExp(`^/f/(${ID})/?$`));
  if (share) return { page: "download", shareId: share[1] };
  const requested = path.match(new RegExp(`^/r/(${ID})(?:/(${ID}))?/?$`));
  if (requested) return { page: "requested", requestId: requested[1], ownerKey: requested[2] };
  if (/^\/request\/?$/.test(path)) return { page: "request" };
  if (/^\/terms\/?$/.test(path)) return { page: "terms" };
  return { page: "send" };
}

const CHANGE = "beam:navigate";

/** Go to an in-app URL without reloading. `state` rides along in history (e.g. "just created"). */
export function go(url: string, state: unknown = null) {
  window.history.pushState(state, "", url);
  window.scrollTo(0, 0);
  window.dispatchEvent(new Event(CHANGE));
}

/** onClick for in-app links: same as go(), but lets modifier clicks open a new tab as usual. */
export function navigate(e: MouseEvent<HTMLAnchorElement>) {
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
  e.preventDefault();
  go(e.currentTarget.getAttribute("href") ?? "/");
}

/** The current route and its history state; updates on back/forward and go(). */
export function useRoute(): { route: Route; state: unknown } {
  const read = () => ({ route: parseRoute(window.location.pathname), state: window.history.state as unknown });
  const [current, setCurrent] = useState(read);
  useEffect(() => {
    const update = () => setCurrent(read());
    window.addEventListener("popstate", update);
    window.addEventListener(CHANGE, update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener(CHANGE, update);
    };
  }, []);
  return current;
}
