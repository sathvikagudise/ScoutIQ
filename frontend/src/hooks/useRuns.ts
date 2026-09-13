import { useCallback, useEffect, useState } from "react";
import { listRuns } from "../api/runs";
import { ApiError } from "../api/client";
import type { DiscoveryRun } from "../api/types";

type LoadState = "loading" | "error" | "ready";

export function useRuns() {
  const [runs, setRuns] = useState<DiscoveryRun[]>([]);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      const data = await listRuns();
      setRuns(data);
      setState("ready");
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, null, String(err)));
      setState("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return { runs, state, error, reload: load };
}