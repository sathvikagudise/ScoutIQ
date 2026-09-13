import { Link } from "react-router-dom";
import { useRuns } from "../hooks/useRuns";
import { Metric } from "../components/ui/Metric";
import { SectionHeader } from "../components/ui/SectionHeader";
import { ErrorState } from "../components/ui/ErrorState";
import { RunsList } from "../components/runs/RunsList";
import "../components/runs/runs.css";

function MetricSkeleton() {
  return (
    <div className="metric metric-skeleton" aria-hidden="true">
      <div className="skeleton skeleton-line skeleton-line-sm" />
      <div className="skeleton skeleton-line" style={{ width: "46%" }} />
    </div>
  );
}

export function RunsPage() {
  const { runs, state, error, reload } = useRuns();

  const completed = runs.filter((run) => run.status === "completed").length;
  const inProgress = runs.filter(
    (run) => run.status === "pending" || run.status === "running",
  ).length;
  const qualifiedLeads = runs.reduce(
    (sum, run) => sum + run.qualified_lead_count,
    0,
  );

  return (
    <div>
      <SectionHeader
        eyebrow="Workspace"
        title="Runs"
        description="Discovery executions and their pipeline outcomes. Each run follows the full orchestrated pipeline: discovery, research, extraction, qualification, contacts, leads, and completion."
        action={
          <Link to="/runs/new" className="btn btn-primary btn-md">
            New run
          </Link>
        }
      />

      <div className="metrics-strip">
        {state === "ready" ? (
          <>
            <Metric label="Total runs" value={runs.length} />
            <Metric label="Completed" value={completed} />
            <Metric
              label="In progress"
              value={inProgress}
              hint="pending or running"
            />
            <Metric label="Qualified leads" value={qualifiedLeads} />
          </>
        ) : (
          <>
            <MetricSkeleton />
            <MetricSkeleton />
            <MetricSkeleton />
            <MetricSkeleton />
          </>
        )}
      </div>

      {state === "error" ? (
        <ErrorState
          title="The run list could not be loaded"
          detail={error?.message}
          onRetry={() => void reload()}
        />
      ) : (
        <div>
          <p className="eyebrow runs-recent-label">Recent runs</p>
          <RunsList runs={runs} loading={state === "loading"} />
        </div>
      )}
    </div>
  );
}