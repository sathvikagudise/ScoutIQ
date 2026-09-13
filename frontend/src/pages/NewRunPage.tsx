import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createRun, executeRun } from "../api/runs";
import { ApiError } from "../api/client";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { SectionHeader } from "../components/ui/SectionHeader";
import { ErrorState } from "../components/ui/ErrorState";
import { Spinner } from "../components/ui/Spinner";
import "../components/runs/runs.css";

type ComposerPhase = "idle" | "creating" | "executing";

const PIPELINE_STEPS = [
  "Discovery",
  "Research",
  "Extraction",
  "Company qualification",
  "Contact enrichment",
  "Leads",
  "Completion",
] as const;

export function NewRunPage() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<ComposerPhase>("idle");
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [targetLeadCount, setTargetLeadCount] = useState(8);
  const [maxResults, setMaxResults] = useState(2);
  const [queriesText, setQueriesText] = useState("");
  const [validation, setValidation] = useState<string | null>(null);

  const parsing = queriesText.split("\n").map((line) => line.trim());
  const queryCount = parsing.filter((q) => q.length > 0).length;

  const busy = phase === "creating" || phase === "executing";

  async function handleSubmit() {
    const queries = Array.from(
      new Set(parsing.filter((q) => q.length > 0)),
    );
    if (queries.length === 0) {
      setValidation("Enter at least one search query.");
      return;
    }
    setValidation(null);
    setError(null);

    let created: Awaited<ReturnType<typeof createRun>>;
    try {
      setPhase("creating");
      created = await createRun(targetLeadCount);
    } catch (err) {
      setPhase("idle");
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not create the run. Is the backend running?",
      );
      return;
    }

    setRunId(created.run_id);

    try {
      setPhase("executing");
      await executeRun(created.run_id, queries, maxResults);
      navigate(`/runs/${created.run_id}/results`, { replace: true });
    } catch {
      // The pipeline is synchronous and re-raises on failure, so a non-2xx
      // response usually means the run was persisted as FAILED. Navigate to
      // the results view and let it reconcile the real persisted state.
      navigate(`/runs/${created.run_id}/results`, { replace: true });
    }
  }

  return (
    <div>
      <SectionHeader
        eyebrow="Pipeline"
        title="Start a run"
        description="Create a discovery run and execute the full ScoutIQ pipeline against real web sources. Runs persist on the backend and open in the results workspace."
      />

      {error !== null ? (
        <div style={{ marginBottom: 24 }}>
          <ErrorState title="The run could not be started" detail={error} />
        </div>
      ) : null}

      <div className="composer-grid">
        <Card className="phase-note" raised>
          <div
            className="form-inline-grid"
            style={{ marginBottom: 20 }}
          >
            <div className="field">
              <label className="field-label" htmlFor="target-count">
                Target lead count
              </label>
              <input
                id="target-count"
                className="input"
                type="number"
                min={0}
                value={targetLeadCount}
                disabled={busy}
                onChange={(e) => setTargetLeadCount(Number(e.target.value))}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="max-results">
                Max results per query
              </label>
              <input
                id="max-results"
                className="input"
                type="number"
                min={1}
                max={10}
                value={maxResults}
                disabled={busy}
                onChange={(e) => setMaxResults(Number(e.target.value))}
              />
            </div>
          </div>
          <p className="field-hint" style={{ marginBottom: 20, marginTop: -12 }}>
            Max results per query: 1–10, matching the backend cap. Extra
            sources mean a longer-running pipeline.
          </p>

          <div className="field">
            <label className="field-label" htmlFor="queries">
              Search queries — one per line
            </label>
            <textarea
              id="queries"
              className="textarea"
              placeholder={"SaaS sales intelligence platform\nB2B data pipeline startups"}
              value={queriesText}
              disabled={busy}
              onChange={(e) => setQueriesText(e.target.value)}
            />
            <p className="field-hint">
              {parsing.length > 0
                ? `${queryCount} valid quer${queryCount === 1 ? "y" : "ies"}${
                    queryCount === 0 ? " — enter at least one" : ""
                  }, duplicates ignored.`
                : "Paste one search query per line."}
            </p>
            {validation !== null ? (
              <p className="field-error">{validation}</p>
            ) : null}
          </div>

          <div className="form-actions">
            <Button disabled={busy} onClick={() => void handleSubmit()}>
              {busy ? <Spinner /> : null}
              {phase === "creating"
                ? "Creating run…"
                : phase === "executing"
                  ? "Executing pipeline…"
                  : "Create & run pipeline"}
            </Button>
            {busy ? (
              <span className="field-hint">
                Request stays open until the pipeline finishes — this can take a
                minute or two on real sources.
              </span>
            ) : null}
          </div>
        </Card>

        <div className="composer-rail">
          <Card className="results-contacts">
            <p className="eyebrow" style={{ marginBottom: 10 }}>
              Qualification profile
            </p>
            <dl className="profile-list">
              <div className="profile-row">
                <dt>Financial</dt>
                <dd>$1M–$5M funding or revenue</dd>
              </div>
              <div className="profile-row">
                <dt>Business type</dt>
                <dd>Tech-related platform</dd>
              </div>
              <div className="profile-row">
                <dt>Geography</dt>
                <dd>Minimal / no US presence</dd>
              </div>
              <div className="profile-row">
                <dt>Contact information</dt>
                <dd>Optional enrichment</dd>
              </div>
            </dl>
            <p className="profile-note">
              Company qualification is determined by the three company criteria.
              Contact information is enriched separately and does not downgrade
              a qualified company.
            </p>
          </Card>

          <Card className="results-contacts">
            <p className="eyebrow" style={{ marginBottom: 10 }}>
              Pipeline stages
            </p>
            <div className="composer-steps">
              {PIPELINE_STEPS.map((step, index) => (
                <div key={step} className="composer-step">
                  <span className="composer-step-index">{index + 1}</span>
                  <span className="composer-step-name">{step}</span>
                </div>
              ))}
            </div>
            <p className="composer-rail-note">
              Explanatory sequence, not live progress — the backend reports only
              the final status (completed or failed).
            </p>
          </Card>
        </div>
      </div>

      {phase === "executing" && runId !== null ? (
        <Card className="phase-note" raised>
          <div className="pipeline-running">
            <div className="pipeline-running-head">
              <Spinner />
              <p className="pipeline-running-title">Pipeline is running</p>
            </div>
            <p className="field-hint">
              Real discovery queries are hitting the network, researched pages
              are being fetched and extracted, and candidates are qualified with
              persisted evidence. The backend advances the run to{" "}
              <span className="mono">completed</span> or{" "}
              <span className="mono">failed</span> when it finishes.
            </p>
            <p className="mono" style={{ color: "var(--text-faint)" }}>
              run {runId}
            </p>
          </div>
        </Card>
      ) : null}
    </div>
  );
}