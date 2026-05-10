import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiGetPublic, apiPost, getStoredUser, getToken } from "./api.js";

export default function ProjectInvitePage() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [preview, setPreview] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [accepting, setAccepting] = useState(false);

  const me = getStoredUser();
  const authed = Boolean(getToken() && me);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setErr(null);
    try {
      const data = await apiGetPublic(`/invites/token/${encodeURIComponent(token)}`);
      setPreview(data);
    } catch (e2) {
      setErr(e2.message || "Could not load invitation");
      setPreview(null);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const emailMatches =
    authed && preview?.valid && me?.email && preview.email && String(me.email).toLowerCase() === String(preview.email).toLowerCase();

  const onAccept = async () => {
    if (!token || !authed) return;
    setAccepting(true);
    setErr(null);
    try {
      const row = await apiPost(`/invites/token/${encodeURIComponent(token)}/accept`, {});
      navigate(`/p/${row.project_id}/team`, { replace: true });
    } catch (e2) {
      setErr(e2.message || "Could not accept");
    } finally {
      setAccepting(false);
    }
  };

  const loginHref = `/login?invite=${encodeURIComponent(token || "")}`;
  const registerHref = `/register?invite=${encodeURIComponent(token || "")}`;

  return (
    <div className="as-auth-page min-vh-100 d-flex align-items-center justify-content-center p-3">
      <div className="as-auth-card card shadow border-0" style={{ width: "100%", maxWidth: 480 }}>
        <div className="card-body p-4 p-md-5">
          <div className="text-center mb-4">
            <div
              className="d-inline-flex align-items-center justify-content-center rounded-3 bg-primary text-white mb-3"
              style={{ width: 48, height: 48 }}
            >
              <i className="bi bi-envelope-open fs-4" aria-hidden />
            </div>
            <h1 className="h4 fw-semibold mb-1">Lời mời dự án</h1>
            <p className="small text-secondary mb-0">Tham gia Agile Studio qua email mời.</p>
          </div>

          {loading ? (
            <p className="text-center text-secondary small mb-0">Đang tải…</p>
          ) : err && !preview ? (
            <div className="alert alert-danger small py-2">{err}</div>
          ) : preview && !preview.valid ? (
            <div className="alert alert-warning small py-2">
              {preview.reason === "accepted"
                ? "Lời mời đã được chấp nhận trước đó. Đăng nhập và chọn dự án trong menu."
                : preview.reason === "expired"
                  ? "Lời mời đã hết hạn. Nhờ admin gửi lại."
                  : preview.reason === "revoked"
                    ? "Lời mời đã bị thu hồi."
                    : "Liên kết không hợp lệ."}
            </div>
          ) : preview?.valid ? (
            <>
              <div className="border rounded-3 p-3 mb-3 bg-light-subtle">
                <div className="small text-secondary mb-1">Dự án</div>
                <div className="fw-semibold">{preview.project_name}</div>
                <div className="small text-muted">{preview.project_slug}</div>
                <hr className="my-2" />
                <div className="small text-secondary mb-1">Email được mời</div>
                <div className="font-monospace small">{preview.email}</div>
                {preview.expires_at ? (
                  <div className="small text-muted mt-2">Hết hạn: {new Date(preview.expires_at).toLocaleString()}</div>
                ) : null}
              </div>

              {err ? (
                <div className="alert alert-danger small py-2" role="alert">
                  {err}
                </div>
              ) : null}

              {!authed ? (
                <div className="vstack gap-2">
                  <p className="small text-secondary mb-0">
                    Đăng nhập bằng đúng email <strong>{preview.email}</strong>, hoặc tạo tài khoản mới với email đó.
                  </p>
                  <Link className="btn btn-primary" to={loginHref}>
                    Đăng nhập
                  </Link>
                  <Link className="btn btn-outline-primary" to={registerHref}>
                    Đăng ký
                  </Link>
                </div>
              ) : emailMatches ? (
                <div className="vstack gap-2">
                  <p className="small text-secondary mb-0">
                    Bạn đang đăng nhập là <strong>{me.display_name}</strong> ({me.email}).
                  </p>
                  <button type="button" className="btn btn-success" disabled={accepting} onClick={onAccept}>
                    {accepting ? "Đang tham gia…" : "Chấp nhận tham gia dự án"}
                  </button>
                </div>
              ) : (
                <div className="alert alert-warning small py-2 mb-0">
                  Bạn đang đăng nhập với <strong>{me.email}</strong>, khác email được mời. Hãy{" "}
                  <Link to={loginHref}>đăng xuất và đăng nhập</Link> đúng tài khoản được mời.
                </div>
              )}
            </>
          ) : null}

          <p className="small text-center text-secondary mt-4 mb-0">
            <Link to="/">Về trang chủ</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
