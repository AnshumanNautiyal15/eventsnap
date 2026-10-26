import { createContext, useContext, useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { api } from "./api";
import FullPageSpinner from "./components/FullPageSpinner";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined while loading, null when logged out

  useEffect(() => {
    api("/api/auth/me/")
      .then((data) => setUser(data.user))
      .catch(() => setUser(null));
  }, []);

  return <AuthContext.Provider value={{ user, setUser }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);

export function RequireAuth({ children }) {
  const { user } = useAuth();
  const location = useLocation();
  if (user === undefined) return <FullPageSpinner />;
  if (!user) return <Navigate to={`/login/?next=${encodeURIComponent(location.pathname)}`} replace />;
  return children;
}
