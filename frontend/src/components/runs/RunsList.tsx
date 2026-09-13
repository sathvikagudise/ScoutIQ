import { Link } from "react-router-dom";
import type { DiscoveryRun } from "../../api/types";
import { EmptyState } from "../ui/EmptyState";
import { SkeletonCard } from "../ui/LoadingState";
import { RunCard } from "./RunCard";
import "./runs.css";

interface RunsListProps {
  runs: DiscoveryRun[];
  loading?: boolean;
}

export function RunsList({ runs, loading }: RunsListProps) {
  if (loading) {
    return (
      <div className="runs-grid" aria-label="Loading runs">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <EmptyState
        mark="◆"
        title="No runs yet"
        body="No discovery runs have been created. Start one to push the persisted pipeline end to end — discovery through qualified leads."
        action={
          <Link to="/runs/new" className="btn btn-primary btn-md">
            Start a run
          </Link>
        }
      />
    );
  }

  return (
    <div className="runs-grid">
      {runs.map((run) => (
        <RunCard key={run.run_id} run={run} />
      ))}
    </div>
  );
}