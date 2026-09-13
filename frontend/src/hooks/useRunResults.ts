import { useCallback, useEffect, useState } from "react";
import { getRunResults } from "../api/runs";
import { ApiError } from "../api/client";
import type { RunResults } from "../api/types";

type LoadState = "loading" | "error" | "ready";

/**
 * Fetch a run's persisted results. Polls every `intervalMs` while the run's
 * persisted status is pending/running, so a run still executing (created but
 * not yet finished, or executing outside this tab) resolves on its own.
 */
export function useRunResults(runId: string, intervalMs = 4000) {
  const [results, setResults] = useState<RunResults | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      setResults(await getRunResults(runId));
      setState("ready");
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, null, String(err)));
      setState("error");
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  const active =
    results !== null &&
    (results.run.status === "pending" || results.run.status === "running");

  useEffect(() => {
    if (!active || state !== "ready") {
      return;
    }
    const timer = window.setTimeout(() => void load(), intervalMs);
    return () => window.clearTimeout(timer);
  }, [active, state, intervalMs, load]);

  return { results, state, error, reload: load };
}