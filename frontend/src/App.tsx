import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { HashRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import type { User } from "./types";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import TelegramConfig from "./pages/TelegramConfig";
import Sources from "./pages/Sources";
import Rules from "./pages/Rules";
import Alerts from "./pages/Alerts";
import Search from "./pages/Search";
import Settings from "./pages/Settings";
import AuditLog from "./pages/AuditLog";

interface AuthCtx {
  user: User | null;
  loading: boolean;
  setUser: (u: User | null) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthCtx>({
  user: null,
  loading: true,
  setUser: () => {},
  logout: async () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

function NavItem({ to, label, show }: { to: string; label: string; show: boolean }) {
  if (!show) return null;
  return (
    <NavLink to={to} className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}>
      {label}
    </NavLink>
  );
}

function Layout() {
  const { user, logout } = useAuth();
  const isOperator = user?.role === "operator" || user?.role === "admin";
  const isAdmin = user?.role === "admin";
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">Telemonitor</div>
        <nav>
          <NavItem to="/" label="Overview" show />
          <NavItem to="/telegram" label="Telegram" show={isOperator} />
          <NavItem to="/sources" label="Sources" show={isOperator} />
          <NavItem to="/rules" label="Rules" show={isOperator} />
          <NavItem to="/alerts" label="Alerts" show />
          <NavItem to="/search" label="Search" show />
          <NavItem to="/settings" label="Settings" show={isAdmin} />
          <NavItem to="/audit" label="Audit Log" show={isOperator} />
        </nav>
        <div className="sidebar-footer">
          <div className="user-chip">
            <span className="user-name">{user?.username}</span>
            <span className="user-role">{user?.role}</span>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/telegram" element={<TelegramConfig />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/rules" element={<Rules />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/search" element={<Search />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/audit" element={<AuditLog />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function Shell() {
  const { user, loading } = useAuth();
  if (loading) {
    return <div className="center-screen">Loading…</div>;
  }
  if (!user) {
    return <Login />;
  }
  return <Layout />;
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .me()
      .then((r) => setUser(r.user))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      /* ignore */
    }
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, setUser, logout }}>
      <HashRouter>
        <Shell />
      </HashRouter>
    </AuthContext.Provider>
  );
}
