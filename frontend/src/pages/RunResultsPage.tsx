import { Link, useParams } from "react-router-dom";
import { useRunResults } from "../hooks/useRunResults";
import { formatDateTime } from "../utils/format";
import { Card } from "../components/ui/Card";
import { Metric } from "../components/ui/Metric";
import { SectionHeader } from "../components/ui/SectionHeader";
import { LoadingState } from "../components/ui/LoadingState";
import { ErrorState } from "../components/ui/ErrorState";
import { EmptyState } from "../components/ui/EmptyState";
import { Spinner } from "../components/ui/Spinner";
import { RunStatusBadge } from "../components/runs/RunStatusBadge";
import { Badge } from "../components/ui/Badge";
import { LeadsTable } from "../components/runs/LeadsTable";
import { ContactsList } from "../components/runs/ContactsList";
import { AnalysisTable } from "../components/runs/AnalysisTable";
import "../components/runs/runs.css";

const READINESS_META = [
  {
    key: "evidenced_contact" as const,
    label: "Evidenced contact",
    hint: "named leader with an evidence-backed email",
  },
  {
    key: "named_contact_no_email" as const,
    label: "Named leader, no email",
    hint: "name recorded, no email publicly attributed",
  },
  {
    key: "public_email_available" as const,
    label: "Public email available",
    hint: "public company email persisted",
  },
  {
    key: "company_contact_available" as const,
    label: "Company contact channel",
    hint: "use the company contact page or channel",
  },
  {
    key: "no_contact_found" as const,
    label: "No public contact",
    hint: "no public contact evidence persisted",
  },
  {
    key: "not_enriched" as const,
    label: "Not enriched",
    hint: "legacy leads persisted before readiness tracking",
  },
];

