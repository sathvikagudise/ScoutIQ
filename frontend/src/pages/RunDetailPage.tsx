import { Link, useParams } from "react-router-dom";
import { useRun } from "../hooks/useRun";
import { formatDateTime, unknown } from "../utils/format";
import { Card } from "../components/ui/Card";
import { Metric } from "../components/ui/Metric";
import { SectionHeader } from "../components/ui/SectionHeader";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { LoadingState } from "../components/ui/LoadingState";
import { RunStatusBadge } from "../components/runs/RunStatusBadge";
import { RunActivity } from "../components/runs/RunActivity";
import "../components/runs/runs.css";

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const { run, state, error, reload } = useRun(runId ?? "");

  if (state === "loading") {
    return <LoadingState label="Loading run" />;
  }

  if (state === "error") {
    if (error?.status === 404) {
      return (
        <EmptyState
          mark="?"
          title="Run not found"
          body="No run exists with this id. It may have been created in a different environment or removed from the database."
          action={
            <Link to="/runs" className="btn btn-primary btn-md">
              Back to runs
            </Link>
          }
          titleTag="h1"
        />
      );
    }
    return (
      <ErrorState
        title="Could not load this run"
        detail={error?.message}
        onRetry={() => void reload()}
      />
    );
  }

  if (run === null) {
    return <EmptyState mark="?" title="Run unavailable" />;
  }

  return (
    <div className="run-detail">
      <Link to="/runs" className="back-link">
        &larr; All runs
      </Link>

      <SectionHeader
        eyebrow="Run detail"
        title="Run summary"
        description="Execution state and outcome are read directly from the backend run record."
        action={
          run.status === "completed" ? (
            <Link to={`/runs/${run.run_id}/results`} className="btn btn-primary btn-md">
              View results
            </Link>
          ) : undefined
        }
      />

      <div className="run-detail-head">
        <RunStatusBadge status={run.status} />
        <span className="mono run-detail-id">{run.run_id}</span>
      </div>

      <div className="run-detail-meta-grid">
        <Metric
          label="Qualified leads"
          value={`${run.qualified_lead_count} / ${run.target_lead_count}`}
          hint="qualified leads / target lead count"
        />
        <Metric label="Started" value={formatDateTime(run.started_at)} />
        <Metric label="Completed" value={formatDateTime(run.completed_at)} />
        <Metric
          label="Current phase"
          value={unknown(run.current_phase)}
          hint="The orchestrator tracks status only; phases are not written per step."
        />
      </div>

      {run.status === "failed" ? (
        <Card className="phase-note" raised>
          <p className="phase-note-label">Failure</p>
          <p className="phase-note-body">
            {run.error_message ?? "The run failed without a persisted message."}
          </p>
        </Card>
      ) : null}

      {run.status === "completed" ? (
        <Card className="phase-note" raised>
          <p className="phase-note-label">Outcome</p>
          <p className="phase-note-body">
            {run.qualified_lead_count} of {run.target_lead_count} target leads
            were qualified with persisted evidence. Open the results workspace
            to inspect leads and contacts.
          </p>
        </Card>
      ) : null}

      <h2 className="results-section-title">Activity</h2>
      <RunActivity runId={run.run_id} />
    </div>
  );
}