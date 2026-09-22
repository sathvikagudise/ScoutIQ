import { Link } from "react-router-dom";
import { ThemeToggle } from "../components/ui/ThemeToggle";
import { EmptyState } from "../components/ui/EmptyState";
import "../components/layout/app.css";
import "./landing.css";

export function NotFoundPage() {
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
        <EmptyState
          mark="?"
          title="Page not found"
          body="The requested view does not exist. Return to the landing page or open the workspace."
          titleTag="h1"
          action={
            <Link to="/" className="btn btn-primary btn-md">
              Back to home
            </Link>
          }
        />
      </main>
    </div>
  );
}