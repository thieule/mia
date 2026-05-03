import { useMemo, useState } from "react";
import { DndContext, DragOverlay, PointerSensor, useDraggable, useDroppable, useSensor, useSensors } from "@dnd-kit/core";

const DROP_PREFIX = "kanban-col-";

/** Map UI column to API status when a card is dropped. */
export function columnToApiStatus(columnId) {
  if (columnId === "icebox") return "icebox_in_progress";
  if (columnId === "backlog") return "backlog_unstart";
  if (columnId === "current") return "current_unstart";
  if (columnId === "done") return "done";
  return "backlog_unstart";
}

/** Which Kanban column a story belongs to for display. */
export function storyKanbanColumn(story) {
  const st = story.status || "";
  if (st === "done") return "done";
  if (st.startsWith("backlog_")) return "backlog";
  if (st.startsWith("current_")) return "current";
  if (st.startsWith("icebox_")) return "icebox";
  // Legacy fallback for old rows.
  if (st === "backlog") return "backlog";
  if (st === "ready" || st === "in_progress" || st === "review") return "current";
  if (st === "icebox" || st === "cancelled") return "icebox";
  return "icebox";
}

const COLUMNS = [
  { id: "icebox", title: "Icebox", subtitle: "In-progress · Approved · Rejected · Feedback" },
  { id: "backlog", title: "Backlog", subtitle: "Unstart" },
  { id: "current", title: "Current", subtitle: "Unstart · Started · Review · Delivery" },
  { id: "done", title: "Done", subtitle: "Completed" },
];

function dropId(columnId) {
  return `${DROP_PREFIX}${columnId}`;
}

function parseDropId(id) {
  if (typeof id !== "string" || !id.startsWith(DROP_PREFIX)) return null;
  return id.slice(DROP_PREFIX.length);
}

function parseStoryId(activeId) {
  if (typeof activeId !== "string" || !activeId.startsWith("story-")) return null;
  const n = Number(activeId.slice(6));
  return Number.isFinite(n) ? n : null;
}

function assigneeIdsForCard(story) {
  if (Array.isArray(story.assignee_ids) && story.assignee_ids.length) return story.assignee_ids;
  if (story.assignee_id != null) return [story.assignee_id];
  return [];
}

function releaseGroupLabel(story, releaseNameById) {
  if (story.release_id == null) return "No milestone";
  const n = releaseNameById[story.release_id];
  if (n) return n;
  return `Release #${story.release_id}`;
}

const STATUS_LABELS = {
  icebox_in_progress: "in-progress",
  icebox_approved: "approved",
  icebox_rejected: "rejected",
  icebox_feedback: "feedback",
  backlog_unstart: "unstart",
  current_unstart: "unstart",
  current_started: "started",
  current_review: "review",
  current_delivery: "delivery",
  done: "done",
  // Legacy labels (for older rows not migrated yet).
  icebox: "in-progress",
  backlog: "unstart",
  ready: "unstart",
  in_progress: "started",
  review: "review",
  cancelled: "rejected",
};

function normalizeStoryStatus(status) {
  if (!status) return "icebox_in_progress";
  if (status === "icebox") return "icebox_in_progress";
  if (status === "backlog") return "backlog_unstart";
  if (status === "ready") return "current_unstart";
  if (status === "in_progress") return "current_started";
  if (status === "review") return "current_review";
  if (status === "cancelled") return "icebox_rejected";
  return status;
}

function quickActionsForStory(story) {
  const status = normalizeStoryStatus(story.status);
  const column = storyKanbanColumn(story);
  if (status.startsWith("icebox_")) {
    return [
      { status: "backlog_unstart", label: "Approve", className: "btn-outline-success" },
      { status: "icebox_rejected", label: "Reject", className: "btn-outline-danger" },
      { status: "icebox_feedback", label: "Feedback", className: "btn-outline-warning" },
    ];
  }
  if (column === "icebox") {
    return [
      { status: "backlog_unstart", label: "Approve", className: "btn-outline-success" },
      { status: "icebox_rejected", label: "Reject", className: "btn-outline-danger" },
      { status: "icebox_feedback", label: "Feedback", className: "btn-outline-warning" },
    ];
  }
  if (status === "backlog_unstart") {
    return [{ status: "current_unstart", label: "Start", className: "btn-primary" }];
  }
  if (column === "backlog") {
    return [{ status: "current_unstart", label: "Start", className: "btn-primary" }];
  }
  if (status === "current_unstart") {
    return [{ status: "current_started", label: "Start", className: "btn-outline-primary" }];
  }
  if (status === "current_started") {
    return [{ status: "current_review", label: "Review", className: "btn-outline-info" }];
  }
  if (status === "current_review") {
    return [{ status: "current_delivery", label: "Delivery", className: "btn-outline-warning" }];
  }
  if (status === "current_delivery") {
    return [{ status: "done", label: "Approved", className: "btn-success" }];
  }
  if (column === "current") {
    return [{ status: "current_started", label: "Start", className: "btn-outline-primary" }];
  }
  return [];
}

