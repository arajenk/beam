import { Clock, HardDrive, Inbox, UserX } from "lucide-react";
import { BeamMark } from "./components/BeamMark";
import { DownloadPage } from "./pages/DownloadPage";
import { NewRequestPage } from "./pages/NewRequestPage";
import { RequestPage } from "./pages/RequestPage";
import { SendPage } from "./pages/SendPage";
import { TermsPage } from "./pages/TermsPage";
import { ABUSE_EMAIL } from "./api";
import { navigate, useRoute } from "./route";

export default function App() {
  const { route, state } = useRoute();
  const requesting = route.page === "request" || route.page === "requested";

  return (
    <div className="shell">
      <header className="topbar">
        <a className="brand" href="/" onClick={navigate} aria-label="Beam home">
          <BeamMark />
          <span className="brand-name">Beam</span>
        </a>
        <nav className="modes" aria-label="What to do">
          <a className="mode" href="/" onClick={navigate} aria-current={route.page === "send" ? "page" : undefined}>
            Send
          </a>
          <a className="mode" href="/request" onClick={navigate} aria-current={requesting ? "page" : undefined}>
            Request
          </a>
        </nav>
      </header>
      <main className="stage">
        {route.page === "download" ? (
          <DownloadPage shareId={route.shareId} />
        ) : route.page === "terms" ? (
          <TermsPage />
        ) : route.page === "request" ? (
          <NewRequestPage />
        ) : route.page === "requested" ? (
          <RequestPage
            key={`${route.requestId}/${route.ownerKey ?? ""}`}
            requestId={route.requestId}
            ownerKey={route.ownerKey}
            justCreated={state === "created"}
          />
        ) : (
          <SendPage />
        )}
        {route.page !== "terms" &&
          (requesting ? (
            <ul className="facts" aria-label="How requests work">
              <li>
                <Inbox size={16} strokeWidth={2} aria-hidden="true" />
                <span>Up to 10 files per sender</span>
              </li>
              <li>
                <Clock size={16} strokeWidth={2} aria-hidden="true" />
                <span>Open for about a day</span>
              </li>
              <li>
                <UserX size={16} strokeWidth={2} aria-hidden="true" />
                <span>No account needed</span>
              </li>
            </ul>
          ) : (
            <ul className="facts" aria-label="How Beam works">
              <li>
                <HardDrive size={16} strokeWidth={2} aria-hidden="true" />
                <span>Up to 10 files, 10 GB in total</span>
              </li>
              <li>
                <Clock size={16} strokeWidth={2} aria-hidden="true" />
                <span>Links last about a day</span>
              </li>
              <li>
                <UserX size={16} strokeWidth={2} aria-hidden="true" />
                <span>No account needed</span>
              </li>
            </ul>
          ))}
      </main>
      <footer className="footer">
        <span>Files are stored temporarily and deleted automatically.</span>
        <nav className="footer-links" aria-label="Policies and contact">
          <a href="/terms" onClick={navigate}>
            Terms &amp; Privacy
          </a>
          <a href={`mailto:${ABUSE_EMAIL}`}>Report abuse: {ABUSE_EMAIL}</a>
        </nav>
      </footer>
    </div>
  );
}
