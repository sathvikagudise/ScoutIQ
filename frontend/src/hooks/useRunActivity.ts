import { useCallback, useEffect, useState } from "react";
import { getRunActivity } from "../api/runs";
import { ApiError } from "../api/client";
import type { ActivityEvent } from "../api/types";

type LoadState = "loading" | "error" | "ready";

export function useRunActivity(runId: string) {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      setEvents(await getRunActivity(runId));
      setState("ready");
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, null, String(err)));
      setState("error");
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  return { events, state, error, reload: load };
}