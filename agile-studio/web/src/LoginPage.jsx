import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { apiPost, setAuth } from "./api.js";

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);

  const raw = location.state?.from;
  const from =
    typeof raw === "string" && raw.length > 0 && !raw.startsWith("/login") && !raw.startsWith("/register") ? raw : "/";

  const onSubmit = async (e) => {
    e.preventDefault();
    setErr(null);
    setLoading(true);
    try {
      const data = await apiPost("/auth/login", { email: email.trim(), password });
      setAuth(data.access_token, data.user);
      navigate(from, { replace: true });
    } catch (e2) {
      setErr(e2.message || "Sign-in failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="as-auth-page min-vh-100 d-flex align-items-center justify-content-center p-3">
      <div className="as-auth-card card shadow border-0" style={{ width: "100%", maxWidth: 420 }}>
        <div className="card-body p-4 p-md-5">
          <div className="text-center mb-4">
            <div className="d-inline-flex align-items-center justify-content-center rounded-3 bg-primary text-white mb-3" style={{ width: 48, height: 48 }}>
              <i className="bi bi-kanban fs-4" aria-hidden />
            </div>
            <h1 className="h4 fw-semibold mb-1">Sign in to Agile Studio</h1>
            <p className="small text-secondary mb-0">Use the email and password you registered with.</p>
          </div>
          {err && (
            <div className="alert alert-danger py-2 small" role="alert">
              {err}
            </div>
          )}
          <form onSubmit={onSubmit} className="vstack gap-3">
            <div>
              <label className="form-label small fw-semibold" htmlFor="as-login-email">
                Email
              </label>
              <input
                id="as-login-email"
                type="email"
                className="form-control"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="form-label small fw-semibold" htmlFor="as-login-password">
                Password
              </label>
              <input
                id="as-login-password"
                type="password"
                className="form-control"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <button type="submit" className="btn btn-primary w-100" disabled={loading}>
              {loading ? "Signing in…" : "Sign in"}
            </button>
          </form>
          <p className="small text-secondary text-center mt-4 mb-0">
            No account yet?{" "}
            <Link to="/register" className="fw-semibold">
              Create an account
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
