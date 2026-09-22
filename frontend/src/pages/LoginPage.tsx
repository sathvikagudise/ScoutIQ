import { useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { ThemeToggle } from "../components/ui/ThemeToggle";
import { Spinner } from "../components/ui/Spinner";
import "../components/layout/app.css";
import "./landing.css";
import "./auth.css";

export function LoginPage() {
  const { user, loading, login } = useAuth();
  const location = useLocation();
  const from: string = (location.state as { from?: string } | null)?.from ?? "/runs";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (loading) {
    return (
      <div className="standalone">
        <header className="standalone-top">
          <Link to="/" className="landing-brand" aria-label="TVBFundRadar home">
            <span className="brand-mark" aria-hidden="true">S</span>
            <span className="landing-brand-name">TVBFundRadar</span>
          </Link>
          <ThemeToggle />
        </header>
        <main className="standalone-main">
          <div className="auth-card">
            <div className="auth-loading"><Spinner /><p className="field-hint">Restoring your session…</p></div>
          </div>
        </main>
      </div>
    );
  }

  if (user !== null) {
    return <Navigate to={from} replace />;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("The email or password is incorrect.");
      } else {
        setError("Could not sign in. Is the backend running?");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="standalone">
      <header className="standalone-top">
        <Link to="/" className="landing-brand" aria-label="TVBFundRadar home">
          <span className="brand-mark" aria-hidden="true">S</span>
          <span className="landing-brand-name">TVBFundRadar</span>
        </Link>
        <ThemeToggle />
      </header>
      <main className="standalone-main">
        <div className="auth-card">
          <h1 className="state-title">Sign in to TVBFundRadar</h1>
          <p className="field-hint" style={{ marginBottom: 24 }}>
            Enter your email and password to access your workspace.
          </p>

          <form onSubmit={(e) => void handleSubmit(e)}>
            {error !== null ? (
              <p className="auth-error" role="alert">{error}</p>
            ) : null}

            <div className="field">
              <label className="field-label" htmlFor="email">Email</label>
              <input
                id="email"
                className="input"
                type="email"
                required
                autoComplete="username"
                value={email}
                disabled={busy}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="password">Password</label>
              <input
                id="password"
                className="input"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                disabled={busy}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            <div className="form-actions">
              <button className="btn btn-primary btn-md" type="submit" disabled={busy}>
                {busy ? <><Spinner /> Signing in…</> : "Sign in"}
              </button>
            </div>
          </form>

          <p className="auth-alt-action">
            Don't have an account?{" "}
            <Link to="/register">Create one</Link>
          </p>
        </div>
      </main>
    </div>
  );
}