/**
 * Group stories by `release_id` (milestone) — for Current & Done columns.
 * Order: unassigned first, then by label (en locale).
 */
function groupStoriesByMilestone(stories, releaseNameById) {
  const byKey = new Map();
  for (const s of stories) {
    const k = s.release_id == null ? "none" : String(s.release_id);
    if (!byKey.has(k)) {
      const label = k === "none" ? "No milestone" : releaseGroupLabel(s, releaseNameById);
      byKey.set(k, { key: k, label, stories: [] });
    }
    byKey.get(k).stories.push(s);
  }
  const list = Array.from(byKey.values());
  list.sort((a, b) => {
    if (a.key === "none") return -1;
    if (b.key === "none") return 1;
    return a.label.localeCompare(b.label, "en");
  });
  return list;
}

function DraggableStoryCard({ story, onOpen, onQuickStatusChange, releaseNameById, memberNameById, hideReleaseBadge = false }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `story-${story.id}`,
    data: { story },
  });
  const style = {
    ...(transform ? { transform: `translate3d(${transform.x}px,${transform.y}px,0)` } : {}),
    borderColor: "var(--as-border, #e2e8f0)",
  };
  const normalizedStatus = normalizeStoryStatus(story.status);
  const actions = quickActionsForStory(story);
  const rname = story.release_id && releaseNameById ? releaseNameById[story.release_id] : null;
  const aidList = assigneeIdsForCard(story);
  const assigneeLine =
    aidList.length > 0
      ? aidList.map((id) => memberNameById[id] || `#${id}`).join(", ")
      : "";

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`kanban-card card border mb-2 ${isDragging ? "opacity-40 shadow" : "shadow-sm"}`}
    >
      <div className="card-body p-2 d-flex gap-2 align-items-start">
        <button
          type="button"
          className="btn btn-light btn-sm p-0 border kanban-drag-handle"
          style={{ width: 28, minHeight: 36 }}
          aria-label="Drag to move"
          {...listeners}
          {...attributes}
        >
          <i className="bi bi-grip-vertical text-muted" aria-hidden />
        </button>
        <div className="flex-grow-1 min-w-0">
          {story.story_key ? (
            <div className="small text-secondary text-truncate mb-0" title={story.story_key}>
              {story.story_key}
            </div>
          ) : null}
          <button type="button" className="btn btn-link text-start text-decoration-none p-0 fw-medium small w-100" onClick={() => onOpen(story.id)}>
            {story.title}
          </button>
          {actions.length ? (
            <div className="d-flex flex-wrap gap-1 mt-1">
              {actions.map((action) => (
                <button
                  key={action.status}
                  type="button"
                  className={`btn btn-sm kanban-action-btn ${action.className}`}
                  style={{ "--bs-btn-padding-y": ".05rem", "--bs-btn-padding-x": ".35rem", fontSize: ".67rem" }}
                  disabled={normalizedStatus === action.status}
                  onClick={() => onQuickStatusChange(story.id, action.status)}
                  title={`Set status: ${action.label}`}
                >
                  {action.label}
                </button>
              ))}
            </div>
          ) : null}
          {assigneeLine ? (
            <div className="small text-muted text-truncate mb-0" title={assigneeLine}>
              {assigneeLine}
            </div>
          ) : null}
          <div className="d-flex flex-wrap align-items-center gap-1">
            {rname && !hideReleaseBadge ? (
              <span className="badge rounded-pill bg-primary bg-opacity-10 text-primary border border-primary border-opacity-25 small" title="Release">
                {rname}
              </span>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function KanbanColumn({ column, stories, onOpenStory, onQuickStatusChange, releaseNameById, memberNameById, groupByMilestone = false }) {
  const { isOver, setNodeRef } = useDroppable({ id: dropId(column.id) });
  const groups = useMemo(
    () => (groupByMilestone ? groupStoriesByMilestone(stories, releaseNameById) : null),
    [stories, releaseNameById, groupByMilestone]
  );
  return (
    <div
      className={`kanban-column kanban-column--${column.id} flex-shrink-0 rounded-3 border ${isOver ? "kanban-column--drag-over" : ""}`}
      style={{
        background: "var(--kanban-bd-bg)",
        borderColor: "var(--kanban-border)",
      }}
    >
      <div
        className="px-3 py-2 rounded-top-3 kanban-column__hd"
        style={{
          background: "var(--kanban-hd-bg)",
          borderBottom: "1px solid var(--kanban-border)",
        }}
      >
        <div className="fw-semibold small" style={{ color: "var(--kanban-hd-text)" }}>
          {column.title}
        </div>
        <div style={{ fontSize: "0.7rem", color: "var(--kanban-hd-muted)" }}>
          {groupByMilestone ? "By release milestone — see below" : column.subtitle}
        </div>
        <span
          className="badge rounded-pill mt-1"
          style={{ background: "var(--kanban-count-bg)", color: "var(--kanban-count-text)" }}
        >
          {stories.length}
        </span>
      </div>
      <div ref={setNodeRef} className="kanban-column-scroll p-2 flex-grow-1 overflow-y-auto">
        {groupByMilestone && groups && groups.length > 0
          ? groups.map((g) => (
              <div key={g.key} className="kanban-milestone-group mb-3 pb-1">
                <div
                  className="d-flex align-items-center gap-1 mb-2 px-1 py-1 rounded-2"
                  style={{
                    background: "var(--as-milestone-hd-bg, rgba(0,0,0,0.04))",
                    borderLeft: "3px solid var(--as-milestone-border, #6366f1)",
                  }}
                >
                  <i className="bi bi-flag text-primary" style={{ fontSize: "0.8rem" }} aria-hidden />
                  <span className="small fw-semibold text-body text-truncate flex-grow-1" title={g.label}>
                    {g.label}
                  </span>
                  <span className="badge bg-secondary bg-opacity-25 text-secondary" style={{ fontSize: "0.65rem" }}>
                    {g.stories.length}
                  </span>
                </div>
                {g.stories.map((s) => (
                  <DraggableStoryCard
                    key={s.id}
                    story={s}
                    onOpen={onOpenStory}
                    onQuickStatusChange={onQuickStatusChange}
                    releaseNameById={releaseNameById}
                    memberNameById={memberNameById}
                    hideReleaseBadge
                  />
                ))}
              </div>
            ))
          : stories.map((s) => (
              <DraggableStoryCard
                key={s.id}
                story={s}
                onOpen={onOpenStory}
                onQuickStatusChange={onQuickStatusChange}
                releaseNameById={releaseNameById}
                memberNameById={memberNameById}
              />
            ))}
      </div>
    </div>
  );
}

export default function KanbanBoard({ stories, onMoveStory, onOpenStory, releaseNameById = {}, memberNameById = {} }) {
  const [activeStory, setActiveStory] = useState(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  const byColumn = useMemo(() => {
    const map = { icebox: [], backlog: [], current: [], done: [] };
    for (const s of stories) {
      const col = storyKanbanColumn(s);
      if (map[col]) map[col].push(s);
    }
    return map;
  }, [stories]);

  const handleDragStart = ({ active }) => {
    const sid = parseStoryId(active.id);
    setActiveStory(stories.find((x) => x.id === sid) || null);
  };

  const handleDragEnd = ({ active, over }) => {
    setActiveStory(null);
    if (!over) return;
    const sid = parseStoryId(active.id);
    const targetCol = parseDropId(over.id);
    if (sid === null || !targetCol) return;
    const story = stories.find((x) => x.id === sid);
    if (!story) return;
    if (storyKanbanColumn(story) === targetCol) return;
    onMoveStory(sid, columnToApiStatus(targetCol));
  };

  const handleDragCancel = () => setActiveStory(null);

  return (
    <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd} onDragCancel={handleDragCancel}>
      <div className="d-flex gap-3 overflow-x-auto pb-2 kanban-strip">
        {COLUMNS.map((col) => (
          <KanbanColumn
            key={col.id}
            column={col}
            stories={byColumn[col.id] || []}
            onOpenStory={onOpenStory}
            onQuickStatusChange={onMoveStory}
            releaseNameById={releaseNameById}
            memberNameById={memberNameById}
            groupByMilestone={col.id === "current" || col.id === "done"}
          />
        ))}
      </div>
      <DragOverlay dropAnimation={null}>
        {activeStory ? (
          <div className="card border-primary shadow kanban-card kanban-drag-preview">
            <div className="card-body p-2 small">
              <div className="fw-medium">{activeStory.title}</div>
            </div>
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}
