import { Card } from "./Card";
import { Spinner } from "./Spinner";
import "./ui.css";

/** Full-panel loading state. */
export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="loading-panel" role="status" aria-label={label}>
      <Spinner />
      <p className="state-body">{label}…</p>
    </div>
  );
}

/** Skeleton card used while lists hydrate. */
export function SkeletonCard() {
  return (
    <Card className="skeleton-card">
      <div className="skeleton skeleton-line skeleton-line-sm" />
      <div className="skeleton skeleton-line" />
      <div className="skeleton skeleton-line skeleton-line-xs" />
      <div className="skeleton skeleton-line skeleton-line-xs" />
    </Card>
  );
}