export function RunResultsPage() {
  const { runId } = useParams<{ runId: string }>();
  const { results, state, error, reload } = useRunResults(runId ?? "");

  if (state === "loading") {
    return <LoadingState label="Loading results" />;
  }

  if (state === "error") {
    if (error?.status === 404) {
      return (
        <EmptyState
          mark="?"
          title="Run not found"
          body="No run exists with this id, so there is nothing to inspect. Double-check the run link or return to the workspace."
          action={
            <Link to="/runs" className="btn btn-primary btn-md">
              Back to runs
            </Link>
          }
          titleTag="h1"
        />
      );
    }
    return (
      <ErrorState
        title="Could not load results"
        detail={error?.message}
        onRetry={() => void reload()}
      />
    );
  }

  if (results === null) {
    return <EmptyState mark="?" title="Results unavailable" />;
  }

  const { run, funnel, contact_breakdown, candidate_summary, candidates, leads, contacts } =
    results; 

  const analysesById: Record<string, (typeof candidates)[number]> = Object.fromEntries(
    candidates.map((item) => [item.candidate_id, item])
  );
  const nearQualified = candidates.filter(
    (item) => item.classification === "near_qualified"
  );
  const otherAnalyzed = candidates.filter(
    (item) =>
      item.classification === "not_qualified" ||
      item.classification === "not_evaluated"
  );
  const otherCount = candidate_summary.not_qualified + candidate_summary.not_evaluated;

  if (run.status === "pending" || run.status === "running") {
    return (
      <div>
        <SectionHeader
          eyebrow="Pipeline"
          title="Waiting for the pipeline"
          description="The run is still executing on the backend. Results appear here as soon as it completes."
        />
        <Card className="phase-note" raised>
          <div className="pipeline-running">
            <div className="pipeline-running-head">
              <Spinner />
              <p className="pipeline-running-title">Pipeline in progress</p>
            </div>
            <p className="field-hint">
              Polling{" "}
              <span className="mono">GET /api/runs/{runId}/results</span> until
              the run reaches a terminal state.
            </p>
            <div className="run-detail-head">
              <RunStatusBadge status={run.status} />
            </div>
          </div>
        </Card>
      </div>
    );
  }

  if (run.status === "failed") {
    return (
      <div>
        <SectionHeader
          eyebrow="Pipeline"
          title="Run failed"
          description="The backend persisted this run as failed during execution."
        />
        <ErrorState
          title="Pipeline failed"
          detail={run.error_message ?? "The run failed without a persisted message."}
        />
        <div className="run-detail-meta-grid" style={{ marginTop: 0 }}>
          <Metric
            label="Qualified leads"
            value={`${run.qualified_lead_count} / ${run.target_lead_count}`}
          />
          <Metric label="Started" value={formatDateTime(run.started_at)} />
        </div>
      </div>
    );
  }

  const publicEmails =
    contact_breakdown.public_email_available + contact_breakdown.evidenced_contact;

  // Terminal success
  return (
    <div>
      <SectionHeader
        eyebrow="Pipeline"
        title="Run results"
        description="Persisted pipeline output. Companies are company-qualified when funding/revenue, tech platform, and US presence all pass — contact data never affects qualification."
        action={
          <Link to={`/runs/${run.run_id}`} className="btn btn-secondary btn-sm">
            Run summary
          </Link>
        }
      />

      <div className="run-detail-head" style={{ marginBottom: 16 }}>
        <RunStatusBadge status={run.status} />
        <span className="mono run-detail-id">{run.run_id}</span>
      </div>

      <div className="results-summary">
        <p className="results-summary-line">
          TVBFundRadar researched{" "}
          <strong>{funnel.sources_researched}</strong>{" "}
          source{funnel.sources_researched === 1 ? "" : "s"} from{" "}
          {funnel.sources_discovered} discovered{" "}
          {funnel.sources_discovered === 1 ? "URL" : "URLs"} and evaluated{" "}
          <strong>{funnel.candidates_evaluated}</strong>{" "}
          compan{funnel.candidates_evaluated === 1 ? "y" : "ies"}.
        </p>
        <div className="results-summary-buckets">
          <Badge tone="success">
            {funnel.company_qualified} company-qualified
          </Badge>
          <Badge tone="warning">
            {candidate_summary.near_qualified} near-qualified
          </Badge>
          <Badge tone="neutral">{otherCount} other analyzed</Badge>
        </div>
      </div>

      <div className="metrics-strip">
        <Metric
          label="Sources discovered"
          value={funnel.sources_discovered}
          hint="URLs discovered across the run's queries"
        />
        <Metric
          label="Sources researched"
          value={funnel.sources_researched}
          hint="sources with a successful fetch"
        />
        <Metric
          label="Candidates extracted"
          value={funnel.candidates_extracted}
          hint="companies extracted from researched pages"
        />
        <Metric
          label="Company qualified"
          value={funnel.company_qualified}
          hint="all three company criteria passed"
        />
        <Metric
          label="Near qualified"
          value={candidate_summary.near_qualified}
          hint="passed exactly two of three criteria"
        />
        <Metric
          label="Public contact available"
          value={publicEmails}
          hint="public or evidence-backed leader email"
        />
        <Metric
          label="Target"
          value={`${run.target_lead_count}`}
          hint="target lead count set at creation"
        />
        <Metric label="Completed" value={formatDateTime(run.completed_at)} />
      </div>

      <h2 className="results-section-title">Qualification funnel</h2>
      <div className="funnel-cards">
        <div className="funnel-card">
          <p className="funnel-card-count">{funnel.sources_discovered}</p>
          <p className="funnel-card-label">Sources discovered</p>
          <p className="funnel-card-hint">URLs discovered across the run&apos;s queries</p>
        </div>
        <div className="funnel-card">
          <p className="funnel-card-count">{funnel.sources_researched}</p>
          <p className="funnel-card-label">Sources researched</p>
          <p className="funnel-card-hint">sources with a successful fetch</p>
        </div>
        <div className="funnel-card">
          <p className="funnel-card-count">{funnel.candidates_extracted}</p>
          <p className="funnel-card-label">Candidates extracted</p>
          <p className="funnel-card-hint">companies discovered in the run</p>
        </div>
        <div className="funnel-card">
          <p className="funnel-card-count">{funnel.candidates_evaluated}</p>
          <p className="funnel-card-label">Candidates evaluated</p>
          <p className="funnel-card-hint">a persisted qualification decision</p>
        </div>
        <div className="funnel-card">
          <p className="funnel-card-count">{funnel.financial_pass}</p>
          <p className="funnel-card-label">Financial criteria met</p>
          <p className="funnel-card-hint">$1M&ndash;$5M funding / revenue evidence</p>
        </div>
        <div className="funnel-card">
          <p className="funnel-card-count">{funnel.tech_pass}</p>
          <p className="funnel-card-label">Tech platform criteria met</p>
          <p className="funnel-card-hint">software / SaaS / platform evidence</p>
        </div>
        <div className="funnel-card">
          <p className="funnel-card-count">{funnel.geography_pass}</p>
          <p className="funnel-card-label">US presence criteria met</p>
          <p className="funnel-card-hint">minimal or no US presence evidence</p>
        </div>
        <div className="funnel-card funnel-card-final">
          <p className="funnel-card-count">{funnel.company_qualified}</p>
          <p className="funnel-card-label">Company qualified</p>
          <p className="funnel-card-hint">all three company criteria passed</p>
        </div>
      </div>
      <Card className="phase-note" raised>
        <p className="phase-note-label">Reading this funnel</p>
        <p className="phase-note-body">
          Criterion pass counts are per-criterion counts over the run&apos;s
          evaluated candidates and can overlap: a company can pass financial and
          tech criteria independently. &ldquo;Company qualified&rdquo; is the only
          number that requires all three to pass together. Contact readiness is
          reported separately and never changes qualification.
        </p>
      </Card>

      <h2 className="results-section-title">Qualification overview</h2>
      <div className="qualification-overview-grid">
        <div className="funnel-card">
          <p className="funnel-card-count">{funnel.financial_pass}</p>
          <p className="funnel-card-label">Financial criteria met</p>
          <p className="funnel-card-hint">$1M&ndash;$5M funding / revenue evidence</p>
        </div>
        <div className="funnel-card">
          <p className="funnel-card-count">{funnel.tech_pass}</p>
          <p className="funnel-card-label">Tech platform criteria met</p>
          <p className="funnel-card-hint">software / SaaS / platform evidence</p>
        </div>
        <div className="funnel-card">
          <p className="funnel-card-count">{funnel.geography_pass}</p>
          <p className="funnel-card-label">US presence criteria met</p>
          <p className="funnel-card-hint">minimal or no US presence evidence</p>
        </div>
        <div className="funnel-card funnel-card-final">
          <p className="funnel-card-count">{candidate_summary.company_qualified}</p>
          <p className="funnel-card-label">Company qualified</p>
          <p className="funnel-card-hint">all three company criteria passed</p>
        </div>
        <div className="funnel-card funnel-card-near">
          <p className="funnel-card-count">{candidate_summary.near_qualified}</p>
          <p className="funnel-card-label">Near qualified</p>
          <p className="funnel-card-hint">passed exactly two of three criteria</p>
        </div>
        <div className="funnel-card">
          <p className="funnel-card-count">{otherCount}</p>
          <p className="funnel-card-label">Other analyzed</p>
          <p className="funnel-card-hint">not qualified or never evaluated</p>
        </div>
      </div>
      <Card className="phase-note" raised>
        <p className="phase-note-label">How these buckets relate</p>
        <p className="phase-note-body">
          Counts are evaluated independently and may overlap across criteria.
          Every candidate in the run falls into exactly one bucket: company
          qualified, near qualified (exactly two criteria passed), or other
          analyzed (fewer than two passed, or never evaluated). Near-qualified
          companies are <strong>not</strong> counted as qualified leads, and
          contact readiness never changes any bucket.
        </p>
      </Card>

      <h2 className="results-section-title">Company-qualified leads</h2>
      <LeadsTable leads={leads} analyses={analysesById} />

      <h2 className="results-section-title">Near-qualified companies</h2>
      <p className="results-section-sub">
        These companies passed 2 of the 3 company qualification criteria. They
        are not counted as qualified leads.
      </p>
      <AnalysisTable
        analyses={nearQualified}
        emptyMark="2"
        emptyTitle="No near-qualified companies"
        emptyBody="No candidate passed exactly two of the three company criteria. Every analyzed company either passed all three or fewer than two."
      />

      <h2 className="results-section-title">Other analyzed companies</h2>
      <details className="results-collapse">
        <summary>
          <span className="results-collapse-heading">
            Show all other analyzed companies
          </span>
          <span className="results-collapse-count">{otherCount}</span>
        </summary>
        <p className="results-section-sub">
          Companies that passed fewer than two company criteria, or were never
          evaluated. Nothing here is counted as a qualified lead.
        </p>
        <AnalysisTable
          analyses={otherAnalyzed}
          emptyMark="0"
          emptyTitle="No other analyzed companies"
          emptyBody="Every candidate in the run was company qualified or near qualified."
        />
      </details>

      {leads.length > 0 ? (
        <>
          <h2 className="results-section-title">Contact readiness</h2>
          <div className="funnel-cards">
            {READINESS_META.map((item) => (
              <div className="funnel-card" key={item.key}>
                <p className="funnel-card-count">
                  {contact_breakdown[item.key]}
                </p>
                <p className="funnel-card-label">{item.label}</p>
                <p className="funnel-card-hint">{item.hint}</p>
              </div>
            ))}
          </div>
        </>
      ) : null}

      <h2 className="results-section-title">Contacts</h2>
      <ContactsList contacts={contacts} />

      <Card className="phase-note" raised>
        <p className="phase-note-label">Phase note</p>
        <p className="phase-note-body">
          Candidates are classified only against persisted company evidence.
          Company-qualified leads passed every company criterion; near-qualified
          companies passed exactly two and are shown above without ever counting
          as leads; the remaining analyzed companies are visible in the list
          above. Anyone missing a persisted decision is reported truthfully as
          &ldquo;not evaluated&rdquo; — never as failed. No lead requires a named
          contact or email, and no qualification result is ever fabricated.
        </p>
      </Card>
    </div>
  );
}