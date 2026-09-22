import { useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { ThemeToggle } from "../components/ui/ThemeToggle";
import { Spinner } from "../components/ui/Spinner";
import "../components/layout/app.css";
import "./landing.css";
import "./auth.css";

export function RegisterPage() {
  const { user, loading, register } = useAuth();
  const location = useLocation();
  const from: string = (location.state as { from?: string } | null)?.from ?? "/runs";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
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

    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setBusy(true);
    try {
      await register({
        email: email.trim(),
        password,
        display_name: displayName.trim() || null,
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("An account with this email already exists. Sign in instead.");
      } else {
        setError("Could not create the account. Check your details and try again.");
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
          <h1 className="state-title">Create your TVBFundRadar account</h1>
          <p className="field-hint" style={{ marginBottom: 24 }}>
            Your runs live in a private workspace only you can see.
          </p>

          <form onSubmit={(e) => void handleSubmit(e)}>
            {error !== null ? (
              <p className="auth-error" role="alert">{error}</p>
            ) : null}

            <div className="field">
              <label className="field-label" htmlFor="display-name">
                Display name <span className="field-optional">optional</span>
              </label>
              <input
                id="display-name"
                className="input"
                type="text"
                autoComplete="name"
                value={displayName}
                disabled={busy}
                onChange={(e) => setDisplayName(e.target.value)}
              />
            </div>

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
                autoComplete="new-password"
                value={password}
                disabled={busy}
                onChange={(e) => setPassword(e.target.value)}
              />
              <p className="field-hint">At least 8 characters. Never sent in plain text — stored as a bcrypt hash.</p>
            </div>

            <div className="form-actions">
              <button className="btn btn-primary btn-md" type="submit" disabled={busy}>
                {busy ? <><Spinner /> Creating account…</> : "Create account"}
              </button>
            </div>
          </form>

          <p className="auth-alt-action">
            Already have an account? <Link to="/login">Sign in</Link>
          </p>
        </div>
      </main>
    </div>
  );
}