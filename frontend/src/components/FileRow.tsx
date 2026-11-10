import type { ReactNode } from "react";
import { RotateCw, X } from "lucide-react";
import { formatBytes } from "../format";
import { FileIcon } from "./FileIcon";

export type RowStatus = "staged" | "queued" | "uploading" | "done" | "failed" | "cancelled";

/**
 * One file in a share: icon, name, size, and its status. While uploading it
 * shows progress; queued and uploading files can be cancelled, staged files
 * removed, failed files retried. `action` puts a button (e.g. Download) on the right.
 */
export function FileRow({
  name,
  size,
  loaded,
  status,
  onCancel,
  onRemove,
  onRetry,
  action,
  compact = false,
}: {
  name: string;
  size: number;
  loaded?: number;
  status: RowStatus;
  onCancel?: () => void;
  onRemove?: () => void;
  onRetry?: () => void;
  action?: ReactNode;
  compact?: boolean;
}) {
  // Truncate the middle, never the extension: "Beach trip — Aug…(edited).mov".
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : "";
  const pct = size > 0 && loaded !== undefined ? Math.min(100, Math.floor((loaded / size) * 100)) : 100;
  // after 100% R2 still has to confirm the last parts and the API joins them
  const finishing = status === "uploading" && loaded !== undefined && loaded >= size;

  const close =
    (status === "uploading" || status === "queued") && onCancel ? (
      <button type="button" className="icon-button" onClick={onCancel} aria-label={`Cancel upload of ${name}`}>
        <X size={16} strokeWidth={2.25} />
      </button>
    ) : status === "staged" && onRemove ? (
      <button type="button" className="icon-button" onClick={onRemove} aria-label={`Remove ${name}`}>
        <X size={16} strokeWidth={2.25} />
      </button>
    ) : null;

  return (
    <div className={`file-row${compact ? " is-compact" : ""}`} data-status={status}>
      <FileIcon name={name} size={compact ? 36 : 44} className="file-row-icon" />
      <div className="file-row-main">
        <div className="file-row-head">
          <span className="file-row-name" title={name}>
            <span className="file-row-stem">{stem}</span>
            <span className="file-row-ext">{ext}</span>
          </span>
          {close}
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
                {finishing ? "Saving…" : `${formatBytes(loaded ?? 0)} of ${formatBytes(size)}`}
              </span>
              <span className="num">{pct}%</span>
            </div>
          </>
        ) : (
          <div className="file-row-sub">
            <span className="num">{formatBytes(size)}</span>
            {status === "queued" && <span>Waiting</span>}
            {status === "cancelled" && <span>Cancelled</span>}
            {status === "failed" && <span className="file-row-failed">Didn’t go through</span>}
          </div>
        )}
      </div>
      {status === "failed" && onRetry && (
        <button type="button" className="button button-quiet file-row-action" onClick={onRetry}>
          <RotateCw size={16} strokeWidth={2.25} />
          <span>Retry</span>
        </button>
      )}
      {action}
    </div>
  );
}
