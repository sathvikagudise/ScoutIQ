import type { ContactReadiness } from "../../api/types";
import { Badge, type Tone } from "../ui/Badge";

const META: Record<ContactReadiness, { tone: Tone; label: string }> = {
  evidenced_contact: {
    tone: "accent",
    label: "Named contact with evidence-backed email",
  },
  named_contact_no_email: {
    tone: "info",
    label: "Named leader found — email not publicly attributed",
  },
  public_email_available: {
    tone: "info",
    label: "Public company email available",
  },
  company_contact_available: {
    tone: "neutral",
    label: "Use available company contact channel",
  },
  no_contact_found: {
    tone: "neutral",
    label: "No public contact evidence found",
  },
};

export function ContactReadinessBadge({
  readiness,
}: {
  readiness: ContactReadiness | null;
}) {
  const meta =
    readiness === null
      ? { tone: "neutral" as const, label: "Not enriched" }
      : META[readiness] ?? { tone: "neutral" as const, label: readiness };
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}