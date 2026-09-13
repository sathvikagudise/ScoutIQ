import { SectionHeader } from "../components/ui/SectionHeader";
import { Card } from "../components/ui/Card";
import { Badge, type Tone } from "../components/ui/Badge";
import "../components/runs/runs.css";

interface ProviderRow {
  name: string;
  detail: string;
  state: string;
  tone: Tone;
}

const SEARCH_PROVIDERS: ProviderRow[] = [
  {
    name: "Built-in search discovery",
    detail:
      "Zero-key DuckDuckGo adapter. Used by every run — no API key, account, or configuration required.",
    state: "In use",
    tone: "success",
  },
  {
    name: "External search API",
    detail:
      "No external search provider has been configured. When adapters are added, credentials live server-side only.",
    state: "Not configured",
    tone: "neutral",
  },
  {
    name: "Company data API",
    detail:
      "Not configured. Company evidence is gathered from public web sources in the current build.",
    state: "Not configured",
    tone: "neutral",
  },
];

const ENRICHMENT_PROVIDERS: ProviderRow[] = [
  {
    name: "Contact enrichment",
    detail:
      "Available enrichment today is evidence-based assembly from researched pages. Third-party enrichment providers are optional and none are connected.",
    state: "Not configured",
    tone: "neutral",
  },
  {
    name: "Email verification",
    detail:
      "Not implemented by design. ScoutIQ never guesses, verifies, or attributes emails to people.",
    state: "Unavailable",
    tone: "neutral",
  },
];

function ProviderTable({ rows }: { rows: ProviderRow[] }) {
  return (
    <div className="results-table-wrap" tabIndex={0} aria-label="Provider configuration table">
      <table className="results-table integration-table">
        <thead>
          <tr>
            <th>Provider</th>
            <th>Description</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.name}>
              <td data-label="Provider">
                <span className="results-company">{row.name}</span>
              </td>
              <td data-label="Description">
                <span className="integration-detail">{row.detail}</span>
              </td>
              <td data-label="Status">
                <Badge tone={row.tone}>{row.state}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function IntegrationsPage() {
  return (
    <div>
      <SectionHeader
        eyebrow="Workspace"
        title="Integrations"
        description="Connect approved research and enrichment providers. Nothing is connected unless the backend has a configured adapter — no fake statuses, no silent third-party calls."
      />

      <Card className="phase-note" raised>
        <p className="phase-note-label">Current state</p>
        <p className="phase-note-body">
          ScoutIQ runs entirely on its built-in, zero-key search adapter and
          public web research. This build stores no provider credentials, sends
          no secrets anywhere, and never calls a third-party data service. The
          structure below describes the provider architecture so future adapters
          have a clear, safe home.
        </p>
      </Card>

      <h2 className="results-section-title">Search providers</h2>
      <ProviderTable rows={SEARCH_PROVIDERS} />

      <h2 className="results-section-title">Enrichment providers</h2>
      <ProviderTable rows={ENRICHMENT_PROVIDERS} />

      <h2 className="results-section-title">Credential architecture</h2>
      <Card className="phase-note" raised>
        <p className="phase-note-label">Security model</p>
        <p className="phase-note-body">
          When external provider adapters are integrated, their credentials
          will be stored server-side only — never in browser storage (no keys in
          <span className="mono"> localStorage</span>), never returned in full
          after saving, and never written to logs. A provider is shown as
          configured or not configured strictly from what the backend can
          truthfully determine.
        </p>
      </Card>
    </div>
  );
}