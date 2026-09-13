import type { CriterionStatus } from "../../api/types";
import { cn } from "../../utils/cn";

export const CRITERION_LABELS = {
  financial: "Financial",
  tech_platform: "Tech platform",
  us_presence: "US presence",
} as const;

export type CriterionKey = keyof typeof CRITERION_LABELS;

const STATUS_META: Record<
  CriterionStatus,
  { mark: string; label: string; tone: "pass" | "fail" | "warn" | "none" }
> = {
  pass: { mark: "✓", label: "Pass", tone: "pass" },
  fail: { mark: "✕", label: "Failed", tone: "fail" },
  insufficient_evidence: {
    mark: "~",
    label: "Insufficient evidence",
    tone: "warn",
  },
  not_evaluated: { mark: "—", label: "Not evaluated", tone: "none" },
  none: { mark: "—", label: "No data", tone: "none" },
};

interface CandidateCriteriaProps {
  criteria: Record<CriterionKey, { status: CriterionStatus }>;
}

/** The three company criterion outcomes as marked, labelled chips (never
 * color-only: each chip carries an explicit text label). */
export function CandidateCriteria({ criteria }: CandidateCriteriaProps) {
  return (
    <div className="criteria-chips">
      {(Object.keys(CRITERION_LABELS) as CriterionKey[]).map((key) => {
        const meta = STATUS_META[criteria[key].status];
        return (
          <span
            key={key}
            className={cn("criterion-chip", `criterion-chip-${meta.tone}`)}
          >
            <span className="criterion-chip-mark" aria-hidden="true">
              {meta.mark}
            </span>
            <span className="criterion-chip-text">
              <span className="criterion-chip-name">{CRITERION_LABELS[key]}</span>
              <span className="criterion-chip-value">{meta.label}</span>
            </span>
          </span>
        );
      })}
    </div>
  );
}

/** Human-readable blocking line for persisted criterion outcomes. A persisted
 * FAIL is "criterion failed"; a persisted INSUFFICIENT_EVIDENCE is "missing
 * evidence". The two are never merged or aliased. */
export function blockingLines(criterion: CriterionKey, status: CriterionStatus): string {
  const name = CRITERION_LABELS[criterion].toLowerCase();
  if (status === "fail") {
    return `Failed: ${name} criterion`;
  }
  if (status === "insufficient_evidence") {
    return `Missing: ${name} evidence`;
  }
  return `Not evaluated: ${name}`;
}