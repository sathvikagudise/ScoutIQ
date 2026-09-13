import { postJson, request } from "./client";
import type { ActivityEvent, DiscoveryRun, RunResults } from "./types";

/** List recent runs, newest first. */
export function listRuns(limit = 20): Promise<DiscoveryRun[]> {
  return request<DiscoveryRun[]>(`/api/runs?limit=${limit}`);
}

/** Fetch one run by id. Throws ApiError(404) when the run does not exist. */
export function getRun(runId: string): Promise<DiscoveryRun> {
  return request<DiscoveryRun>(`/api/runs/${runId}`);
}

/** Create a new pending run. */
export function createRun(targetLeadCount: number): Promise<DiscoveryRun> {
  return postJson<DiscoveryRun>("/api/runs", {
    target_lead_count: targetLeadCount,
  });
}

/**
 * Run the full pipeline for a run. This is the orchestrated path: the backend
 * performs real discovery/research work and the request stays open until the
 * pipeline finishes, so callers should surface a "running" state.
 */
export function executeRun(
  runId: string,
  queries: string[],
  maxResultsPerQuery = 5,
): Promise<RunResults> {
  return postJson<RunResults>(`/api/runs/${runId}/execute`, {
    queries,
    max_results_per_query: maxResultsPerQuery,
  });
}

/** Read-only snapshot of a run's persisted output. */
export function getRunResults(runId: string): Promise<RunResults> {
  return request<RunResults>(`/api/runs/${runId}/results`);
}

/** Chronological activity feed for a run. */
export function getRunActivity(runId: string): Promise<ActivityEvent[]> {
  return request<ActivityEvent[]>(`/api/runs/${runId}/activity`);
}