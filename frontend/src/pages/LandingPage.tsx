import { Link } from "react-router-dom";
import { ThemeToggle } from "../components/ui/ThemeToggle";
import { useAuth } from "../context/AuthContext";
import "./landing.css";

const STEPS = [
  {
    index: "01",
    title: "Discover",
    body: "Search and collect relevant public sources across the web.",
  },
  {
    index: "02",
    title: "Research",
    body: "Fetch researched pages and extract company evidence from them.",
  },
  {
    index: "03",
    title: "Qualify",
    body: "Evaluate each company against explicit company criteria.",
  },
  {
    index: "04",
    title: "Review",
    body: "Inspect qualified, near-qualified, and other analyzed companies.",
  },
] as const;

const CAPABILITIES = [
  {
    title: "Evidence-backed qualification",
    body: "Every company is evaluated against the three active criteria — funding/revenue range, tech platform, and US presence — using only persisted evidence collected from public sources.",
  },
  {
    title: "Near-qualified visibility",
    body: "Companies that pass two of three criteria are shown explicitly as near-qualified and are never counted as qualified leads.",
  },
  {
    title: "Contact enrichment without guessing",
    body: "Publicly attributable names and emails are recorded with their evidence state. Missing contact information stays blank — it is never fabricated.",
  },
  {
    title: "Transparent research funnel",
    body: "Trace a run from sources discovered, through candidates extracted and evaluated, to the exact reason each company qualified or did not.",
  },
] as const;

const TRUST_POINTS = [
  "Missing evidence remains insufficient — it is never assumed.",
  "Missing contact information stays blank — it is never invented.",
  "Companies passing two of three criteria stay near-qualified — they are never presented as leads.",
  "Every qualification decision traces to persisted, source-backed evidence.",
] as const;

export function LandingPage() {
  const { user, loading } = useAuth();
  const signedIn = loading || user !== null;

  return (
    <div className="landing">
      <header className="landing-nav">
        <div className="landing-nav-inner">
          <Link to="/" className="landing-brand" aria-label="TVBFundRadar home">
            <span className="brand-mark" aria-hidden="true">
              S
            </span>
            <span className="landing-brand-name">TVBFundRadar</span>
          </Link>

          <nav className="landing-links" aria-label="Landing">
            <a href="#product">Product</a>
            <a href="#how-it-works">How it works</a>
            {signedIn ? (
              <Link to="/runs">Workspace</Link>
            ) : (
              <>
                <Link to="/login">Sign in</Link>
                <Link to="/register">Create account</Link>
              </>
            )}
          </nav>

          <div className="landing-nav-actions">
            <Link to="/runs/new" className="btn btn-primary btn-md">
              Start researching
            </Link>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main>
        <section className="landing-hero">
          <div className="landing-hero-inner">
            <div className="landing-hero-copy">
              <p className="eyebrow">Autonomous company intelligence and qualification</p>
              <h1>Find companies that actually match your criteria.</h1>
              <p className="landing-hero-lede">
                TVBFundRadar researches public web sources, evaluates companies
                against explicit qualification rules, and shows exactly why each
                company qualifies, nearly qualifies, or does not meet the
                criteria.
              </p>
              <div className="landing-hero-actions">
                <Link to="/runs/new" className="btn btn-primary btn-md">
                  Start a research run
                </Link>
                <Link to="/runs" className="btn btn-secondary btn-md">
                  Explore workspace
                </Link>
              </div>
              <p className="landing-hero-note">
                Sources are searched organically — no API keys required.
              </p>
            </div>

            <div className="landing-hero-visual" aria-hidden="true">
              <div className="ledger-card">
                <div className="ledger-head">
                  <p className="eyebrow">Qualification ledger</p>
                  <p className="mono ledger-tag">run · structure</p>
                </div>
                <div className="ledger-body">
                  <dl className="ledger">
                    <div className="ledger-row">
                      <dt>Sources discovered</dt>
                      <dd>recorded</dd>
                    </div>
                    <div className="ledger-row">
                      <dt>Sources researched</dt>
                      <dd>recorded</dd>
                    </div>
                    <div className="ledger-row">
                      <dt>Candidates extracted</dt>
                      <dd>recorded</dd>
                    </div>
                    <div className="ledger-row">
                      <dt>Candidates evaluated</dt>
                      <dd>recorded</dd>
                    </div>
                  </dl>
                  <div className="ledger-divider" />
                  <div className="ledger-criteria">
                    <span className="ledger-chip ledger-chip-pass">Financial PASS</span>
                    <span className="ledger-chip ledger-chip-pass">Tech platform PASS</span>
                    <span className="ledger-chip ledger-chip-pass">US presence PASS</span>
                  </div>
                  <div className="ledger-divider" />
                  <div className="ledger-buckets">
                    <div className="ledger-bucket ledger-bucket-final">Company qualified</div>
                    <div className="ledger-bucket">Near qualified — two of three</div>
                    <div className="ledger-bucket">Other analyzed — fewer than two</div>
                  </div>
                </div>
              </div>
              <p className="ledger-footnote">
                Illustrative structure — open the workspace to read your own
                runs.
              </p>
            </div>
          </div>
        </section>

        <section id="how-it-works" className="landing-section">
          <div className="landing-section-inner">
            <p className="eyebrow">How it works</p>
            <h2>From search query to qualified company.</h2>
            <div className="landing-steps">
              {STEPS.map((step) => (
                <div key={step.index} className="landing-step">
                  <p className="landing-step-index mono">{step.index}</p>
                  <h3>{step.title}</h3>
                  <p>{step.body}</p>
                </div>
              ))}
            </div>
            <p className="landing-section-note">
              Qualification depends on persisted evidence. Where evidence is
              missing, TVBFundRadar says so — it does not guess.
            </p>
          </div>
        </section>

        <section id="product" className="landing-section">
          <div className="landing-section-inner">
            <p className="eyebrow">Product capabilities</p>
            <h2>Built around the research that already exists.</h2>
            <div className="landing-capabilities">
              {CAPABILITIES.map((cap) => (
                <div key={cap.title} className="landing-capability">
                  <p className="landing-capability-title">{cap.title}</p>
                  <p className="landing-capability-body">{cap.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="truth" className="landing-section landing-truth">
          <div className="landing-section-inner">
            <div className="landing-truth-panel">
              <p className="eyebrow">Truthfulness</p>
              <blockquote className="landing-truth-quote">
                TVBFundRadar does not turn missing information into confident guesses.
              </blockquote>
              <ul className="landing-truth-list">
                {TRUST_POINTS.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <section className="landing-final-cta">
          <div className="landing-section-inner">
            <h2>Ready to research companies that match your criteria?</h2>
            <div className="landing-cta-actions">
              <Link to="/runs" className="btn btn-primary btn-md">
                Open workspace
              </Link>
              <Link to="/runs/new" className="btn btn-secondary btn-md">
                Start a research run
              </Link>
            </div>
            <p className="landing-hero-note">
              Runs persist on the backend and open in the results workspace.
            </p>
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-footer-inner">
          <span className="landing-brand-name">TVBFundRadar</span>
          <p>
            Autonomous company intelligence and qualification. Single-user,
            local-first — no accounts, no API keys.
          </p>
        </div>
      </footer>
    </div>
  );
}