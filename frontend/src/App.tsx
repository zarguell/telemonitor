import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { HashRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { api, UNAUTHORIZED_EVENT } from "./api";
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

function RequireRole({ roles, children }: { roles: string[]; children: React.ReactElement }) {
  const { user } = useAuth();
  if (!user || !roles.includes(user.role)) {
    return <Navigate to="/" replace />;
  }
  return children;
}

function NavItem({ to, label, show }: { to: string; label: string; show: boolean }) {
  if (!show) return null;
  return (
    <NavLink to={to} className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}>
      {label}
    </NavLink>
  );
}

function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    setOk(null);
    try {
      await api.changePassword(current, next);
      setOk("Password changed — you will be signed out.");
      setTimeout(() => {
        void api.logout().catch(() => {});
        window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
      }, 1200);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ width: 420 }} onClick={(e) => e.stopPropagation()}>
        <h2>Change password</h2>
        {error && <div className="error-box">{error}</div>}
        {ok && <div className="ok-box">{ok}</div>}
        <label>Current password</label>
        <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        <label>New password (8+ characters)</label>
        <input type="password" value={next} onChange={(e) => setNext(e.target.value)} />
        <div className="btn-row" style={{ marginTop: 14 }}>
          <button className="btn" onClick={() => void submit()} disabled={!current || next.length < 8}>
            Change password
          </button>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function Layout() {
  const { user, logout } = useAuth();
  const [showPw, setShowPw] = useState(false);
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
          <button className="btn btn-ghost btn-sm" onClick={() => setShowPw(true)}>
            Change password
          </button>
          <button className="btn btn-ghost btn-sm" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route
            path="/telegram"
            element={
              <RequireRole roles={["operator", "admin"]}>
                <TelegramConfig />
              </RequireRole>
            }
          />
          <Route
            path="/sources"
            element={
              <RequireRole roles={["operator", "admin"]}>
                <Sources />
              </RequireRole>
            }
          />
          <Route
            path="/rules"
            element={
              <RequireRole roles={["operator", "admin"]}>
                <Rules />
              </RequireRole>
            }
          />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/search" element={<Search />} />
          <Route
            path="/settings"
            element={
              <RequireRole roles={["admin"]}>
                <Settings />
              </RequireRole>
            }
          />
          <Route
            path="/audit"
            element={
              <RequireRole roles={["operator", "admin"]}>
                <AuditLog />
              </RequireRole>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      {showPw && <ChangePasswordModal onClose={() => setShowPw(false)} />}
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

  // Any 401 from an API call (session expiry, revocation) returns to Login.
  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
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
