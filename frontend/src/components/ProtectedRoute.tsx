import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { AuthSkeleton } from "../pages/AuthSkeleton";

/**
 * Guards every workspace shell route. While the session is still resolving we
 * render a neutral skeleton; once resolved, unauthenticated visitors are sent
 * to the sign-in page with their intended destination remembered.
 */
export function ProtectedRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return <AuthSkeleton />;
  }

  if (user === null) {
    const from = `${location.pathname}${location.search}`;
    return <Navigate to="/login" replace state={{ from }} />;
  }

  return <Outlet />;
}