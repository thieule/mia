import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiPost, setAuth } from "./api.js";

export default function RegisterPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e) => {
    e.preventDefault();
    setErr(null);
    if (password.length < 8) {
      setErr("Password must be at least 8 characters.");
      return;
    }
    setLoading(true);
    try {
      const data = await apiPost("/auth/register", {
        email: email.trim(),
        password,
        display_name: displayName.trim(),
      });
      setAuth(data.access_token, data.user);
      navigate("/", { replace: true });
    } catch (e2) {
      setErr(e2.message || "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="as-auth-page min-vh-100 d-flex align-items-center justify-content-center p-3">
      <div className="as-auth-card card shadow border-0" style={{ width: "100%", maxWidth: 440 }}>
        <div className="card-body p-4 p-md-5">
          <div className="text-center mb-4">
            <div className="d-inline-flex align-items-center justify-content-center rounded-3 bg-primary text-white mb-3" style={{ width: 48, height: 48 }}>
              <i className="bi bi-person-plus fs-4" aria-hidden />
            </div>
            <h1 className="h4 fw-semibold mb-1">Create an account</h1>
            <p className="small text-secondary mb-0">Creates your login and a human member in the workspace.</p>
          </div>
          {err && (
            <div className="alert alert-danger py-2 small" role="alert">
              {err}
            </div>
          )}
          <form onSubmit={onSubmit} className="vstack gap-3">
            <div>
              <label className="form-label small fw-semibold" htmlFor="as-reg-name">
                Display name
              </label>
              <input
                id="as-reg-name"
                type="text"
                className="form-control"
                autoComplete="name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
                minLength={1}
                maxLength={255}
              />
            </div>
            <div>
              <label className="form-label small fw-semibold" htmlFor="as-reg-email">
                Email
              </label>
              <input
                id="as-reg-email"
                type="email"
                className="form-control"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="form-label small fw-semibold" htmlFor="as-reg-password">
                Password
              </label>
              <input
                id="as-reg-password"
                type="password"
                className="form-control"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                maxLength={128}
              />
              <div className="form-text">At least 8 characters.</div>
            </div>
            <button type="submit" className="btn btn-primary w-100" disabled={loading}>
              {loading ? "Creating account…" : "Register"}
            </button>
          </form>
          <p className="small text-secondary text-center mt-4 mb-0">
            Already have an account?{" "}
            <Link to="/login" className="fw-semibold">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
