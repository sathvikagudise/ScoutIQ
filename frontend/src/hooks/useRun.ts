import { useCallback, useEffect, useState } from "react";
import { getRun } from "../api/runs";
import { ApiError } from "../api/client";
import type { DiscoveryRun } from "../api/types";

type LoadState = "loading" | "error" | "ready";

interface UseRunOptions {
  pollWhileActive?: boolean;
  intervalMs?: number;
}

/**
 * Fetch a single run. When `pollWhileActive` is set, the run is re-fetched
 * every `intervalMs` while its persisted status is non-terminal (pending or
 * running), so a run executing elsewhere in the system surfaces in the UI.
 */
export function useRun(runId: string, options: UseRunOptions = {}) {
  const { pollWhileActive = false, intervalMs = 4000 } = options;
  const [run, setRun] = useState<DiscoveryRun | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      setRun(await getRun(runId));
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
    run !== null && (run.status === "pending" || run.status === "running");

  useEffect(() => {
    if (!pollWhileActive || !active || state !== "ready") {
      return;
    }
    const timer = window.setTimeout(() => void load(), intervalMs);
    return () => window.clearTimeout(timer);
  }, [pollWhileActive, active, state, intervalMs, load]);

  return { run, state, error, reload: load };
}