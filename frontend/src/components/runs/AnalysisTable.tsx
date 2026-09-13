import type { BlockingCriterion, CandidateAnalysis } from "../../api/types";
import { unknown } from "../../utils/format";
import { Card } from "../ui/Card";
import { Badge, type Tone } from "../ui/Badge";
import {
  blockingLines,
  CandidateCriteria,
  type CriterionKey,
} from "./CandidateCriteriaStatus";
import "./runs.css";

interface AnalysisTableProps {
  analyses: CandidateAnalysis[];
  emptyMark: string;
  emptyTitle: string;
  emptyBody: string;
}

const CLASSIFICATION_META: Record<
  CandidateAnalysis["classification"],
  { tone: Tone; label: string }
> = {
  company_qualified: { tone: "success", label: "Company qualified" },
  near_qualified: { tone: "warning", label: "Near qualified" },
  not_qualified: { tone: "neutral", label: "Not qualified" },
  not_evaluated: { tone: "neutral", label: "Not evaluated" },
};

function BlockingCell({ blockers }: { blockers: BlockingCriterion[] }) {
  if (blockers.length === 0) {
    return <span className="results-na">—</span>;
  }
  return (
    <ul className="blocking-list">
      {blockers.map((blocker) => (
        <li key={blocker.criterion}>
          {blockingLines(blocker.criterion as CriterionKey, blocker.status)}
        </li>
      ))}
    </ul>
  );
}

export function AnalysisTable({
  analyses,
  emptyMark,
  emptyTitle,
  emptyBody,
}: AnalysisTableProps) {
  if (analyses.length === 0) {
    return (
      <Card className="results-empty">
        <p className="results-empty-mark" aria-hidden="true">
          {emptyMark}
        </p>
        <p className="state-title">{emptyTitle}</p>
        <p className="state-body">{emptyBody}</p>
      </Card>
    );
  }

  return (
    <Card
      className="results-table-wrap"
      raised
      tabIndex={0}
      ariaLabel="Analyzed companies table — scroll the card horizontally to view all columns"
    >
      <table className="results-table analysis-table">
        <thead>
          <tr>
            <th>Company</th>
            <th>Description</th>
            <th>Industry / sector</th>
            <th>Classification</th>
            <th className="analysis-criteria-head">Company criteria</th>
            <th>Blocking criterion</th>
            <th className="ta-right">Passed criteria</th>
          </tr>
        </thead>
        <tbody>
          {analyses.map((item) => (
            <tr key={item.candidate_id}>
              <td data-label="Company">
                <span className="results-company">{item.company_name}</span>
                <span className="mono results-sub">{unknown(item.candidate_id)}</span>
              </td>
              <td data-label="Description">{unknown(item.description)}</td>
              <td data-label="Industry / sector">
                {unknown(item.industry_or_sector)}
              </td>
              <td data-label="Classification">
                <Badge tone={CLASSIFICATION_META[item.classification].tone}>
                  {CLASSIFICATION_META[item.classification].label}
                </Badge>
              </td>
              <td data-label="Company criteria" className="analysis-criteria-cell">
                <CandidateCriteria criteria={item.criteria} />
              </td>
              <td data-label="Blocking criterion">
                <BlockingCell blockers={item.blocking_criteria} />
              </td>
              <td
                data-label="Passed criteria"
                className="ta-right mono analysis-passed"
              >
                {item.passed_criteria_count} / 3
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}