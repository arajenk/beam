import { useEffect } from "react";
import { ABUSE_EMAIL } from "../api";
import { Window } from "../components/Window";

/** Terms and privacy in one short page, in plain words. */
export function TermsPage() {
  useEffect(() => {
    document.title = "Terms & Privacy · Beam";
  }, []);

  const abuse = <a href={`mailto:${ABUSE_EMAIL}`}>{ABUSE_EMAIL}</a>;

  return (
    <Window title="Terms & Privacy">
      <article className="legal">
        <p className="legal-updated">Last updated October 14, 2026</p>

        <h2>Using Beam</h2>
        <ul>
          <li>Beam is free and comes with no guarantees. Links stop working after about a day, so keep your own copy of anything important.</li>
          <li>Don’t upload illegal content, malware, or anything you don’t have the right to share.</li>
          <li>We can remove any file and block uploads that break these rules, without notice.</li>
        </ul>

        <h2>Reporting a file</h2>
        <p>
          Use “Report this file” on the download page, or email {abuse}. We don’t look through uploaded files, so
          reports are how we find out about a problem.
        </p>

        <h2>Privacy</h2>
        <ul>
          <li>
            Your file and its name are stored with Cloudflare R2 and deleted automatically, usually within a day or two
            of uploading.
          </li>
          <li>File contents go straight from your browser to storage. Our server never sees them.</li>
          <li>
            Our server keeps your IP address in memory to enforce upload limits, until it restarts (about once a day).
            It isn’t saved anywhere else by us.
          </li>
          <li>
            Our providers process IP addresses to run the service and may keep short-lived logs: Cloudflare (this
            website, file storage, and the bot check) and Heroku (our server).
          </li>
          <li>If you include your email in a report, we use it only to reply to you.</li>
          <li>No accounts, no ads, and no analytics or tracking of our own.</li>
        </ul>

        <h2>Contact</h2>
        <p>Questions or problems: {abuse}.</p>
      </article>
    </Window>
  );
}
