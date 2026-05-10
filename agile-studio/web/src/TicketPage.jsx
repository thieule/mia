import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MarkdownEditorField from "./MarkdownEditorField.jsx";
import StoryLinkPicker from "./StoryLinkPicker.jsx";
import TicketCommentsSection from "./TicketCommentsSection.jsx";
import { apiDelete, apiPost, getStoredUser } from "./api.js";
import { renderMarkdownWithMentions } from "./markdownWithMentions.jsx";
import {
  TICKET_PRIORITY_OPTIONS,
  TICKET_STATUS_OPTIONS,
  TICKET_TYPE_OPTIONS,
  datetimeLocalToDueIso,
  isoToDatetimeLocal,
  ticketPriorityLabel,
  ticketTypeLabel,
} from "./ticketUiConstants.js";

function mentionKeyFromName(name) {
  return String(name || "")
    .trim()
    .replace(/\s+/g, "")
    .toLowerCase();
}

export default function TicketPage({
  ticket,
  projectId,
  stories,
  projectMembers,
  navigate,
  onPatch,
  onDelete,
  onReload,
  setErr,
  onOpenProjectPicker,
}) {
  const me = getStoredUser();
  const canEdit = me?.member_id != null && projectMembers.some((row) => row.member_id === me.member_id);

  const [taskStatus, setTaskStatus] = useState("open");
  const [ticketPriority, setTicketPriority] = useState("medium");
  const [ticketType, setTicketType] = useState("task");
  const [dueLocal, setDueLocal] = useState("");
  const [done, setDone] = useState(false);
  const [title, setTitle] = useState("");
  const [assigneeIds, setAssigneeIds] = useState([]);
  const [reporterId, setReporterId] = useState("");
  const [storyIds, setStoryIds] = useState([]);
  const [bodyMd, setBodyMd] = useState("");
  const [saving, setSaving] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [editingDesc, setEditingDesc] = useState(false);
  const titleInputRef = useRef(null);

  const sortedStories = useMemo(() => {
    if (!Array.isArray(stories)) return [];
    return [...stories].sort((a, b) => String(a.story_key || a.id).localeCompare(String(b.story_key || b.id)));
  }, [stories]);

  const mentionIndex = useMemo(() => {
    const map = new Map();
    for (const row of projectMembers || []) {
      const name = row?.member?.display_name;
      if (!name) continue;
      map.set(mentionKeyFromName(name), name);
    }
    return map;
  }, [projectMembers]);

  useEffect(() => {
    if (!ticket?.id) return;
    const aids = Array.isArray(ticket.assignee_ids)
      ? ticket.assignee_ids
      : ticket.assignee_id != null
        ? [ticket.assignee_id]
        : [];
    const ts =
      ticket.task_status && String(ticket.task_status).trim().length
        ? String(ticket.task_status).trim().toLowerCase()
        : null;
    setTitle(ticket.title ?? "");
    setBodyMd(ticket.body ?? "");
    setAssigneeIds(aids);
    setReporterId(ticket.reporter_id != null ? String(ticket.reporter_id) : "");
    setTaskStatus(ts ?? (ticket.done ? "done" : "open"));
    setDone(!!ticket.done);
    setTicketPriority(
      ticket.ticket_priority && String(ticket.ticket_priority).trim()
        ? String(ticket.ticket_priority).toLowerCase()
        : "medium"
    );
    setTicketType(
      ticket.ticket_type && String(ticket.ticket_type).trim()
        ? String(ticket.ticket_type).toLowerCase()
        : "task"
    );
    setDueLocal(isoToDatetimeLocal(ticket.due_at));
    const sids =
      Array.isArray(ticket.story_ids) && ticket.story_ids.length
        ? ticket.story_ids.map(Number).filter((x) => Number.isFinite(x))
        : ticket.story_id != null
          ? [Number(ticket.story_id)]
          : [];
    setStoryIds(sids);
  }, [ticket]);

  useEffect(() => {
    if (!editingTitle || !titleInputRef.current) return;
    const el = titleInputRef.current;
    el.focus();
    try {
      el.select();
    } catch {
      /* ignore */
    }
  }, [editingTitle]);

  const storyRows = useMemo(() => {
    if (!ticket?.id) return [];
    return Array.isArray(ticket.story_ids) && ticket.story_ids.length
      ? ticket.story_ids.map((sid, idx) => ({
          id: sid,
          key: ticket.story_keys?.[idx] || `#${sid}`,
          title: ticket.story_titles?.[idx] || "",
        }))
      : [];
  }, [ticket]);

  const toggleWatch = useCallback(async () => {
    if (me?.member_id == null || !ticket?.id) return;
    setErr(null);
    try {
      const wids = Array.isArray(ticket.watcher_member_ids) ? ticket.watcher_member_ids : [];
      const watching = wids.includes(me.member_id);
      const path = `/projects/${projectId}/tasks/${ticket.id}/watch`;
      if (watching) await apiDelete(path);
      else await apiPost(path, {});
      await onReload?.();
    } catch (e) {
      setErr(e.message);
    }
  }, [me?.member_id, onReload, projectId, setErr, ticket?.id, ticket?.watcher_member_ids]);

  const discardDrafts = useCallback(() => {
    if (!ticket?.id) return;
    const aids = Array.isArray(ticket.assignee_ids)
      ? ticket.assignee_ids
      : ticket.assignee_id != null
        ? [ticket.assignee_id]
        : [];
    const ts =
      ticket.task_status && String(ticket.task_status).trim().length
        ? String(ticket.task_status).trim().toLowerCase()
        : null;
    setTitle(ticket.title ?? "");
    setBodyMd(ticket.body ?? "");
    setAssigneeIds(aids);
    setReporterId(ticket.reporter_id != null ? String(ticket.reporter_id) : "");
    setTaskStatus(ts ?? (ticket.done ? "done" : "open"));
    setDone(!!ticket.done);
    setTicketPriority(
      ticket.ticket_priority && String(ticket.ticket_priority).trim()
        ? String(ticket.ticket_priority).toLowerCase()
        : "medium"
    );
    setTicketType(
      ticket.ticket_type && String(ticket.ticket_type).trim()
        ? String(ticket.ticket_type).toLowerCase()
        : "task"
    );
    setDueLocal(isoToDatetimeLocal(ticket.due_at));
    const sids =
      Array.isArray(ticket.story_ids) && ticket.story_ids.length
        ? ticket.story_ids.map(Number).filter((x) => Number.isFinite(x))
        : ticket.story_id != null
          ? [Number(ticket.story_id)]
          : [];
    setStoryIds(sids);
    setEditingTitle(false);
    setEditingDesc(false);
  }, [ticket]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const t = title.trim();
    if (!t) return;
    const dueIso = datetimeLocalToDueIso(dueLocal);
    if (dueIso === undefined) {
      setErr("Invalid due date.");
      return;
    }
    const rawBody = bodyMd.trim();
    const reporter_id = reporterId === "" ? null : Number(reporterId);
    let ts = taskStatus || "open";
    if (done && ts !== "done") ts = "done";
    if (!done && ts === "done") ts = "open";
    setSaving(true);
    setErr(null);
    try {
      await onPatch({
        title: t,
        body: rawBody.length ? rawBody : null,
        assignee_ids: Array.isArray(assigneeIds) ? assigneeIds.map(Number) : [],
        reporter_id,
        task_status: ts,
        ticket_priority: ticketPriority || "medium",
        ticket_type: ticketType || "task",
        due_at: dueIso,
        story_ids: storyIds.map(Number).filter((x) => Number.isFinite(x)),
      });
      setEditingTitle(false);
      setEditingDesc(false);
      await onReload?.();
    } catch {
      /* parent setErr */
    } finally {
      setSaving(false);
    }
  };

  const watching = me?.member_id != null && (ticket?.watcher_member_ids || []).includes(me.member_id);

  if (!projectId || !ticket?.id) {
    return (
      <div className="as-panel">
        <div className="as-empty py-5">
          <p className="mb-0 text-secondary">Missing ticket.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="as-ticket-edit">
      <div className="as-ticket-edit-bar d-flex flex-wrap align-items-center justify-content-between gap-2 mb-3">
        <div className="d-flex flex-wrap align-items-center gap-2">
          <button type="button" className="btn btn-outline-secondary btn-sm" onClick={() => navigate(`/p/${projectId}/tickets`)}>
            <i className="bi bi-arrow-left me-1" aria-hidden />
            Tickets
          </button>
          {storyRows.map((s) => (
            <button
              key={s.id}
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={() => navigate(`/p/${projectId}/story/${s.id}`)}
            >
              <i className="bi bi-journal-text me-1" aria-hidden />
              <span className="font-monospace">{s.key}</span>
            </button>
          ))}
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary"
            title="Copy link"
            onClick={() => {
              const u = `${window.location.origin}${window.location.pathname}`;
              navigator.clipboard?.writeText(u).catch(() => {});
            }}
          >
            <i className="bi bi-link-45deg me-1" aria-hidden />
            Copy link
          </button>
        </div>
        <div className="d-flex flex-wrap gap-2 align-items-center">
          <button
            type="button"
            className={`btn btn-sm ${watching ? "btn-warning" : "btn-outline-secondary"}`}
            disabled={!me?.member_id}
            title="Watch"
            onClick={() => toggleWatch()}
          >
            <i className="bi bi-eye" aria-hidden />
            {(ticket.watcher_member_ids || []).length ? ` ${(ticket.watcher_member_ids || []).length}` : ""}
          </button>
          {canEdit ? (
            <button type="button" className="btn btn-outline-danger btn-sm" onClick={() => onDelete?.()}>
              <i className="bi bi-trash me-1" aria-hidden />
              Delete
            </button>
          ) : null}
          {onOpenProjectPicker ? (
            <button type="button" className="btn btn-outline-secondary btn-sm" onClick={onOpenProjectPicker}>
              <i className="bi bi-folder2 me-1" aria-hidden />
              Switch project
            </button>
          ) : null}
        </div>
      </div>

      {!canEdit ? (
        <div className="as-panel border-warning-subtle mb-4">
          <div className="as-panel-bd">
            <p className="mb-0 small">
              Join this project&apos;s <strong>Team</strong> to edit fields or delete this ticket.
            </p>
          </div>
        </div>
      ) : null}

      <div className="d-flex flex-wrap align-items-center gap-2 mb-3">
        <span className="badge rounded-pill bg-secondary-subtle text-dark px-3 py-2">{ticketPriorityLabel(ticketPriority)}</span>
        <span className="badge rounded-pill bg-info-subtle text-dark px-3 py-2">{ticketTypeLabel(ticketType)}</span>
        <span
          className={`badge rounded-pill px-3 py-2 ${done ? "bg-success-subtle text-success-emphasis" : "bg-light text-secondary border"}`}
        >
          {done ? "Done" : (taskStatus || "open").replace(/_/g, " ")}
        </span>
        {storyRows.length === 0 ? (
          <span className="small text-secondary ms-1">Project ticket · no linked stories</span>
        ) : null}
      </div>

      <form
        onSubmit={(e) => {
          if (!canEdit) {
            e.preventDefault();
            return;
          }
          handleSubmit(e);
        }}
      >
        <div className="as-ticket-edit-layout mb-4">
          <div className="as-ticket-edit-main">
            <section className="as-ticket-fieldset">
              <h2 className="as-ticket-fieldset-title">Summary</h2>
              {canEdit && editingTitle ? (
                <>
                  <label className="as-ticket-label" htmlFor="as-tp-title">
                    Title <span className="text-danger">*</span>
                  </label>
                  <input
                    ref={titleInputRef}
                    id="as-tp-title"
                    type="text"
                    className="form-control form-control-lg as-ticket-title-input mb-0"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    maxLength={500}
                    required
                    onBlur={() => setEditingTitle(false)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        setEditingTitle(false);
                      }
                      if (e.key === "Escape") {
                        e.preventDefault();
                        setTitle(ticket.title ?? "");
                        setEditingTitle(false);
                      }
                    }}
                  />
                  <p className="small text-secondary mb-0 mt-2">Enter or blur to finish · Esc reverts the title.</p>
                </>
              ) : (
                <>
                  <div
                    className={`as-ticket-inline-title-target mb-0 ${canEdit ? "as-ticket-inline-edit-target" : ""}`}
                    onDoubleClick={
                      canEdit
                        ? () => {
                            setEditingTitle(true);
                          }
                        : undefined
                    }
                    role={canEdit ? "button" : undefined}
                    tabIndex={canEdit ? 0 : undefined}
                    onKeyDown={
                      canEdit
                        ? (e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              setEditingTitle(true);
                            }
                          }
                        : undefined
                    }
                  >
                    <div className="as-ticket-view-title text-break mb-0">{title.trim() || "—"}</div>
                  </div>
                </>
              )}
            </section>

            <section className="as-ticket-fieldset mb-0">
              <div className="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-2">
                <h2 className="as-ticket-fieldset-title mb-0">Description</h2>
                {canEdit && editingDesc ? (
                  <button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => setEditingDesc(false)}>
                    Done
                  </button>
                ) : null}
              </div>
              {canEdit && editingDesc ? (
                <MarkdownEditorField
                  value={bodyMd}
                  onChange={setBodyMd}
                  height={320}
                  placeholder="Context, steps, background…"
                  projectId={projectId}
                  className="as-ticket-md"
                />
              ) : (
                <div
                  className={`as-ticket-view-panel ${canEdit ? "as-ticket-inline-edit-target" : ""}`}
                  onDoubleClick={canEdit ? () => setEditingDesc(true) : undefined}
                  role={canEdit ? "button" : undefined}
                  tabIndex={canEdit ? 0 : undefined}
                  onKeyDown={
                    canEdit
                      ? (e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setEditingDesc(true);
                          }
                        }
                      : undefined
                  }
                >
                  {bodyMd.trim() ? (
                    <div className="as-story-body as-story-desc-md mb-0">{renderMarkdownWithMentions(bodyMd, mentionIndex)}</div>
                  ) : (
                    <p className="small text-secondary fst-italic mb-0">
                      No description yet.{canEdit ? " Double-click to add." : ""}
                    </p>
                  )}
                </div>
              )}
            </section>

            <TicketCommentsSection projectId={projectId} taskId={ticket.id} projectMembers={projectMembers} setErr={setErr} />
          </div>

          <aside className="as-ticket-edit-aside">
            <section className="as-ticket-fieldset as-ticket-edit-quick">
              <h2 className="as-ticket-fieldset-title">Workflow &amp; triage</h2>
              <p className="as-ticket-fieldset-hint mb-3 small">Status, priority, type, due date.</p>
              <div className="d-flex flex-column gap-3">
                <div>
                  <label className="as-ticket-label" htmlFor="as-tp-status">
                    Status
                  </label>
                  <select
                    id="as-tp-status"
                    className="form-select"
                    value={taskStatus}
                    disabled={!canEdit}
                    onChange={(e) => {
                      const v = e.target.value;
                      setTaskStatus(v);
                      setDone(v === "done");
                    }}
                  >
                    {TICKET_STATUS_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="as-ticket-label" htmlFor="as-tp-priority">
                    Priority
                  </label>
                  <select
                    id="as-tp-priority"
                    className="form-select"
                    value={ticketPriority}
                    disabled={!canEdit}
                    onChange={(e) => setTicketPriority(e.target.value)}
                  >
                    {TICKET_PRIORITY_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="as-ticket-label" htmlFor="as-tp-type">
                    Type
                  </label>
                  <select
                    id="as-tp-type"
                    className="form-select"
                    value={ticketType}
                    disabled={!canEdit}
                    onChange={(e) => setTicketType(e.target.value)}
                  >
                    {TICKET_TYPE_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="as-ticket-label" htmlFor="as-tp-due">
                    Due
                  </label>
                  <input
                    id="as-tp-due"
                    type="datetime-local"
                    className="form-control"
                    value={dueLocal}
                    disabled={!canEdit}
                    onChange={(e) => setDueLocal(e.target.value)}
                  />
                </div>
                <div className="form-check mb-0">
                  <input
                    id="as-tp-done"
                    type="checkbox"
                    className="form-check-input"
                    checked={done}
                    disabled={!canEdit}
                    onChange={(e) => {
                      const c = e.target.checked;
                      setDone(c);
                      if (c) setTaskStatus("done");
                      else if (taskStatus === "done") setTaskStatus("open");
                    }}
                  />
                  <label className="form-check-label" htmlFor="as-tp-done">
                    Mark as done
                  </label>
                </div>
              </div>
            </section>

            <section className="as-ticket-fieldset">
              <h2 className="as-ticket-fieldset-title">People</h2>
              <label className="as-ticket-label">Assignees</label>
              <p className="as-ticket-sublabel mb-1 small">Cmd/Ctrl + click for multiple.</p>
              <select
                className="form-select mb-3"
                multiple
                size={Math.min(5, Math.max(3, projectMembers.length || 3))}
                value={assigneeIds.map(String)}
                disabled={!canEdit}
                onChange={(e) => setAssigneeIds(Array.from(e.target.selectedOptions, (o) => Number(o.value)))}
                aria-label="Assignees"
              >
                {projectMembers.map((row) => (
                  <option key={row.member_id} value={row.member_id}>
                    {row.member?.display_name ?? `Member #${row.member_id}`}
                    {row.member?.member_type === "ai" ? " (AI)" : ""}
                  </option>
                ))}
              </select>
              <label className="as-ticket-label" htmlFor="as-tp-reporter">
                Reporter
              </label>
              <select
                id="as-tp-reporter"
                className="form-select"
                value={reporterId}
                disabled={!canEdit}
                onChange={(e) => setReporterId(e.target.value)}
              >
                <option value="">— None —</option>
                {projectMembers.map((row) => (
                  <option key={row.member_id} value={row.member_id}>
                    {row.member?.display_name ?? `Member #${row.member_id}`}
                  </option>
                ))}
              </select>
            </section>

            <section className="as-ticket-fieldset mb-0">
              <StoryLinkPicker
                stories={sortedStories}
                value={storyIds}
                onChange={setStoryIds}
                id="as-tp-story-search"
                disabled={!canEdit}
              />
            </section>
          </aside>
        </div>

        {canEdit ? (
          <div className="as-ticket-edit-actions d-flex flex-wrap gap-2 justify-content-end pb-4">
            <button type="button" className="btn btn-outline-secondary" onClick={discardDrafts} disabled={saving}>
              Discard changes
            </button>
            <button type="submit" className="btn btn-primary btn-lg px-4" disabled={!title.trim() || saving}>
              {saving ? (
                <>
                  <span className="spinner-border spinner-border-sm me-2" aria-hidden />
                  Saving…
                </>
              ) : (
                "Save changes"
              )}
            </button>
          </div>
        ) : (
          <div className="pb-4" />
        )}
      </form>
    </div>
  );
}
