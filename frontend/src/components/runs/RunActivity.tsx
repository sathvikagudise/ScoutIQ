import { useRunActivity } from "../../hooks/useRunActivity";
import { formatDateTime } from "../../utils/format";
import { Card } from "../ui/Card";
import { LoadingState } from "../ui/LoadingState";
import { ErrorState } from "../ui/ErrorState";
import "./runs.css";

interface RunActivityProps {
  runId: string;
}

export function RunActivity({ runId }: RunActivityProps) {
  const { events, state, error, reload } = useRunActivity(runId);

  if (state === "loading") {
    return <LoadingState label="Loading activity" />;
  }

  if (state === "error") {
    return <ErrorState detail={error?.message} onRetry={() => void reload()} />;
  }

  if (events.length === 0) {
    return (
      <Card className="results-empty">
        <p className="results-empty-mark" aria-hidden="true">
          ·
        </p>
        <p className="state-title">No activity recorded</p>
        <p className="state-body">
          The orchestrator tracks run lifecycle by status only and writes no
          per-step activity events, so this feed is empty for executed runs.
        </p>
      </Card>
    );
  }

  return (
    <Card raised>
      <ul className="activity-list">
        {events.map((event) => (
          <li key={event.event_id} className="activity-item">
            <div className="activity-item-head">
              <span className="eyebrow">{event.phase}</span>
              <span className="mono activity-time">
                {formatDateTime(event.timestamp)}
              </span>
            </div>
            <p className="activity-message">{event.message}</p>
          </li>
        ))}
      </ul>
    </Card>
  );
}