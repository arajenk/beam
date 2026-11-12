import { ArrowRight } from "lucide-react";
import { shareUrl } from "../api";
import { Sender } from "../components/Sender";
import { ShareLink } from "../components/ShareLink";
import { Window } from "../components/Window";
import { navigate } from "../route";

export function SendPage() {
  return (
    <Sender
      idleHeading="Drop files to send them"
      idleSub="Up to 10 files, 10 GB in total. The link stops working after about a day."
      doneFoot="Anyone with the link can download these for about a day."
      done={(shareId) => (
        <>
          <ShareLink url={shareUrl(shareId)} />
          <p className="crosslink">
            <span>Need files from someone?</span>
            <a href="/request" onClick={navigate}>
              Request them
              <ArrowRight size={15} strokeWidth={2.25} aria-hidden="true" />
            </a>
          </p>
        </>
      )}
    >
      {({ title, highlighted, body }) => (
        <Window title={title || "Send files"} highlighted={highlighted}>
          {body}
        </Window>
      )}
    </Sender>
  );
}
