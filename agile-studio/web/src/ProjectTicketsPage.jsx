import { useCallback, useEffect, useState } from "react";
import { apiDelete, apiGet, apiPost, getStoredUser } from "./api.js";
import {
  TICKET_PRIORITY_OPTIONS,
  TICKET_STATUS_OPTIONS,
  TICKET_TYPE_OPTIONS,
  ticketPriorityLabel,
  ticketTypeLabel,
} from "./ticketUiConstants.js";

const TICKET_STATUS_FILTER = [{ value: "", label: "All statuses" }, ...TICKET_STATUS_OPTIONS];

function statusLabel(s) {
  if (!s) return "—";
  return TICKET_STATUS_FILTER.find((o) => o.value === s)?.label ?? s;
}

const PAGE_SIZE_OPTIONS = [25, 50, 100];

function formatDue(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return String(iso);
  }
}

const PRIORITY_FILTER = [{ value: "", label: "All priorities" }, ...TICKET_PRIORITY_OPTIONS];
const TYPE_FILTER = [{ value: "", label: "All types" }, ...TICKET_TYPE_OPTIONS];

export default function ProjectTicketsPage({ projectId, projectMembers, stories, setErr, navigate, onOpenProjectPicker }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [assigneeFilter, setAssigneeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [storyFilter, setStoryFilter] = useState("");
  const [qInput, setQInput] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [watchedOnly, setWatchedOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => setQDebounced(qInput.trim()), 380);
    return () => clearTimeout(t);
  }, [qInput]);

  useEffect(() => {
    setPage(1);
  }, [assigneeFilter, statusFilter, priorityFilter, typeFilter, storyFilter, qDebounced, watchedOnly]);

  useEffect(() => {
    setPage((p) => {
      const tp = Math.max(1, Math.ceil(total / pageSize) || 1);
      return p > tp ? tp : p;
    });
  }, [total, pageSize]);

  const loadTickets = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (assigneeFilter) params.set("assignee_member_id", assigneeFilter);
      if (statusFilter) params.set("task_status", statusFilter);
      if (priorityFilter) params.set("ticket_priority", priorityFilter);
      if (typeFilter) params.set("ticket_type", typeFilter);
      if (storyFilter) params.set("story_id", storyFilter);
      if (qDebounced) params.set("q", qDebounced);
      if (watchedOnly) params.set("watched_by_me", "true");
      params.set("limit", String(pageSize));
      params.set("offset", String((page - 1) * pageSize));
      const qs = params.toString();
      const data = await apiGet(`/projects/${projectId}/tasks${qs ? `?${qs}` : ""}`, { cache: "no-store" });
      if (data && Array.isArray(data.items)) {
        setRows(data.items);
        setTotal(typeof data.total === "number" ? data.total : data.items.length);
      } else if (Array.isArray(data)) {
        setRows(data);
        setTotal(data.length);
      } else {
        setRows([]);
        setTotal(0);
      }
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, [
    projectId,
    assigneeFilter,
    statusFilter,
    priorityFilter,
    typeFilter,
    storyFilter,
    qDebounced,
    watchedOnly,
    page,
    pageSize,
    setErr,
  ]);

  useEffect(() => {
    void loadTickets();
  }, [loadTickets]);

  const me = getStoredUser();
  const mid = me?.member_id;

  const formatNames = (ids) => {
    if (!Array.isArray(ids) || !ids.length) return "—";
    return ids
      .map((id) => projectMembers.find((r) => r.member_id === id)?.member?.display_name ?? `#${id}`)
      .join(", ");
  };

  const toggleWatch = async (row) => {
    if (mid == null) return;
    setErr(null);
    try {
      const watching = Array.isArray(row.watcher_member_ids) && row.watcher_member_ids.includes(mid);
      if (watching) await apiDelete(`/projects/${projectId}/tasks/${row.id}/watch`);
      else await apiPost(`/projects/${projectId}/tasks/${row.id}/watch`, {});
      await loadTickets();
    } catch (e) {
      setErr(e.message);
    }
  };

  const sortedStories = Array.isArray(stories)
    ? [...stories].sort((a, b) => String(a.story_key || a.id).localeCompare(String(b.story_key || b.id)))
    : [];

  const totalPages = Math.max(1, Math.ceil(total / pageSize) || 1);
  const rangeFrom = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeTo = total === 0 ? 0 : Math.min(page * pageSize, total);

  return (
    <>
      <div className="as-page-head d-flex flex-wrap justify-content-between align-items-start gap-2">
        <div>
          <h1 className="as-page-title">Tickets</h1>
          <p className="as-page-desc mb-0">All tickets in this project — filter by assignee, status, type, priority, or story.</p>
        </div>
        {projectId ? (
          <div className="d-flex flex-wrap gap-2 align-items-center">
            <button
              type="button"
              className="btn btn-primary btn-sm flex-shrink-0"
              onClick={() => navigate(`/p/${projectId}/ticket/new`)}
            >
              <i className="bi bi-plus-lg me-1" aria-hidden />
              Create ticket
            </button>
            {onOpenProjectPicker ? (
              <button type="button" className="btn btn-outline-secondary btn-sm flex-shrink-0" onClick={onOpenProjectPicker}>
                <i className="bi bi-folder2 me-1" aria-hidden />
                Switch project
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      {!projectId ? (
        <div className="as-panel">
          <div className="as-empty">
            <div className="as-empty-icon">
              <i className="bi bi-ticket-detailed" />
            </div>
            <p className="mb-2">Select a project to list tickets.</p>
          </div>
        </div>
      ) : (
        <div className="as-panel">
          <div className="as-panel-bd">
            <div className="row g-2 align-items-end mb-3">
              <div className="col-12 col-md-3 col-xl-2">
                <label className="form-label small text-secondary mb-1">Assignee</label>
                <select
                  className="form-select form-select-sm"
                  value={assigneeFilter}
                  onChange={(e) => setAssigneeFilter(e.target.value)}
                >
                  <option value="">Anyone</option>
                  {projectMembers.map((row) => (
                    <option key={row.member_id} value={String(row.member_id)}>
                      {row.member?.display_name ?? `Member #${row.member_id}`}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-6 col-md-2 col-xl-2">
                <label className="form-label small text-secondary mb-1">Status</label>
                <select
                  className="form-select form-select-sm"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                >
                  {TICKET_STATUS_FILTER.map((o) => (
                    <option key={o.value || "all"} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-6 col-md-2 col-xl-2">
                <label className="form-label small text-secondary mb-1">Priority</label>
                <select
                  className="form-select form-select-sm"
                  value={priorityFilter}
                  onChange={(e) => setPriorityFilter(e.target.value)}
                >
                  {PRIORITY_FILTER.map((o) => (
                    <option key={o.value || "all-pri"} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-12 col-md-3 col-xl-2">
                <label className="form-label small text-secondary mb-1">Type</label>
                <select
                  className="form-select form-select-sm"
                  value={typeFilter}
                  onChange={(e) => setTypeFilter(e.target.value)}
                >
                  {TYPE_FILTER.map((o) => (
                    <option key={o.value || "all-type"} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-12 col-md-4 col-xl-3">
                <label className="form-label small text-secondary mb-1">Story</label>
                <select
                  className="form-select form-select-sm"
                  value={storyFilter}
                  onChange={(e) => setStoryFilter(e.target.value)}
                >
                  <option value="">All stories</option>
                  {sortedStories.map((s) => (
                    <option key={s.id} value={String(s.id)}>
                      {s.story_key ? `${s.story_key} — ` : ""}
                      {s.title}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-12 col-md-2 col-xl-1">
                <div className="form-check mt-3 mt-md-4">
                  <input
                    className="form-check-input"
                    type="checkbox"
                    id="as-tickets-watched-only"
                    checked={watchedOnly}
                    onChange={(e) => setWatchedOnly(e.target.checked)}
                  />
                  <label className="form-check-label small" htmlFor="as-tickets-watched-only">
                    Watching
                  </label>
                </div>
              </div>
              <div className="col-12 col-md-6 col-lg-4">
                <label className="form-label small text-secondary mb-1">Title contains</label>
                <input
                  className="form-control form-control-sm"
                  value={qInput}
                  onChange={(e) => setQInput(e.target.value)}
                  placeholder="Search ticket title…"
                />
              </div>
            </div>

            {loading ? (
              <p className="small text-secondary mb-0">Loading…</p>
            ) : rows.length === 0 ? (
              <p className="small text-secondary fst-italic mb-0">No tickets match these filters.</p>
            ) : (
              <div className="table-responsive">
                <table className="table table-sm table-hover align-middle mb-0">
                  <thead>
                    <tr>
                      <th>Ticket</th>
                      <th>Priority</th>
                      <th>Type</th>
                      <th>Due</th>
                      <th>Stories</th>
                      <th>Status</th>
                      <th>Assignees</th>
                      <th>Watch</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((t) => {
                      const watching = mid != null && Array.isArray(t.watcher_member_ids) && t.watcher_member_ids.includes(mid);
                      return (
                        <tr key={t.id}>
                          <td>
                            <button
                              type="button"
                              className="btn btn-link btn-sm text-start p-0 text-decoration-none fw-semibold"
                              onClick={() => navigate(`/p/${projectId}/ticket/${t.id}`)}
                            >
                              {t.title}
                            </button>
                          </td>
                          <td className="small">
                            <span className="badge bg-secondary-subtle text-dark">{ticketPriorityLabel(t.ticket_priority)}</span>
                          </td>
                          <td className="small">
                            <span className="badge bg-info-subtle text-dark">{ticketTypeLabel(t.ticket_type)}</span>
                          </td>
                          <td className="small text-secondary text-nowrap">{formatDue(t.due_at)}</td>
                          <td className="small">
                            {Array.isArray(t.story_keys) && t.story_keys.length ? (
                              t.story_keys.map((sk, i) => (
                                <div key={`${t.id}-sk-${i}`} className={i ? "mt-1 pt-1 border-top border-light" : ""}>
                                  <div className="text-secondary font-monospace">{sk}</div>
                                  <div className="text-truncate" style={{ maxWidth: 220 }} title={t.story_titles?.[i] || ""}>
                                    {t.story_titles?.[i] || "—"}
                                  </div>
                                </div>
                              ))
                            ) : (
                              <>
                                <div className="text-muted fst-italic small">Project ticket</div>
                                <div className="text-secondary">—</div>
                              </>
                            )}
                          </td>
                          <td>
                            <span className="badge bg-secondary-subtle text-dark">{statusLabel(t.task_status)}</span>
                          </td>
                          <td className="small">{formatNames(t.assignee_ids?.length ? t.assignee_ids : t.assignee_id != null ? [t.assignee_id] : [])}</td>
                          <td>
                            <button
                              type="button"
                              className={`btn btn-sm ${watching ? "btn-warning" : "btn-outline-secondary"}`}
                              disabled={mid == null}
                              title={watching ? "Stop watching" : "Watch"}
                              onClick={() => toggleWatch(t)}
                            >
                              <i className="bi bi-eye" aria-hidden />
                              {Array.isArray(t.watcher_member_ids) && t.watcher_member_ids.length
                                ? ` ${t.watcher_member_ids.length}`
                                : ""}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {!loading && total > 0 ? (
              <div className="as-tickets-pager d-flex flex-wrap align-items-center justify-content-between gap-2">
                <div className="small text-secondary">
                  Showing <strong className="text-dark">{rangeFrom}</strong>–<strong className="text-dark">{rangeTo}</strong> of{" "}
                  <strong className="text-dark">{total}</strong>
                </div>
                <div className="d-flex flex-wrap align-items-center gap-2">
                  <label className="small text-secondary mb-0 d-flex align-items-center gap-2">
                    Rows per page
                    <select
                      className="form-select form-select-sm"
                      style={{ width: "5.25rem" }}
                      value={String(pageSize)}
                      onChange={(e) => {
                        setPageSize(Number(e.target.value));
                        setPage(1);
                      }}
                      aria-label="Rows per page"
                    >
                      {PAGE_SIZE_OPTIONS.map((n) => (
                        <option key={n} value={String(n)}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="btn-group btn-group-sm" role="group" aria-label="Pagination">
                    <button
                      type="button"
                      className="btn btn-outline-secondary"
                      disabled={page <= 1}
                      onClick={() => setPage(1)}
                      title="First page"
                    >
                      «
                    </button>
                    <button
                      type="button"
                      className="btn btn-outline-secondary"
                      disabled={page <= 1}
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                    >
                      Previous
                    </button>
                    <span className="btn btn-outline-secondary disabled" aria-current="page">
                      {page} / {totalPages}
                    </span>
                    <button
                      type="button"
                      className="btn btn-outline-secondary"
                      disabled={page >= totalPages}
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    >
                      Next
                    </button>
                    <button
                      type="button"
                      className="btn btn-outline-secondary"
                      disabled={page >= totalPages}
                      onClick={() => setPage(totalPages)}
                      title="Last page"
                    >
                      »
                    </button>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}
    </>
  );
}
