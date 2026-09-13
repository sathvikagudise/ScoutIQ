import type { ReactNode } from "react";
import { Button } from "./Button";
import "./ui.css";

interface ErrorStateProps {
  title?: string;
  detail?: ReactNode;
  retryLabel?: string;
  onRetry?: () => void;
}

/** Consistent, retriable error surface for API failures. */
export function ErrorState({
  title = "Could not load this view",
  detail,
  retryLabel = "Retry",
  onRetry,
}: ErrorStateProps) {
  return (
    <div className="state">
      <div className="state-mark" aria-hidden="true">
        !
      </div>
      <p className="state-title">{title}</p>
      {detail ? <p className="state-body">{detail}</p> : null}
      {onRetry ? (
        <div className="state-action">
          <Button variant="secondary" onClick={onRetry}>
            {retryLabel}
          </Button>
        </div>
      ) : null}
    </div>
  );
}