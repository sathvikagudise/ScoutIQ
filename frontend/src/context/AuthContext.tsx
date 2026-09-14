import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { getMe, loginUser, logoutUser, registerUser } from "../api/auth";
import { setSessionToken, getSessionToken } from "../api/tokenStore";
import type { User } from "../api/types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (payload: {
    email: string;
    password: string;
    display_name?: string | null;
  }) => Promise<User>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const token = getSessionToken();
    if (token === null) {
      setLoading(false);
      return;
    }

    getMe()
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch(() => {
        // Token missing, revoked, or expired: clear it so the next visit
        // starts cleanly at the sign-in page.
        if (!cancelled) {
          setSessionToken(null);
          setUser(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const auth = await loginUser({ email, password });
    setSessionToken(auth.token);
    setUser(auth.user);
    return auth.user;
  }, []);

  const register = useCallback(
    async (payload: {
      email: string;
      password: string;
      display_name?: string | null;
    }) => {
      const auth = await registerUser(payload);
      setSessionToken(auth.token);
      setUser(auth.user);
      return auth.user;
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await logoutUser();
    } finally {
      setSessionToken(null);
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}