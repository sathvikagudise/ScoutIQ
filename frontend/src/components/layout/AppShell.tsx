import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { ThemeToggle } from "../ui/ThemeToggle";
import { useAuth } from "../../context/AuthContext";
import { API_BASE_URL } from "../../api/client";
import { cn } from "../../utils/cn";
import "./app.css";

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) => cn("nav-item", isActive && "nav-item-active")}
    >
      <span className="nav-marker" aria-hidden="true" />
      {label}
    </NavLink>
  );
}

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleSignOut() {
    await logout();
    navigate("/", { replace: true });
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <Link to="/" className="brand" aria-label="TVBFundRadar — back to home">
          <div className="brand-mark" aria-hidden="true">
            S
          </div>
          <div>
            <div className="brand-name">TVBFundRadar</div>
            <div className="brand-tagline">Autonomous company intelligence</div>
          </div>
        </Link>

        <nav className="nav-section" aria-label="Primary">
          <p className="nav-label">Workspace</p>
          <NavItem to="/runs" label="Runs" />
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-user">
            <span className="sidebar-user-avatar" aria-hidden="true">
              {(user?.display_name?.trim().charAt(0) ?? user?.email.charAt(0) ?? "?").toUpperCase()}
            </span>
            <div className="sidebar-user-meta">
              <span className="sidebar-user-name">
                {user?.display_name?.trim() || user?.email}
              </span>
              <span className="sidebar-user-email">{user?.email}</span>
            </div>
            <button
              type="button"
              className="sidebar-signout"
              title="Sign out"
              aria-label="Sign out"
              onClick={() => void handleSignOut()}
            >
              Sign out
            </button>
          </div>
          <div className="sidebar-status-row">
            {API_BASE_URL ? (
              <span
                className="sidebar-status"
                title={`Backend API: ${API_BASE_URL}`}
              >
                API &rarr; {new URL(API_BASE_URL).host}
              </span>
            ) : (
              <span
                className="sidebar-status"
                title="Development traffic to the API routes through the Vite dev proxy (see vite.config.ts)."
              >
                Dev proxy &rarr; local API
              </span>
            )}
            <ThemeToggle />
          </div>
        </div>
      </aside>

      <main className="main">
        <div className="main-inner">
          <Outlet />
        </div>
        <footer className="main-footer">
          TVBFundRadar — autonomous company intelligence &amp; lead discovery.
        </footer>
      </main>
    </div>
  );
}