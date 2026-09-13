import type { CandidateAnalysis, ContactReadiness, QualifiedLead } from "../../api/types";
import { unknown } from "../../utils/format";
import { Card } from "../ui/Card";
import { Badge } from "../ui/Badge";
import { ContactReadinessBadge } from "./ContactReadinessBadge";
import { CandidateCriteria } from "./CandidateCriteriaStatus";
import "./runs.css";

interface LeadsTableProps {
  leads: QualifiedLead[];
  analyses?: Record<string, CandidateAnalysis>;
}

const CONTACT_SUGGESTION: Record<
  ContactReadiness,
  { label: string; hint?: string }
> = {
  evidenced_contact: {
    label: "Contact the named leader on public channels",
    hint: "an evidence-backed email for the named leader is recorded",
  },
  named_contact_no_email: {
    label: "Contact the named leader via the company site",
    hint: "no email is publicly attributed to that person",
  },
  public_email_available: {
    label: "Use the public company email",
    hint: "persisted public email above",
  },
  company_contact_available: {
    label: "Use the company contact page",
    hint: "no named leader with a public email was found",
  },
  no_contact_found: {
    label: "No public contact channel found",
  },
};

export function LeadsTable({ leads, analyses = {} }: LeadsTableProps) {
  if (leads.length === 0) {
    return (
      <Card className="results-empty">
        <p className="results-empty-mark" aria-hidden="true">
          —
        </p>
        <p className="state-title">No company-qualified leads</p>
        <p className="state-body">
          No company satisfied all three company qualification criteria
          (funding/revenue, tech platform, minimal US presence) with sufficient
          persisted evidence. This is an honest outcome, not a failure — the
          funnel above shows where companies dropped out.
        </p>
      </Card>
    );
  }

  return (
    <Card
      className="results-table-wrap"
      raised
      tabIndex={0}
      ariaLabel="Qualified leads table — scroll the card horizontally to view all columns"
    >
      <table className="results-table">
        <thead>
          <tr>
            <th>Company</th>
            <th>Description</th>
            <th>Industry / sector</th>
            <th>Company qualification</th>
            <th className="analysis-criteria-head">Company criteria</th>
            <th>CEO / co-founder</th>
            <th>Email</th>
            <th>Contact readiness</th>
            <th>Contact suggestion</th>
            <th className="ta-right">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {leads.map((lead) => {
            const analysis = analyses[lead.candidate_id];
            return (
              <tr key={lead.lead_id}>
                <td data-label="Company">
                  <span className="results-company">{lead.company_name}</span>
                  <span className="mono results-sub">{unknown(lead.lead_id)}</span>
                </td>
                <td data-label="Description">{unknown(lead.description)}</td>
                <td data-label="Industry / sector">
                  {unknown(lead.industry_or_sector)}
                </td>
                <td data-label="Company qualification">
                  <Badge tone="success">Company qualified</Badge>
                </td>
                <td data-label="Company criteria" className="analysis-criteria-cell">
                  {analysis ? (
                    <CandidateCriteria criteria={analysis.criteria} />
                  ) : (
                    <span className="results-na">—</span>
                  )}
                </td>
                <td data-label="CEO / co-founder">
                  {unknown(lead.ceo_or_cofounder_name)}
                </td>
                <td data-label="Email">
                  {lead.verified_email ? (
                    <span className="results-email">{lead.verified_email}</span>
                  ) : (
                    <span className="results-na">—</span>
                  )}
                </td>
                <td data-label="Contact readiness">
                  <ContactReadinessBadge readiness={lead.contact_readiness} />
                </td>
                <td data-label="Contact suggestion">
                  {lead.contact_readiness === null ? (
                    <span className="results-na">—</span>
                  ) : (
                    <span className="results-suggestion">
                      {CONTACT_SUGGESTION[lead.contact_readiness]?.label ?? "—"}
                    </span>
                  )}
                </td>
                <td
                  data-label="Evidence"
                  className={
                    lead.evidence_ids.length === 0
                      ? "ta-right mono results-evidence-zero"
                      : "ta-right mono"
                  }
                >
                  {lead.evidence_ids.length}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}