import { Link } from "react-router-dom";
import type { DiscoveryRun } from "../../api/types";
import { formatDateTime, shortId, unknown } from "../../utils/format";
import { Card } from "../ui/Card";
import { RunStatusBadge } from "./RunStatusBadge";
import "./runs.css";

interface RunCardProps {
  run: DiscoveryRun;
}

export function RunCard({ run }: RunCardProps) {
  const failure = run.status === "failed";
  return (
    <Link to={`/runs/${run.run_id}`} className="run-card-link">
      <Card className="run-card">
        <div className="run-card-top">
          <RunStatusBadge status={run.status} />
          <span className="mono run-card-id">{shortId(run.run_id)}</span>
        </div>
        <div className="run-card-body">
          <p className="run-card-count">
            <span className="run-card-count-value">
              {run.qualified_lead_count}
            </span>
            <span className="run-card-count-total">
              / {run.target_lead_count}
            </span>
          </p>
          <p className="run-card-count-label">qualified leads / target</p>
        </div>
        <dl className="run-card-meta">
          <div>
            <dt>Started</dt>
            <dd>{formatDateTime(run.started_at)}</dd>
          </div>
          <div>
            <dt>Completed</dt>
            <dd>{formatDateTime(run.completed_at)}</dd>
          </div>
        </dl>
        {failure ? (
          <p className="run-card-error" title={unknown(run.error_message)}>
            {run.error_message ?? "The run failed."}
          </p>
        ) : null}
        <p className="run-card-open" aria-hidden="true">
          Open run &rarr;
        </p>
      </Card>
    </Link>
  );
}