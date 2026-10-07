import type { ReactNode } from "react";

/** The app's one container: a desktop-style window with a title bar. */
export function Window({
  title,
  meta,
  highlighted = false,
  children,
}: {
  title: ReactNode;
  meta?: ReactNode;
  highlighted?: boolean;
  children: ReactNode;
}) {
  return (
    <section className={`window${highlighted ? " is-highlighted" : ""}`}>
      <header className="window-bar">
        <span />
        <h1 className="window-title">{title}</h1>
        {meta ? <span className="window-meta">{meta}</span> : <span />}
      </header>
      <div className="window-body">{children}</div>
    </section>
  );
}
