import type { RunStatus } from "../../api/types";
import { Badge, type Tone } from "../ui/Badge";
import "./runs.css";

const STATUS_META: Record<
  RunStatus,
  { tone: Tone; label: string; pulse?: boolean }
> = {
  pending: { tone: "neutral", label: "Pending" },
  running: { tone: "info", label: "Running", pulse: true },
  completed: { tone: "success", label: "Completed" },
  failed: { tone: "danger", label: "Failed" },
  cancelled: { tone: "neutral", label: "Cancelled" },
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const meta = STATUS_META[status] ?? { tone: "neutral" as const, label: status };
  return (
    <Badge tone={meta.tone} className={meta.pulse ? "badge-running" : undefined}>
      {meta.label}
    </Badge>
  );
}