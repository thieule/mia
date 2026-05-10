import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import MarkdownEditorField from "./MarkdownEditorField.jsx";
import StoryLinkPicker from "./StoryLinkPicker.jsx";
import { getStoredUser } from "./api.js";
import {
  TICKET_PRIORITY_OPTIONS,
  TICKET_STATUS_OPTIONS,
  TICKET_TYPE_OPTIONS,
  datetimeLocalToDueIso,
} from "./ticketUiConstants.js";

export default function TicketCreatePage({
  projectId,
  stories,
  projectMembers,
  onCreateTask,
  navigate,
  setErr,
  onOpenProjectPicker,
}) {
  const [searchParams] = useSearchParams();
  const storyParam = searchParams.get("story");
  const preStoryId = storyParam != null && storyParam !== "" ? Number(storyParam) : NaN;

  const me = getStoredUser();
  const canCreate = me?.member_id != null && projectMembers.some((row) => row.member_id === me.member_id);

  const sortedStories = useMemo(() => {
    if (!Array.isArray(stories)) return [];
    return [...stories].sort((a, b) => String(a.story_key || a.id).localeCompare(String(b.story_key || b.id)));
  }, [stories]);

  const validPreStory =
    Number.isFinite(preStoryId) && sortedStories.some((s) => Number(s.id) === preStoryId) ? preStoryId : null;

  const [storyIds, setStoryIds] = useState(() => (validPreStory != null ? [validPreStory] : []));

  useEffect(() => {
    if (storyParam == null || storyParam === "") return;
    const sp = Number(storyParam);
    if (!Number.isFinite(sp) || !sortedStories.some((s) => Number(s.id) === sp)) return;
    setStoryIds((prev) => (prev.includes(sp) ? prev : [...prev, sp]));
  }, [storyParam, sortedStories]);
  const [title, setTitle] = useState("");
  const [bodyMd, setBodyMd] = useState("");
  const [taskStatus, setTaskStatus] = useState("open");
  const [ticketPriority, setTicketPriority] = useState("medium");
  const [ticketType, setTicketType] = useState("task");
  const [dueLocal, setDueLocal] = useState("");
  const [assigneeIds, setAssigneeIds] = useState([]);
  const [reporterId, setReporterId] = useState(() => (me?.member_id != null ? String(me.member_id) : ""));
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e) => {
    e.preventDefault();
    setErr(null);
    const t = title.trim();
    if (!t) {
      setErr("Title is required.");
      return;
    }
    const dueIso = datetimeLocalToDueIso(dueLocal);
    if (dueIso === undefined) {
      setErr("Invalid due date.");
      return;
    }
    const rawBody = bodyMd.trim();
    const reporter_id = reporterId === "" ? null : Number(reporterId);
    setSubmitting(true);
    try {
      await onCreateTask({
        story_ids: storyIds.filter((x) => Number.isFinite(Number(x))).map(Number),
        title: t,
        body: rawBody.length ? rawBody : null,
        task_status: taskStatus,
        ticket_priority: ticketPriority,
        ticket_type: ticketType,
        due_at: dueIso,
        assignee_ids: Array.isArray(assigneeIds) ? assigneeIds.map(Number) : [],
        reporter_id,
      });
      navigate(`/p/${projectId}/tickets`);
    } catch {
      /* onCreateTask already setErr */
    } finally {
      setSubmitting(false);
    }
  };

  if (!projectId) {
    return (
      <div className="as-panel">
        <div className="as-empty">
          <p className="mb-2">Select a project to create a ticket.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="as-ticket-create">
      <div className="as-ticket-create-bar d-flex flex-wrap align-items-center justify-content-between gap-2 mb-3">
        <button type="button" className="btn btn-outline-secondary" onClick={() => navigate(`/p/${projectId}/tickets`)}>
          <i className="bi bi-arrow-left me-2" aria-hidden />
          Back to tickets
        </button>
        {onOpenProjectPicker ? (
          <button type="button" className="btn btn-outline-secondary btn-sm" onClick={onOpenProjectPicker}>
            <i className="bi bi-folder2 me-1" aria-hidden />
            Switch project
          </button>
        ) : null}
      </div>

      <div className="as-ticket-create-hero mb-4">
        <p className="as-ticket-create-kicker small text-secondary text-uppercase fw-semibold mb-2">Create work item</p>
        <h1 className="as-page-title mb-2">New ticket</h1>
        <p className="as-page-desc mb-0 text-secondary">
          Optionally link one or more stories, or leave unlinked for a project-only ticket.
        </p>
      </div>

      {!canCreate ? (
        <div className="as-panel border-warning-subtle mb-4">
          <div className="as-panel-bd">
            <p className="mb-0 small">
              Join this project&apos;s <strong>Team</strong> to create tickets.
            </p>
          </div>
        </div>
      ) : null}

      <form onSubmit={onSubmit} className={`as-ticket-create-grid ${!canCreate ? "opacity-50" : ""}`} noValidate>
        <div className="as-ticket-create-main">
          <section className="as-ticket-fieldset">
            <h2 className="as-ticket-fieldset-title">Details</h2>
            <p className="as-ticket-fieldset-hint">What needs to happen and why.</p>

            <div className="mb-3">
              <label className="as-ticket-label" htmlFor="as-new-ticket-title">
                Summary <span className="text-danger">*</span>
              </label>
              <input
                id="as-new-ticket-title"
                type="text"
                className="form-control form-control-lg as-ticket-title-input"
                placeholder="Short title shown in lists and search"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={500}
                required
                disabled={!canCreate}
                autoFocus
              />
            </div>

            <div className="mb-0">
              <label className="as-ticket-label" htmlFor="as-new-ticket-body">
                Description
              </label>
              <p className="as-ticket-sublabel">Context, reproduction steps for bugs, or background for the team.</p>
              <MarkdownEditorField
                value={bodyMd}
                onChange={setBodyMd}
                height={280}
                placeholder="Markdown supported"
                textareaProps={{ id: "as-new-ticket-body", disabled: !canCreate }}
                projectId={projectId}
                className="as-ticket-md"
              />
            </div>
          </section>
        </div>

        <aside className="as-ticket-create-side">
          <section className="as-ticket-fieldset as-ticket-fieldset-sticky">
            <h2 className="as-ticket-fieldset-title">Triage</h2>
            <p className="as-ticket-fieldset-hint mb-3">Status, priority, and scheduling first.</p>

            <div className="row g-2 mb-3">
              <div className="col-md-12">
                <label className="as-ticket-label" htmlFor="as-new-ticket-type">
                  Type
                </label>
                <select
                  id="as-new-ticket-type"
                  className="form-select"
                  value={ticketType}
                  onChange={(e) => setTicketType(e.target.value)}
                  disabled={!canCreate}
                >
                  {TICKET_TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-6">
                <label className="as-ticket-label" htmlFor="as-new-ticket-priority">
                  Priority
                </label>
                <select
                  id="as-new-ticket-priority"
                  className="form-select"
                  value={ticketPriority}
                  onChange={(e) => setTicketPriority(e.target.value)}
                  disabled={!canCreate}
                >
                  {TICKET_PRIORITY_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-6">
                <label className="as-ticket-label" htmlFor="as-new-ticket-status">
                  Workflow
                </label>
                <select
                  id="as-new-ticket-status"
                  className="form-select"
                  value={taskStatus}
                  onChange={(e) => setTaskStatus(e.target.value)}
                  disabled={!canCreate}
                >
                  {TICKET_STATUS_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="mb-4">
              <label className="as-ticket-label" htmlFor="as-new-ticket-due">
                Due date
              </label>
              <input
                id="as-new-ticket-due"
                type="datetime-local"
                className="form-control"
                value={dueLocal}
                onChange={(e) => setDueLocal(e.target.value)}
                disabled={!canCreate}
              />
            </div>

            <h3 className="as-ticket-subheading">Linked stories</h3>
            <div className="mb-4">
              <StoryLinkPicker
                stories={sortedStories}
                value={storyIds}
                onChange={setStoryIds}
                disabled={!canCreate}
                id="as-new-ticket-story-search"
              />
            </div>

            <h3 className="as-ticket-subheading">People</h3>

            <div className="mb-3">
              <label className="as-ticket-label">Assignees</label>
              <p className="as-ticket-sublabel mb-1">Hold Cmd/Ctrl for multiple.</p>
              <select
                className="form-select"
                multiple
                size={Math.min(6, Math.max(3, projectMembers.length || 3))}
                value={assigneeIds.map(String)}
                onChange={(e) => setAssigneeIds(Array.from(e.target.selectedOptions, (o) => Number(o.value)))}
                disabled={!canCreate}
                aria-label="Assignees"
              >
                {projectMembers.map((row) => (
                  <option key={row.member_id} value={row.member_id}>
                    {row.member?.display_name ?? `Member #${row.member_id}`}
                    {row.member?.member_type === "ai" ? " (AI)" : ""}
                  </option>
                ))}
              </select>
            </div>

            <div className="mb-4">
              <label className="as-ticket-label" htmlFor="as-new-ticket-reporter">
                Reporter
              </label>
              <select
                id="as-new-ticket-reporter"
                className="form-select"
                value={reporterId}
                onChange={(e) => setReporterId(e.target.value)}
                disabled={!canCreate}
              >
                <option value="">— None —</option>
                {projectMembers.map((row) => (
                  <option key={row.member_id} value={row.member_id}>
                    {row.member?.display_name ?? `Member #${row.member_id}`}
                    {row.member?.member_type === "ai" ? " (AI)" : ""}
                  </option>
                ))}
              </select>
            </div>

            <div className="d-grid gap-2">
              <button type="submit" className="btn btn-primary btn-lg" disabled={!canCreate || submitting}>
                {submitting ? (
                  <>
                    <span className="spinner-border spinner-border-sm me-2" aria-hidden />
                    Creating…
                  </>
                ) : (
                  "Create ticket"
                )}
              </button>
              <button
                type="button"
                className="btn btn-outline-secondary"
                onClick={() => navigate(`/p/${projectId}/tickets`)}
                disabled={submitting}
              >
                Cancel
              </button>
            </div>
          </section>
        </aside>
      </form>
    </div>
  );
}
