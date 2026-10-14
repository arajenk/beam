import { Clock, HardDrive, UserX } from "lucide-react";
import { BeamMark } from "./components/BeamMark";
import { DownloadPage } from "./pages/DownloadPage";
import { SendPage } from "./pages/SendPage";
import { TermsPage } from "./pages/TermsPage";
import { ABUSE_EMAIL } from "./api";

// Three routes don't need a router: /f/{id} downloads, /terms is the policy page, anything else sends.
const path = window.location.pathname;
const match = path.match(/^\/f\/([A-Za-z0-9_-]+)\/?$/);
const terms = /^\/terms\/?$/.test(path);

export default function App() {
  return (
    <div className="shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Beam home">
          <BeamMark />
          <span className="brand-name">Beam</span>
        </a>
      </header>
      <main className="stage">
        {match ? <DownloadPage fileId={match[1]} /> : terms ? <TermsPage /> : <SendPage />}
        {!terms && (
          <ul className="facts" aria-label="How Beam works">
            <li>
              <HardDrive size={16} strokeWidth={2} aria-hidden="true" />
              <span>Up to 10 GB per file</span>
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
        )}
      </main>
      <footer className="footer">
        <span>Files are stored temporarily and deleted automatically.</span>
        <nav className="footer-links" aria-label="Policies and contact">
          <a href="/terms">Terms &amp; Privacy</a>
          <a href={`mailto:${ABUSE_EMAIL}`}>Report abuse: {ABUSE_EMAIL}</a>
        </nav>
      </footer>
    </div>
  );
}
