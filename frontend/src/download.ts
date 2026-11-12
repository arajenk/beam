// Gap between files in "Download all"; browsers drop downloads started too close together.
const DOWNLOAD_GAP_MS = 800;

/**
 * Downloads each URL in turn through a hidden iframe. Each one hits the API's
 * redirect and R2 answers with Content-Disposition: attachment, so the page
 * stays put. The first time, the browser asks to allow multiple downloads.
 */
export function downloadInTurn(urls: string[]) {
  urls.forEach((url, i) => {
    window.setTimeout(() => {
      const frame = document.createElement("iframe");
      frame.hidden = true;
      frame.src = url;
      document.body.appendChild(frame);
      // long enough for the download to start; the iframe itself shows nothing
      window.setTimeout(() => frame.remove(), 60_000);
    }, i * DOWNLOAD_GAP_MS);
  });
}
