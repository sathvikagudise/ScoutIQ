import type { VerificationStatus } from "../../api/types";
import { Badge, type Tone } from "../ui/Badge";

const META: Record<VerificationStatus, { tone: Tone; label: string }> = {
  unverified: { tone: "neutral", label: "Unverified" },
  evidenced: { tone: "accent", label: "Evidenced" },
  verified: { tone: "success", label: "Verified" },
};

export function VerificationBadge({ status }: { status: VerificationStatus }) {
  const meta = META[status] ?? { tone: "neutral" as const, label: status };
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}