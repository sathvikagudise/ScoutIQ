import type { ReactNode } from "react";
import "./ui.css";

interface EmptyStateProps {
  mark: string;
  title: string;
  body?: ReactNode;
  action?: ReactNode;
  titleTag?: "h1" | "p";
}

export function EmptyState({ mark, title, body, action, titleTag = "p" }: EmptyStateProps) {
  return (
    <div className="state">
      <div className="state-mark" aria-hidden="true">
        {mark}
      </div>
      {titleTag === "h1" ? (
        <h1 className="state-title">{title}</h1>
      ) : (
        <p className="state-title">{title}</p>
      )}
      {body ? <p className="state-body">{body}</p> : null}
      {action ? <div className="state-action">{action}</div> : null}
    </div>
  );
}