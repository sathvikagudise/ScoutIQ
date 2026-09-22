import { Link } from "react-router-dom";
import { ThemeToggle } from "../components/ui/ThemeToggle";
import { Spinner } from "../components/ui/Spinner";
import "../components/layout/app.css";
import "./landing.css";

export function AuthSkeleton() {
  return (
    <div className="standalone">
      <header className="standalone-top">
        <Link to="/" className="landing-brand" aria-label="TVBFundRadar home">
          <span className="brand-mark" aria-hidden="true">
            S
          </span>
          <span className="landing-brand-name">TVBFundRadar</span>
        </Link>
        <ThemeToggle />
      </header>
      <main className="standalone-main">
        <div className="auth-card">
          <div className="auth-loading">
            <Spinner />
            <p className="field-hint">Restoring your session…</p>
          </div>
        </div>
      </main>
    </div>
  );
}