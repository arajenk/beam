import { X } from "lucide-react";
import { formatBytes } from "../format";
import { FileIcon } from "./FileIcon";

/**
 * One file in a transfer: icon, name, size, and (while uploading) progress.
 * Rendered once today; a multi-file share renders a list of these.
 */
export function FileRow({
  name,
  size,
  loaded,
  status,
  onCancel,
}: {
  name: string;
  size: number;
  loaded?: number;
  status: "uploading" | "done";
  onCancel?: () => void;
}) {
  // Truncate the middle, never the extension: "Beach trip — Aug…(edited).mov".
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : "";
  const pct = size > 0 && loaded !== undefined ? Math.min(100, Math.floor((loaded / size) * 100)) : 100;

  return (
    <div className="file-row" data-status={status}>
      <FileIcon name={name} size={44} className="file-row-icon" />
      <div className="file-row-main">
        <div className="file-row-head">
          <span className="file-row-name" title={name}>
            <span className="file-row-stem">{stem}</span>
            <span className="file-row-ext">{ext}</span>
          </span>
          {status === "uploading" && onCancel && (
            <button type="button" className="icon-button" onClick={onCancel} aria-label={`Cancel upload of ${name}`}>
              <X size={16} strokeWidth={2.25} />
            </button>
          )}
        </div>
        {status === "uploading" ? (
          <>
            <div
              className="progress"
              role="progressbar"
              aria-label={`Uploading ${name}`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={pct}
            >
              <div className="progress-fill" style={{ transform: `scaleX(${pct / 100})` }} />
            </div>
            <div className="file-row-sub">
              <span className="num">
                {formatBytes(loaded ?? 0)} of {formatBytes(size)}
              </span>
              <span className="num">{pct}%</span>
            </div>
          </>
        ) : (
          <div className="file-row-sub">
            <span className="num">{formatBytes(size)}</span>
          </div>
        )}
      </div>
    </div>
  );
}
