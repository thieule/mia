import { Component, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { io } from "socket.io-client";
import { apiDelete, apiGet, apiPatch, apiPost, clearAuth, getStoredUser } from "./api.js";
import KanbanBoard from "./KanbanBoard.jsx";
import MarkdownEditorField from "./MarkdownEditorField.jsx";
import {
  loadNotifications,
  makeNotification,
  MAX_NOTIFICATIONS,
  notificationIconClass,
  saveNotifications,
  textMentionsDisplayName,
} from "./notifications.js";

/** LLM đôi khi dùng ¶ thay cho xuống dòng — đưa về newline để remark không lỗi cấu trúc. */
function normalizeChatMarkdownSource(raw) {
  return String(raw || "")
    .replace(/\u00b6/g, "\n")
    .replace(/\r\n/g, "\n");
}

function formatChatMessageTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  try {
    return d.toLocaleTimeString();
  } catch {
    return "";
  }
}

/**
 * react-markdown có thể throw với một số chuỗi (bảng/list lỗi, ký tự lạ) — fallback plain text.
 */
class ChatMarkdownErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidUpdate(prevProps) {
    if (prevProps.source !== this.props.source) {
      this.setState({ hasError: false });
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <pre className="mb-0 small as-chat-md-fallback" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {this.props.source}
        </pre>
      );
    }
    return this.props.children;
  }
}

/** Markdown trong bubble chat — link mở tab mới; giữ @mention tách khỏi MD để highlight. */
const CHAT_MARKDOWN_COMPONENTS = {
  a: ({ node: _n, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
};

/**
 * Markdown (GFM) + highlight @mention giống bubble chat — tách tại token @ để không làm hỏng parser.
 * mentionIndex: Map từ mentionKey (lowercase) → display name (như commentMentionIndex / chat mentionIndex).
 */
function renderMarkdownWithMentions(content, mentionIndex) {
  const idxMap = mentionIndex instanceof Map ? mentionIndex : new Map();
  const normalized = normalizeChatMarkdownSource(content);
  const parts = normalized.split(/(@[^\s@]+)/g);
  return parts.map((p, idx) => {
    if (!p.startsWith("@")) {
      if (!p) return null;
      const md = normalizeChatMarkdownSource(p);
      return (
        <div key={idx} className="as-chat-md">
          <ChatMarkdownErrorBoundary source={md}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={CHAT_MARKDOWN_COMPONENTS}>
              {md}
            </ReactMarkdown>
          </ChatMarkdownErrorBoundary>
        </div>
      );
    }
    const key = p.slice(1).toLowerCase();
    const matched = idxMap.has(key);
    return (
      <span key={idx} className={matched ? "as-chat-mention" : ""}>
        {p}
      </span>
    );
  });
}

const STORY_STATUSES = [
  "icebox_in_progress",
  "icebox_approved",
  "icebox_rejected",
  "icebox_feedback",
  "backlog_unstart",
  "current_unstart",
  "current_started",
  "current_review",
  "current_delivery",
  "done",
];

const STORY_STATUS_LABELS = {
  icebox_in_progress: "Icebox / In progress",
  icebox_approved: "Icebox / Approved",
  icebox_rejected: "Icebox / Rejected",
  icebox_feedback: "Icebox / Feedback",
  backlog_unstart: "Backlog / Unstart",
  current_unstart: "Current / Unstart",
  current_started: "Current / Start",
  current_review: "Current / Review",
  current_delivery: "Current / Delivery",
  done: "Done",
  // Legacy fallback
  icebox: "Icebox",
  backlog: "Backlog",
  ready: "Current / Unstart",
  in_progress: "Current / Start",
  review: "Current / Review",
  cancelled: "Icebox / Rejected",
};

function storyStatusLabel(status) {
  if (!status) return "Unknown";
  return STORY_STATUS_LABELS[status] || status;
}

function mentionKeyFromName(name) {
  return String(name || "")
    .trim()
    .replace(/\s+/g, "")
    .toLowerCase();
}

/**
 * Display name lỗi kiểu "Mia mia-ba" (fallback catalog) → mention `@miamia-ba`.
 * Chuẩn hóa về token runtime `mia-ba`.
 */
function normalizeAgentMentionToken(raw) {
  let tl = String(raw || "")
    .trim()
    .toLowerCase();
  if (tl.startsWith("miamia-")) {
    tl = `mia-${tl.slice(7)}`;
  }
  return tl;
}

/**
 * agents.json (API Center) dùng id `mia-ba`; Agile hay nhập `agent_id` = `ai-ba`.
 * Chuẩn hóa để khớp một hàng trong GET /v1/agents.
 */
function matchAgentIdToCatalog(tokenLower, apiCenterAgents) {
  const agents = Array.isArray(apiCenterAgents) ? apiCenterAgents : [];
  const tl = normalizeAgentMentionToken(tokenLower);
  if (!tl) return null;
  let hit = agents.find((a) => String(a.id || "").toLowerCase() === tl);
  if (hit) return hit;
  if (tl.startsWith("ai-")) {
    hit = agents.find((a) => String(a.id || "").toLowerCase() === `mia-${tl.slice(3)}`);
    if (hit) return hit;
  }
  return null;
}

/** Chuẩn hóa để so `member.agent_id` (Agile: ai-ba) với id từ API Center (mia-ba). */
function canonicalRuntimeAgentId(id) {
  const s = String(id || "").trim().toLowerCase();
  if (!s) return "";
  if (s.startsWith("ai-")) return `mia-${s.slice(3)}`;
  return s;
}

function findProjectAiMemberForRuntimeAgent(projectMembers, runtimeAgentId) {
  const want = canonicalRuntimeAgentId(runtimeAgentId);
  if (!want) return null;
  for (const row of Array.isArray(projectMembers) ? projectMembers : []) {
    if (row?.member?.member_type !== "ai") continue;
    if (canonicalRuntimeAgentId(row.member?.agent_id) === want) return row;
  }
  return null;
}

/** Map selected_agent_id (API Center) → hàng member AI trong project (fallback catalog). */
function resolveAiMemberForAgentReply(projectMembers, runtimeAgentId, apiCenterAgents) {
  const raw = String(runtimeAgentId || "").trim();
  if (!raw) return null;
  let row = findProjectAiMemberForRuntimeAgent(projectMembers, raw);
  if (row?.member_id) return row;
  const catalog = matchAgentIdToCatalog(raw.toLowerCase(), apiCenterAgents);
  if (catalog?.id) {
    row = findProjectAiMemberForRuntimeAgent(projectMembers, catalog.id);
    if (row?.member_id) return row;
  }
  return null;
}

/**
 * DM private_user: SendMessageDto.userId phải là peer của sender (người khai báo trong resolveChannelKey).
 * Sidebar đặt room.userId = đối phương; khi AI gửi thì sender === đối phương đó → peer phải là viewer (myMemberId).
 */
function dmPeerUserIdForAgentSend(room, senderMemberId, viewerMemberId) {
  if (!room || room.targetKind !== "private_user") return room?.userId ?? undefined;
  const s = Number(senderMemberId || 0);
  const other = Number(room.userId || 0);
  const me = Number(viewerMemberId || 0);
  if (!s || !other || !me) return other || undefined;
  if (s === other) return me;
  if (s === me) return other;
  return other;
}

/** Gắn @token (không gồm @) tới agent trong catalog — id, tên agent, hoặc display_name member AI. */
function findAgentForMentionToken(token, apiCenterAgents, projectMembers) {
  const t = normalizeAgentMentionToken(token);
  if (!t) return null;
  const agents = Array.isArray(apiCenterAgents) ? apiCenterAgents : [];
  const byId = matchAgentIdToCatalog(t, agents);
  if (byId) return byId;
  const rawKey = String(token || "")
    .trim()
    .toLowerCase();
  const byAgentCatalogName = agents.find(
    (a) => mentionKeyFromName(a.name) === t || mentionKeyFromName(a.name) === rawKey
  );
  if (byAgentCatalogName) return byAgentCatalogName;
  for (const row of Array.isArray(projectMembers) ? projectMembers : []) {
    if (row?.member?.member_type !== "ai") continue;
    const mk = mentionKeyFromName(row.member?.display_name);
    if (mk !== t && mk !== rawKey) continue;
    const aid = String(row.member?.agent_id || "").trim();
    if (!aid) continue;
    return matchAgentIdToCatalog(aid.toLowerCase(), agents);
  }
  return null;
}

/** Ưu tiên mention theo thứ tự xuất hiện trong message. */
function firstResolvedMentionedAgent(mentionMatches, apiCenterAgents, projectMembers) {
  for (const m of mentionMatches) {
    const a = findAgentForMentionToken(m, apiCenterAgents, projectMembers);
    if (a) return a;
  }
  return null;
}

function escapeRegExp(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Các story_key có trong bảng stories hiện tại mà người dùng thực sự gõ/đính (word boundary). */
function findStoryKeysFromLoadedStories(text, projectStories) {
  const t = String(text || "");
  if (!t || !Array.isArray(projectStories) || !projectStories.length) return [];
  const found = [];
  for (const st of projectStories) {
    const k = st && st.story_key != null ? String(st.story_key).trim() : "";
    if (!k) continue;
    try {
      if (new RegExp(`\\b${escapeRegExp(k)}\\b`, "i").test(t)) found.push(k);
    } catch {
      if (t.includes(k)) found.push(k);
    }
  }
  return [...new Set(found)];
}

/**
 * Mẫu {project_slug}-{số} khi cần bắt trước khi / ngoài danh sách stories tải sẵn.
 * Chỉ bật khi có project slug thật từ API.
 */
function findStoryKeysByProjectSlugPattern(text, projectSlug) {
  const t = String(text || "");
  const slug = (projectSlug || "").trim();
  if (!t || !slug) return [];
  const out = new Set();
  const re = new RegExp(`\\b${escapeRegExp(slug)}-(\\d+)\\b`, "gi");
  let m;
  while ((m = re.exec(t)) !== null) {
    out.add(`${slug}-${m[1]}`);
  }
  return [...out];
}

const RELEASE_STATUSES = ["planning", "active", "released", "archived"];
const CHAT_REACTIONS = [
  { type: "seen", label: "Seen", icon: "bi-eye" },
  { type: "like", label: "Like", icon: "bi-hand-thumbs-up" },
  { type: "love", label: "Love", icon: "bi-heart" },
  { type: "doing", label: "Doing", icon: "bi-hourglass-split" },
  { type: "wow", label: "Wow", icon: "bi-emoji-surprise" },
  { type: "angry", label: "Angry", icon: "bi-emoji-angry" },
  { type: "happy", label: "Happy", icon: "bi-emoji-smile" },
];
const CHAT_API_BASE = import.meta.env.DEV ? "/agile-chat-api/api" : "http://127.0.0.1:9130/api";
const CHAT_WS_NAMESPACE = import.meta.env.DEV ? "/ws/chat" : "http://127.0.0.1:9130/ws/chat";

/** Socket.IO room cho listener comment story (không là chat channel DB). */
function storyCommentsChannelId(projectId, storyId) {
  return `${projectId}_story_${storyId}`;
}

/** Chờ trước khi hiện seen / doing / typing — tránh nhấp nháy khi agent phản hồi cực nhanh. */
const AGENT_CHAT_UI_LEAD_MS = 520;
/** Sau khi đã hiện trạng thái xử lý, giữ tối thiểu bấy lâu trước khi gỡ doing / tắt typing. */
const AGENT_CHAT_MIN_PROCESSING_MS = 920;

/** Typing indicator qua REST — `ChatGateway.emitTyping` broadcast tới cả người gửi (khác với socket `client.to`). */
async function postChatTypingHttp({ projectId, room, senderUserId, senderName, isTyping, viewerMemberId }) {
  const dmPeer =
    room?.targetKind === "private_user"
      ? dmPeerUserIdForAgentSend(room, senderUserId, viewerMemberId)
      : undefined;
  const body = {
    projectId,
    targetKind: room.targetKind,
    channelName: room.channelName || undefined,
    ...(room.targetKind === "private_user" && dmPeer != null ? { userId: dmPeer } : {}),
    senderUserId: Number(senderUserId),
    ...(senderName ? { senderName: String(senderName).trim() } : {}),
    isTyping: isTyping !== false,
  };
  const res = await fetch(`${CHAT_API_BASE}/chat/typing`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const er = await res.json().catch(() => ({}));
    throw new Error(er?.message || er?.error || `typing HTTP ${res.status}`);
  }
}

/** Reaction trên tin nhắn user — actor là member AI (`actorUserId`), không được trùng sender tin (chat-service). */
async function postAgentMessageReaction({
  projectId,
  room,
  actorUserId,
  viewerMemberId,
  messageId,
  reaction,
  action = "add",
}) {
  const dmPeer =
    room?.targetKind === "private_user"
      ? dmPeerUserIdForAgentSend(room, actorUserId, viewerMemberId)
      : undefined;
  const body = {
    projectId,
    targetKind: room.targetKind,
    channelName: room.channelName || undefined,
    ...(room.targetKind === "private_user" && dmPeer != null ? { userId: dmPeer } : {}),
    actorUserId: Number(actorUserId),
    reaction,
    action,
  };
  const res = await fetch(`${CHAT_API_BASE}/chat/messages/${encodeURIComponent(String(messageId))}/reactions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const er = await res.json().catch(() => ({}));
    throw new Error(er?.message || er?.error || `reaction HTTP ${res.status}`);
  }
}

/** Log chat (API Center WS, dispatch): không dùng console.debug — DevTools hay ẩn mức đó. */
function agileChatDebugEnabled() {
  try {
    if (typeof window !== "undefined" && window.localStorage?.getItem("agile_chat_debug") === "1") return true;
  } catch {
    /* ignore */
  }
  return (
    import.meta.env.DEV ||
    String(import.meta.env.VITE_AGILE_CHAT_DEBUG || "").toLowerCase() === "true"
  );
}
function chatDebug(...args) {
  if (!agileChatDebugEnabled()) return;
  console.info("[agile-chat]", ...args);
}

/** Hub đôi khi trả `chat_ws` thiếu scheme — WebSocket bắt buộc ws:// hoặc wss:// */
function normalizeApiCenterWsUrl(raw) {
  const s = String(raw || "").trim();
  if (!s) return "";
  if (/^wss?:\/\//i.test(s)) return s;
  if (/^https:\/\//i.test(s)) return `wss://${s.slice("https://".length)}`;
  if (/^http:\/\//i.test(s)) return `ws://${s.slice("http://".length)}`;
  return `ws://${s.replace(/^\/+/, "")}`;
}

function releaseIsoYmd(iso) {
  if (iso == null || iso === "") return "";
  return String(iso).slice(0, 10);
}

function localYmdToIsoStart(ymd) {
  if (!ymd) return null;
  return `${ymd}T00:00:00`;
}
function localYmdToIsoEnd(ymd) {
  if (!ymd) return null;
  return `${ymd}T23:59:59.999`;
}

function formatReleasePeriod(r) {
  if (!r?.starts_at) return "—";
  const a = releaseIsoYmd(r.starts_at);
  const b = releaseIsoYmd(r.ends_at);
  if (!r.ends_at || a === b) return a;
  return `${a} → ${b}`;
}

/** Workspace tabs — project list lives in the top hub panel. */
const TABS = {
  board: { id: "board", label: "Board", icon: "bi-columns-gap" },
  team: { id: "team", label: "Team", icon: "bi-people" },
  masterData: { id: "master-data", label: "Master data", icon: "bi-diagram-3" },
  chat: { id: "chat", label: "Chat", icon: "bi-chat-dots" },
  releases: { id: "releases", label: "Releases", icon: "bi-rocket-takeoff" },
  settings: { id: "settings", label: "Settings", icon: "bi-gear" },
};

/** URL sync: `/`, `/team`, `/master-data`, `/p/:id/board|team|chat|releases|settings`, `/p/:id/story/:storyId`. */
function parseWorkspacePath(pathname) {
  const p = (pathname || "/").replace(/\/+$/, "") || "/";
  const sm = p.match(/^\/p\/(\d+)\/story\/(\d+)$/);
  if (sm) return { projectId: Number(sm[1]), tab: "story", storyId: Number(sm[2]) };
  const m = p.match(/^\/p\/(\d+)\/(board|team|chat|releases|settings)$/);
  if (m) return { projectId: Number(m[1]), tab: m[2] };
  if (p === "/team") return { projectId: null, tab: "team" };
  if (p === "/master-data") return { projectId: null, tab: "master-data" };
  if (p === "/") return { projectId: null, tab: "board" };
  return null;
}

function StoryDetailBody({
  storyDetail,
  statusEvents,
  comments,
  projectMembers,
  releases,
  cmBody,
  setCmBody,
  onPatchStoryStatus,
  onPatchStoryDetails,
  onPatchStoryRelease,
  onPatchStoryAssignees,
  onPostComment,
  onPatchComment,
  onDeleteComment,
}) {
  const me = getStoredUser();
  const onProject = me?.member_id != null && projectMembers.some((row) => row.member_id === me.member_id);
  const [editingCommentId, setEditingCommentId] = useState(null);
  const [editDraft, setEditDraft] = useState("");
  const [editingStoryMeta, setEditingStoryMeta] = useState(false);
  const [storyTitleDraft, setStoryTitleDraft] = useState("");
  const [storyDescDraft, setStoryDescDraft] = useState("");
  const commentMentionMembers = useMemo(
    () =>
      (Array.isArray(projectMembers) ? projectMembers : [])
        .filter((row) => row && row.member_id != null)
        .map((row) => ({
          id: row.member_id,
          name: row.member?.display_name || `Member #${row.member_id}`,
        })),
    [projectMembers]
  );
  const commentMentionIndex = useMemo(() => {
    const map = new Map();
    for (const m of commentMentionMembers) {
      map.set(mentionKeyFromName(m.name), m.name);
    }
    return map;
  }, [commentMentionMembers]);
  const createCommentMentionSuggestions = useMemo(() => {
    const m = cmBody.match(/(?:^|\s)@([^\s@]*)$/);
    if (!m) return [];
    const q = (m[1] || "").toLowerCase();
    return commentMentionMembers.filter((x) => mentionKeyFromName(x.name).includes(q)).slice(0, 6);
  }, [cmBody, commentMentionMembers]);
  const editCommentMentionSuggestions = useMemo(() => {
    const m = editDraft.match(/(?:^|\s)@([^\s@]*)$/);
    if (!m) return [];
    const q = (m[1] || "").toLowerCase();
    return commentMentionMembers.filter((x) => mentionKeyFromName(x.name).includes(q)).slice(0, 6);
  }, [editDraft, commentMentionMembers]);
  const renderCommentContent = useCallback(
    (content) => renderMarkdownWithMentions(content, commentMentionIndex),
    [commentMentionIndex]
  );
  const onPickCommentMention = useCallback((displayName, mode) => {
    const mentionToken = `@${mentionKeyFromName(displayName)}`;
    if (mode === "edit") {
      setEditDraft((prev) => prev.replace(/(?:^|\s)@([^\s@]*)$/, (all) => all.replace(/@([^\s@]*)$/, `${mentionToken} `)));
      return;
    }
    setCmBody((prev) => prev.replace(/(?:^|\s)@([^\s@]*)$/, (all) => all.replace(/@([^\s@]*)$/, `${mentionToken} `)));
  }, [setCmBody]);

  const startStoryMetaEdit = () => {
    setStoryTitleDraft(storyDetail.title);
    setStoryDescDraft(storyDetail.description ?? "");
    setEditingStoryMeta(true);
  };

  const cancelStoryMetaEdit = () => {
    setEditingStoryMeta(false);
    setStoryTitleDraft("");
    setStoryDescDraft("");
  };

  const saveStoryMeta = async (e) => {
    e.preventDefault();
    const t = storyTitleDraft.trim();
    if (!t) return;
    const d = storyDescDraft.trim();
    await onPatchStoryDetails(storyDetail.id, {
      title: t,
      description: d.length ? d : null,
    });
    cancelStoryMetaEdit();
  };

  useEffect(() => {
    setEditingStoryMeta(false);
    setStoryTitleDraft("");
    setStoryDescDraft("");
  }, [storyDetail.id]);

  const startEdit = (c) => {
    setEditingCommentId(c.id);
    setEditDraft(c.body);
  };

  const cancelEdit = () => {
    setEditingCommentId(null);
    setEditDraft("");
  };

  const saveEdit = async (e) => {
    e.preventDefault();
    if (!editingCommentId || !editDraft.trim()) return;
    await onPatchComment(editingCommentId, editDraft.trim());
    cancelEdit();
  };

  return (
    <>
      <div className="d-flex align-items-start justify-content-between gap-2 mb-3">
        {editingStoryMeta ? (
          <form className="flex-grow-1 min-w-0" onSubmit={saveStoryMeta}>
            <label className="form-label small text-secondary mb-1" htmlFor="as-story-edit-title">
              Title
            </label>
            <input
              id="as-story-edit-title"
              className="form-control mb-2"
              value={storyTitleDraft}
              onChange={(e) => setStoryTitleDraft(e.target.value)}
              maxLength={500}
              required
            />
            <label className="form-label small text-secondary mb-1" htmlFor="as-story-edit-desc">
              Description
            </label>
            <MarkdownEditorField
              className="mb-2"
              value={storyDescDraft}
              onChange={setStoryDescDraft}
              height={220}
              placeholder="Optional"
              textareaProps={{ id: "as-story-edit-desc" }}
            />
            <div className="d-flex gap-2">
              <button className="btn btn-primary btn-sm" type="submit" disabled={!storyTitleDraft.trim()}>
                Save
              </button>
              <button className="btn btn-outline-secondary btn-sm" type="button" onClick={cancelStoryMetaEdit}>
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <>
            <div className="flex-grow-1 min-w-0">
              <h2 className="h5 mb-2">{storyDetail.title}</h2>
              {storyDetail.description ? (
                <div className="as-story-body as-story-desc-md mb-0">{renderMarkdownWithMentions(storyDetail.description, commentMentionIndex)}</div>
              ) : (
                <p className="small text-secondary fst-italic mb-0">No description.</p>
              )}
            </div>
            {onProject ? (
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm p-1 lh-1 flex-shrink-0"
                onClick={startStoryMetaEdit}
                title="Edit title and description"
                aria-label="Edit title and description"
              >
                <i className="bi bi-pencil" aria-hidden />
              </button>
            ) : null}
          </>
        )}
      </div>
      <div className="mb-3">
        <label className="form-label small text-secondary mb-1">Status</label>
        <select
          className="form-select form-select-sm"
          value={storyDetail.status}
          onChange={(e) => onPatchStoryStatus(storyDetail.id, e.target.value)}
        >
          {STORY_STATUSES.map((x) => (
            <option key={x} value={x}>
              {x}
            </option>
          ))}
        </select>
      </div>
      <div className="mb-3">
        <label className="form-label small text-secondary mb-1">Status activity</label>
        <div className="border rounded-2 p-2 small bg-light-subtle">
          {Array.isArray(statusEvents) && statusEvents.length ? (
            <ul className="list-unstyled mb-0">
              {statusEvents.map((ev) => (
                <li key={ev.id} className="mb-1">
                  <strong>{ev.actor?.display_name || `Member #${ev.actor_member_id}`}</strong>
                  <span className="text-secondary">: </span>
                  <span>{storyStatusLabel(ev.from_status)}</span>
                  <span className="text-secondary">{" -> "}</span>
                  <span>{storyStatusLabel(ev.to_status)}</span>
                  <span className="text-secondary"> · {new Date(ev.created_at).toLocaleString()}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-secondary">No status activity yet.</div>
          )}
        </div>
      </div>
      <div className="mb-3">
        <label className="form-label small text-secondary mb-1">Release</label>
        {onProject ? (
          <select
            className="form-select form-select-sm"
            value={storyDetail.release_id != null ? String(storyDetail.release_id) : ""}
            onChange={(e) => {
              const v = e.target.value;
              onPatchStoryRelease(storyDetail.id, v === "" ? null : Number(v));
            }}
          >
            <option value="">— None —</option>
            {releases.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
                {r.status && r.status !== "planning" ? ` · ${r.status}` : ""}
              </option>
            ))}
          </select>
        ) : (
          <p className="small mb-0 text-secondary">
            {storyDetail.release_id != null
              ? releases.find((x) => x.id === storyDetail.release_id)?.name ?? `Release #${storyDetail.release_id}`
              : "—"}
          </p>
        )}
        {releases.length === 0 && onProject ? (
          <div className="form-text">
            Create a release in the <strong>Releases</strong> tab on the left, then assign it here.
          </div>
        ) : null}
        {!onProject && getStoredUser() ? (
          <div className="form-text text-warning">
            Add yourself in <strong>Team</strong> for this project to change release, assignees, and comments.
          </div>
        ) : null}
      </div>
      <div className="mb-3">
        <label className="form-label small text-secondary mb-1">Assignees</label>
        {onProject ? (
          <select
            className="form-select form-select-sm"
            multiple
            size={Math.max(2, Math.min(8, projectMembers.length))}
            value={(() => {
              const ids = Array.isArray(storyDetail.assignee_ids) ? storyDetail.assignee_ids : [];
              const v = ids.length
                ? ids
                : storyDetail.assignee_id != null
                  ? [storyDetail.assignee_id]
                  : [];
              return v.map(String);
            })()}
            onChange={(e) => {
              const next = Array.from(e.target.selectedOptions, (o) => Number(o.value));
              onPatchStoryAssignees(storyDetail.id, next);
            }}
            aria-label="Assignees"
          >
            {projectMembers.map((row) => (
              <option key={row.member_id} value={row.member_id}>
                {row.member?.display_name ?? `Member #${row.member_id}`}
                {row.member?.member_type === "ai" ? " (AI)" : ""}
              </option>
            ))}
          </select>
        ) : (
          <p className="small mb-0 text-secondary">
            {(() => {
              const ids = Array.isArray(storyDetail.assignee_ids) ? storyDetail.assignee_ids : [];
              const list = ids.length
                ? ids
                : storyDetail.assignee_id != null
                  ? [storyDetail.assignee_id]
                  : [];
              if (!list.length) return "—";
              return list
                .map((id) => projectMembers.find((r) => r.member_id === id)?.member?.display_name ?? `Member #${id}`)
                .join(", ");
            })()}
          </p>
        )}
        {onProject ? (
          <div className="form-text">Hold Cmd/Ctrl to select more than one member.</div>
        ) : null}
      </div>
      <h3 className="h6 text-secondary border-top pt-3 mb-3">Comments</h3>
      <ul className="list-unstyled small mb-4">
        {comments.map((c) => {
          const isAuthor = me?.member_id != null && c.author_member_id === me.member_id;
          const edited =
            c.updated_at &&
            c.created_at &&
            new Date(c.updated_at).getTime() - new Date(c.created_at).getTime() > 1500;
          return (
            <li key={c.id} className="mb-3 pb-3 border-bottom">
              <div className="text-secondary mb-1 d-flex flex-wrap align-items-center justify-content-between gap-2">
                <div>
                  <strong className="text-dark">{c.author?.display_name ?? `Member #${c.author_member_id}`}</strong>
                  {c.author?.member_type === "ai" ? <span className="badge bg-secondary ms-1 small">AI</span> : null}
                  <span className="text-muted"> · {new Date(c.created_at).toLocaleString()}</span>
                  {edited ? <span className="text-muted fst-italic ms-1">(edited)</span> : null}
                </div>
                {isAuthor && editingCommentId !== c.id ? (
                  <div className="d-flex gap-1 flex-shrink-0">
                    <button
                      type="button"
                      className="btn btn-outline-secondary btn-sm p-1 lh-1"
                      onClick={() => startEdit(c)}
                      title="Edit comment"
                      aria-label="Edit comment"
                    >
                      <i className="bi bi-pencil" aria-hidden />
                    </button>
                    <button
                      type="button"
                      className="btn btn-outline-danger btn-sm p-1 lh-1"
                      onClick={() => onDeleteComment(c.id)}
                      title="Delete comment"
                      aria-label="Delete comment"
                    >
                      <i className="bi bi-trash" aria-hidden />
                    </button>
                  </div>
                ) : null}
              </div>
              {editingCommentId === c.id ? (
                <form className="vstack gap-2 mt-1" onSubmit={saveEdit}>
                  {editCommentMentionSuggestions.length > 0 ? (
                    <div className="as-chat-mention-suggest mb-1">
                      {editCommentMentionSuggestions.map((m) => (
                        <button key={m.id} type="button" className="btn btn-sm btn-outline-secondary" onClick={() => onPickCommentMention(m.name, "edit")}>
                          @{mentionKeyFromName(m.name)}
                        </button>
                      ))}
                    </div>
                  ) : null}
                  <MarkdownEditorField
                    value={editDraft}
                    onChange={setEditDraft}
                    height={160}
                    textareaProps={{ required: true }}
                  />
                  <div className="d-flex gap-2">
                    <button className="btn btn-primary btn-sm" type="submit" disabled={!editDraft.trim()}>
                      Save
                    </button>
                    <button className="btn btn-outline-secondary btn-sm" type="button" onClick={cancelEdit}>
                      Cancel
                    </button>
                  </div>
                </form>
              ) : (
                <div className="mt-1 as-comment-md">{renderCommentContent(c.body)}</div>
              )}
            </li>
          );
        })}
      </ul>
      <form onSubmit={onPostComment} className="vstack gap-2">
        {me ? (
          <p className="small text-secondary mb-0">
            Posting as <strong>{me.display_name}</strong>.
            {!onProject ? (
              <span className="d-block text-warning mt-1">You are not on this project — add yourself in Team before commenting.</span>
            ) : null}
          </p>
        ) : null}
        {createCommentMentionSuggestions.length > 0 ? (
          <div className="as-chat-mention-suggest mb-1">
            {createCommentMentionSuggestions.map((m) => (
              <button key={m.id} type="button" className="btn btn-sm btn-outline-secondary" onClick={() => onPickCommentMention(m.name, "create")}>
                @{mentionKeyFromName(m.name)}
              </button>
            ))}
          </div>
        ) : null}
        <MarkdownEditorField value={cmBody} onChange={setCmBody} height={170} placeholder="Comment" textareaProps={{ required: true }} />
        <button
          className="btn btn-primary btn-sm"
          type="submit"
          disabled={!cmBody.trim() || (me != null && !onProject)}
          title={me != null && !onProject ? "Join this project in Team to comment" : undefined}
        >
          Post comment
        </button>
      </form>
    </>
  );
}

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [err, setErr] = useState(null);
  const [showProjectsHub, setShowProjectsHub] = useState(false);
  const [showCreateStory, setShowCreateStory] = useState(false);
  const [projects, setProjects] = useState([]);
  const [members, setMembers] = useState([]);
  const [projectId, setProjectId] = useState(null);
  const [projectMembers, setProjectMembers] = useState([]);
  const [stories, setStories] = useState([]);
  const [releases, setReleases] = useState([]);
  const [workflowTemplates, setWorkflowTemplates] = useState([]);
  const [storyId, setStoryId] = useState(null);
  const [storyDetail, setStoryDetail] = useState(null);
  const [comments, setComments] = useState([]);
  const [storyStatusEventsById, setStoryStatusEventsById] = useState({});

  const [slug, setSlug] = useState("");
  const [pname, setPname] = useState("");
  const [wsRef, setWsRef] = useState("");
  const [mType, setMType] = useState("human");
  const [mName, setMName] = useState("");
  const [mAgent, setMAgent] = useState("");
  const [addMemId, setAddMemId] = useState("");
  const [addRole, setAddRole] = useState("member");
  const [stTitle, setStTitle] = useState("");
  const [stDesc, setStDesc] = useState("");
  const [stStatus, setStStatus] = useState("icebox_in_progress");
  const [stReleaseId, setStReleaseId] = useState("");
  const [stAssigneeIds, setStAssigneeIds] = useState([]);
  const [newReleaseName, setNewReleaseName] = useState("");
  const [newRelDesc, setNewRelDesc] = useState("");
  const [newRelStatus, setNewRelStatus] = useState("planning");
  const [newRelDateMode, setNewRelDateMode] = useState("none");
  const [newRelDay, setNewRelDay] = useState("");
  const [newRelStart, setNewRelStart] = useState("");
  const [newRelEnd, setNewRelEnd] = useState("");
  const [wfName, setWfName] = useState("");
  const [wfDesc, setWfDesc] = useState("");

  const [editingReleaseId, setEditingReleaseId] = useState(null);
  const [editName, setEditName] = useState("");
  const [editStatus, setEditStatus] = useState("planning");
  const [editDesc, setEditDesc] = useState("");
  const [editDateMode, setEditDateMode] = useState("none");
  const [editDay, setEditDay] = useState("");
  const [editStart, setEditStart] = useState("");
  const [editEnd, setEditEnd] = useState("");
  const [cmBody, setCmBody] = useState("");
  const [activeChatId, setActiveChatId] = useState("general");
  const [chatInput, setChatInput] = useState("");
  const [chatMessagesByChannel, setChatMessagesByChannel] = useState({});
  const [chatConnected, setChatConnected] = useState(false);
  const [typingByChannel, setTypingByChannel] = useState({});

  const [notifications, setNotifications] = useState(() => loadNotifications());
  const [showNotifPanel, setShowNotifPanel] = useState(false);
  const notifDropdownRef = useRef(null);
  const lastStoriesPollRef = useRef(null);
  const commentsSeenByStoryRef = useRef(new Map());
  const chatSocketRef = useRef(null);
  const chatMessagesScrollRef = useRef(null);
  const projectIdRef = useRef(projectId);
  const storyIdRef = useRef(storyId);
  const apiCenterAgentWsRef = useRef(null);
  const chatTypingStopTimerRef = useRef(null);
  const chatTypingPurgeTimerRef = useRef(null);
  /** Agent đang trả lời: POST /chat/typing + renew (TTL UI ~3.5s). */
  const agentTypingIntervalRef = useRef(null);
  const agentTypingSafetyTimerRef = useRef(null);
  const agentTypingPayloadRef = useRef(null);
  const agentTypingTraceRef = useRef(null);
  /** Tin user vừa gửi để agent gỡ reaction `doing` khi xong (giữ `seen`). */
  const agentReactCtxRef = useRef(null);
  const agentUiLeadTimerRef = useRef(null);
  const agentProcessingShownAtRef = useRef(null);
  const agentStopMinDelayTimerRef = useRef(null);
  const stopAgentTypingRef = useRef(() => {});
  const me = getStoredUser();

  useEffect(() => {
    projectIdRef.current = projectId;
  }, [projectId]);
  useEffect(() => {
    storyIdRef.current = storyId;
  }, [storyId]);

  const [projWorkspaceRef, setProjWorkspaceRef] = useState("");
  const [projGhRepo, setProjGhRepo] = useState("");
  const [projGhBranch, setProjGhBranch] = useState("");
  const [projGhToken, setProjGhToken] = useState("");
  const [projClearGhToken, setProjClearGhToken] = useState(false);
  const [projDocsPath, setProjDocsPath] = useState("");
  const [projNotes, setProjNotes] = useState("");
  const [projSlackChannel, setProjSlackChannel] = useState("");
  const [projSlackWebhook, setProjSlackWebhook] = useState("");
  const [projClearSlackWebhook, setProjClearSlackWebhook] = useState(false);
  const [projDiscordLabel, setProjDiscordLabel] = useState("");
  const [projDiscordWebhook, setProjDiscordWebhook] = useState("");
  const [projClearDiscordWebhook, setProjClearDiscordWebhook] = useState(false);
  const [projAiWqUrl, setProjAiWqUrl] = useState("");
  const [projAiWqSecret, setProjAiWqSecret] = useState("");
  const [projAiWqAgentId, setProjAiWqAgentId] = useState("");
  const [projWorkflowTemplateId, setProjWorkflowTemplateId] = useState("");
  const [projStorageOverview, setProjStorageOverview] = useState("");
  const [apiCenterEndpoint, setApiCenterEndpoint] = useState("");
  const [apiCenterSecret, setApiCenterSecret] = useState("");
  const [apiCenterConnected, setApiCenterConnected] = useState(false);
  const [apiCenterMcpUrl, setApiCenterMcpUrl] = useState("");
  const [apiCenterHasMcpKey, setApiCenterHasMcpKey] = useState(false);
  const [apiCenterMcpMasked, setApiCenterMcpMasked] = useState("");
  const [apiCenterChatWsUrl, setApiCenterChatWsUrl] = useState("");
  /** WebSocket tới API Center /ws/agent-chat (reply realtime); khác Socket.IO chat-service. */
  const [apiCenterAgentWsReady, setApiCenterAgentWsReady] = useState(false);
  const [apiCenterAgents, setApiCenterAgents] = useState([]);
  const [selectedApiAgentId, setSelectedApiAgentId] = useState("");
  const [projClearAiWqUrl, setProjClearAiWqUrl] = useState(false);
  const [projClearAiWqSecret, setProjClearAiWqSecret] = useState(false);
  const [settingsSaved, setSettingsSaved] = useState(false);

  const workspace = parseWorkspacePath(location.pathname);
  const isStoryPage = workspace?.tab === "story";
  const mainTab =
    workspace && ["board", "team", "master-data", "chat", "releases", "settings"].includes(workspace.tab) ? workspace.tab : "board";

  const refreshProjects = useCallback(async () => {
    setErr(null);
    const list = await apiGet("/projects");
    setProjects(list);
  }, []);

  const refreshMembers = useCallback(async () => {
    setErr(null);
    const list = await apiGet("/members");
    setMembers(list);
  }, []);

  const refreshWorkflowTemplates = useCallback(async () => {
    setErr(null);
    const list = await apiGet("/workflow-templates");
    setWorkflowTemplates(Array.isArray(list) ? list : []);
  }, []);

  const refreshApiCenterStatus = useCallback(async () => {
    const st = await apiGet("/integrations/api-center/status");
    setApiCenterEndpoint(st?.endpoint || "");
    setApiCenterConnected(Boolean(st?.connected));
    setApiCenterHasMcpKey(Boolean(st?.has_mcp_api_key));
    setApiCenterMcpMasked(st?.mcp_api_key_masked || "");
    setApiCenterChatWsUrl(normalizeApiCenterWsUrl(String(st?.chat_ws_url || st?.endpoints?.chat_ws || "").trim()));
    setApiCenterMcpUrl((prev) => prev || `${window.location.origin}/mcp`);
  }, []);

  const refreshApiCenterAgents = useCallback(async () => {
    if (!apiCenterConnected) {
      setApiCenterAgents([]);
      return;
    }
    const rows = await apiGet("/integrations/api-center/agents");
    setApiCenterAgents(Array.isArray(rows) ? rows : []);
  }, [apiCenterConnected]);

  const loadProject = useCallback(async (pid, { preserveStory = false } = {}) => {
    setErr(null);
    if (!preserveStory) {
      setShowCreateStory(false);
      setStoryId(null);
      setStoryDetail(null);
      setComments([]);
    }
    setProjectId(pid);
    const [pm, st, detail, rel] = await Promise.all([
      apiGet(`/projects/${pid}/members`),
      apiGet(`/projects/${pid}/stories`),
      apiGet(`/projects/${pid}`),
      apiGet(`/projects/${pid}/releases`),
    ]);
    setProjectMembers(pm);
    setStories(st);
    setReleases(Array.isArray(rel) ? rel : []);
    lastStoriesPollRef.current = st.map((x) => ({
      id: x.id,
      updated_at: String(x.updated_at),
      title: x.title,
    }));
    setProjects((prev) => {
      const i = prev.findIndex((x) => x.id === detail.id);
      if (i === -1) return [detail, ...prev];
      const next = [...prev];
      next[i] = detail;
      return next;
    });
  }, []);

  const loadStory = useCallback(
    async (sid) => {
      setErr(null);
      setShowCreateStory(false);
      setStoryId(sid);
      const s = await apiGet(`/stories/${sid}`);
      const [c, rel, pm, statusEvents] = await Promise.all([
        apiGet(`/stories/${sid}/comments`),
        apiGet(`/projects/${s.project_id}/releases`),
        apiGet(`/projects/${s.project_id}/members`),
        apiGet(`/stories/${sid}/status-events`),
      ]);
      setReleases(Array.isArray(rel) ? rel : []);
      setProjectMembers(Array.isArray(pm) ? pm : []);
      setStoryStatusEventsById((prev) => ({ ...prev, [sid]: Array.isArray(statusEvents) ? statusEvents : [] }));
      const me = getStoredUser();
      const seen = commentsSeenByStoryRef.current.get(sid);
      const link = `/p/${s.project_id}/story/${s.id}`;
      if (seen == null) {
        commentsSeenByStoryRef.current.set(sid, new Set(c.map((x) => x.id)));
      } else {
        const rows = [];
        for (const com of c) {
          if (seen.has(com.id)) continue;
          const isSelf = me?.member_id != null && com.author_member_id === me.member_id;
          const mentioned = textMentionsDisplayName(com.body, me?.display_name);
          if (mentioned) {
            rows.push(
              makeNotification({
                type: "mention",
                title: "You were mentioned",
                body: `${com.author?.display_name ?? "Someone"} on “${s.title}”`,
                link,
              })
            );
          } else if (!isSelf) {
            rows.push(
              makeNotification({
                type: "comment",
                title: "New comment",
                body: `On “${s.title}”`,
                link,
              })
            );
          }
        }
        if (rows.length) {
          setNotifications((prev) => {
            const next = [...rows, ...prev].slice(0, MAX_NOTIFICATIONS);
            saveNotifications(next);
            return next;
          });
        }
        commentsSeenByStoryRef.current.set(sid, new Set(c.map((x) => x.id)));
      }
      setStoryDetail(s);
      setComments(c);
    },
    []
  );

  const closeStoryDrawer = useCallback(() => {
    setStoryId(null);
    setStoryDetail(null);
    setComments([]);
  }, []);

  const closeProjectsHub = useCallback(() => setShowProjectsHub(false), []);
  const closeMasterDataHub = useCallback(() => {
    if (projectId) navigate(`/p/${projectId}/board`);
    else navigate("/");
  }, [navigate, projectId]);

  const closeCreateStory = useCallback(() => setShowCreateStory(false), []);

  const pushNotif = useCallback((opts) => {
    setNotifications((prev) => {
      const row = makeNotification(opts);
      const next = [row, ...prev].slice(0, MAX_NOTIFICATIONS);
      saveNotifications(next);
      return next;
    });
  }, []);

  const syncStoriesFromServer = useCallback(async () => {
    if (!projectId) return;
    try {
      const list = await apiGet(`/projects/${projectId}/stories`);
      const slim = (arr) => arr.map((x) => ({ id: x.id, updated_at: String(x.updated_at), title: x.title }));
      const snapshot = lastStoriesPollRef.current;
      if (snapshot === null) {
        lastStoriesPollRef.current = slim(list);
        setStories(list);
        return;
      }
      const prevMap = new Map(snapshot.map((x) => [x.id, x.updated_at]));
      for (const s of list) {
        const u = String(s.updated_at);
        const old = prevMap.get(s.id);
        if (old === undefined) {
          pushNotif({
            type: "story",
            title: "New story",
            body: s.title,
            link: `/p/${projectId}/story/${s.id}`,
          });
        } else if (old !== u) {
          pushNotif({
            type: "story",
            title: "Story updated",
            body: s.title,
            link: `/p/${projectId}/story/${s.id}`,
          });
        }
      }
      lastStoriesPollRef.current = slim(list);
      setStories(list);
    } catch {
      /* ignore background sync errors */
    }
  }, [projectId, pushNotif]);

  useEffect(() => {
    lastStoriesPollRef.current = null;
    commentsSeenByStoryRef.current.clear();
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return undefined;
    const id = window.setInterval(() => {
      syncStoriesFromServer();
    }, 45000);
    return () => window.clearInterval(id);
  }, [projectId, syncStoriesFromServer]);

  useEffect(() => {
    if (!projectId) return undefined;
    const onVis = () => {
      if (document.visibilityState === "visible") syncStoriesFromServer();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [projectId, syncStoriesFromServer]);

  useEffect(() => {
    if (!showNotifPanel) return undefined;
    const onDoc = (e) => {
      if (notifDropdownRef.current && !notifDropdownRef.current.contains(e.target)) setShowNotifPanel(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [showNotifPanel]);

  useEffect(() => {
    if (mainTab !== "board") setShowCreateStory(false);
  }, [mainTab]);

  useEffect(() => {
    setStReleaseId("");
    setStAssigneeIds([]);
    setNewReleaseName("");
    setNewRelDesc("");
    setNewRelStatus("planning");
    setNewRelDateMode("none");
    setNewRelDay("");
    setNewRelStart("");
    setNewRelEnd("");
    setEditingReleaseId(null);
  }, [projectId]);

  const selectedProject = (Array.isArray(projects) ? projects : []).find((p) => p.id === projectId);
  const hasProjectWorkflow = Number(selectedProject?.settings?.workflow_template_id || 0) > 0;
  const chatMembers = useMemo(
    () =>
      (Array.isArray(projectMembers) ? projectMembers : [])
        .filter((row) => row && row.member_id != null)
        .map((row) => ({
          id: row.member_id,
          name: row.member?.display_name || `Member #${row.member_id}`,
          type: row.member?.member_type || "human",
        })),
    [projectMembers]
  );
  const chatChannelItems = useMemo(
    () => [{ id: "general", label: "general", subtitle: "Group chat chung" }, ...chatMembers.map((m) => ({ id: `member-${m.id}`, label: m.name, subtitle: m.type }))],
    [chatMembers]
  );
  const activeChatChannel = chatChannelItems.find((x) => x.id === activeChatId) || chatChannelItems[0] || null;
  /** Số — dùng làm dependency; tránh `me` (object mới mỗi render từ getStoredUser) gây loop fetch chat. */
  const myChatUserId = Number(me?.member_id || me?.id || 0);
  const activeChatRoom = useMemo(() => {
    if (!projectId || !activeChatChannel) return null;
    if (activeChatChannel.id === "general") {
      return {
        channelId: `${projectId}_general`,
        targetKind: "project_channel",
        channelName: "general",
        userId: null,
      };
    }
    if (activeChatChannel.id.startsWith("member-")) {
      const uid = Number(activeChatChannel.id.slice(7));
      if (Number.isFinite(uid) && uid > 0) {
        const my = myChatUserId;
        if (my > 0) {
          const lo = Math.min(my, uid);
          const hi = Math.max(my, uid);
          return {
            channelId: `${projectId}_dm_${lo}_${hi}`,
            targetKind: "private_user",
            channelName: null,
            userId: uid,
          };
        }
        return {
          channelId: `${projectId}_${uid}`,
          targetKind: "private_user",
          channelName: null,
          userId: uid,
        };
      }
    }
    return null;
  }, [projectId, activeChatChannel, myChatUserId]);

  const agentChatContextRef = useRef({ room: null, members: [], pid: null, apiCenterAgents: [], myMemberId: null });
  /** Tránh ghi chat trùng khi vừa nhận chat.agent.ack vừa nhận chat.agent.reply (cùng trace_id). */
  const postedAgentReplyTraceIdsRef = useRef(new Set());
  useEffect(() => {
    agentChatContextRef.current = {
      room: activeChatRoom,
      members: projectMembers,
      pid: projectId,
      apiCenterAgents,
      myMemberId: myChatUserId,
    };
  }, [activeChatRoom, projectMembers, projectId, apiCenterAgents, myChatUserId]);

  const activeChatMessages = activeChatRoom ? chatMessagesByChannel[activeChatRoom.channelId] || [] : [];
  const activeTypingRows = activeChatRoom ? typingByChannel[activeChatRoom.channelId] || [] : [];

  /** Luôn cuộn tới tin mới nhất (đáy) khi đổi kênh hoặc nội dung / reaction cập nhật. */
  useEffect(() => {
    if (mainTab !== "chat") return;
    const el = chatMessagesScrollRef.current;
    if (!el) return;
    const scrollToBottom = () => {
      el.scrollTop = el.scrollHeight;
    };
    requestAnimationFrame(() => {
      requestAnimationFrame(scrollToBottom);
    });
  }, [mainTab, activeChatRoom?.channelId, chatMessagesByChannel]);

  const mentionIndex = useMemo(() => {
    const map = new Map();
    for (const m of chatMembers) {
      map.set(mentionKeyFromName(m.name), m.name);
    }
    return map;
  }, [chatMembers]);
  const mentionSuggestions = useMemo(() => {
    const m = chatInput.match(/(?:^|\s)@([^\s@]*)$/);
    if (!m) return [];
    const q = (m[1] || "").toLowerCase();
    return chatMembers
      .filter((x) => mentionKeyFromName(x.name).includes(q))
      .slice(0, 6);
  }, [chatInput, chatMembers]);

  const renderChatMessageContent = useCallback(
    (content) => renderMarkdownWithMentions(content, mentionIndex),
    [mentionIndex]
  );

  /** Tin từ MCP/agent thường thiếu senderName — lấy display_name từ projectMembers thay vì "User #3". */
  const resolveChatSenderDisplayName = useCallback(
    (senderUserId, senderName) => {
      const trimmed = String(senderName || "").trim();
      if (trimmed) return trimmed;
      const uid = Number(senderUserId);
      if (!Number.isFinite(uid) || uid <= 0) return "Unknown";
      const m = chatMembers.find((x) => Number(x.id) === uid);
      if (m?.name && String(m.name).trim()) return String(m.name).trim();
      return `User #${uid}`;
    },
    [chatMembers]
  );

  const onPickMention = useCallback((displayName) => {
    const mentionToken = `@${mentionKeyFromName(displayName)}`;
    setChatInput((prev) => prev.replace(/(?:^|\s)@([^\s@]*)$/, (all) => all.replace(/@([^\s@]*)$/, `${mentionToken} `)));
  }, []);

  useEffect(() => {
    if (!chatChannelItems.length) return;
    if (!chatChannelItems.some((x) => x.id === activeChatId)) {
      setActiveChatId(chatChannelItems[0].id);
    }
  }, [chatChannelItems, activeChatId]);

  const fetchChatMessages = useCallback(async (room) => {
    if (!room) return;
    const params = new URLSearchParams({
      projectId: String(projectId),
      targetKind: room.targetKind,
    });
    if (room.targetKind === "project_channel" && room.channelName) {
      params.set("channelName", room.channelName);
    }
    if (room.targetKind === "private_user" && room.userId) {
      params.set("userId", String(room.userId));
      const viewer = Number(getStoredUser()?.member_id || getStoredUser()?.id || 0);
      if (viewer > 0) params.set("viewerMemberId", String(viewer));
    }
    const res = await fetch(`${CHAT_API_BASE}/chat/messages?${params.toString()}`);
    const raw = await res.text();
    let data;
    try {
      data = raw ? JSON.parse(raw) : {};
    } catch {
      setErr(`Chat: phản hồi không phải JSON (HTTP ${res.status}). Kiểm tra chat-service (9130) và proxy.`);
      return;
    }
    if (!res.ok) {
      const msg =
        (typeof data?.message === "string" && data.message) ||
        (Array.isArray(data?.message) && data.message.join("; ")) ||
        data?.error ||
        `HTTP ${res.status}`;
      setErr(`Chat: không tải được tin nhắn — ${msg}`);
      return;
    }
    const rows = Array.isArray(data?.messages) ? data.messages : [];
    setChatMessagesByChannel((prev) => ({ ...prev, [room.channelId]: rows }));
  }, [projectId]);

  const syncFlushAgentProcessing = useCallback(() => {
    const rctx = agentReactCtxRef.current;
    agentReactCtxRef.current = null;
    if (rctx?.messageId && rctx.actorUserId && rctx.projectId && rctx.room) {
      postAgentMessageReaction({
        projectId: rctx.projectId,
        room: rctx.room,
        actorUserId: rctx.actorUserId,
        viewerMemberId: rctx.viewerMemberId,
        messageId: rctx.messageId,
        reaction: "doing",
        action: "remove",
      }).catch(() => {});
    }
    if (agentTypingIntervalRef.current) {
      clearInterval(agentTypingIntervalRef.current);
      agentTypingIntervalRef.current = null;
    }
    if (agentTypingSafetyTimerRef.current) {
      clearTimeout(agentTypingSafetyTimerRef.current);
      agentTypingSafetyTimerRef.current = null;
    }
    const p = agentTypingPayloadRef.current;
    agentTypingPayloadRef.current = null;
    agentTypingTraceRef.current = null;
    if (p) postChatTypingHttp({ ...p, isTyping: false }).catch(() => {});
  }, []);

  const resetAgentProcessingUiImmediate = useCallback(() => {
    if (agentUiLeadTimerRef.current) {
      clearTimeout(agentUiLeadTimerRef.current);
      agentUiLeadTimerRef.current = null;
    }
    if (agentStopMinDelayTimerRef.current) {
      clearTimeout(agentStopMinDelayTimerRef.current);
      agentStopMinDelayTimerRef.current = null;
    }
    agentProcessingShownAtRef.current = null;
    syncFlushAgentProcessing();
  }, [syncFlushAgentProcessing]);

  const stopAgentTypingIndicator = useCallback(() => {
    if (agentUiLeadTimerRef.current) {
      clearTimeout(agentUiLeadTimerRef.current);
      agentUiLeadTimerRef.current = null;
    }
    if (agentStopMinDelayTimerRef.current) {
      clearTimeout(agentStopMinDelayTimerRef.current);
      agentStopMinDelayTimerRef.current = null;
    }
    const t0 = agentProcessingShownAtRef.current;
    const wait = t0 ? Math.max(0, AGENT_CHAT_MIN_PROCESSING_MS - (Date.now() - t0)) : 0;
    const finish = () => {
      agentStopMinDelayTimerRef.current = null;
      agentProcessingShownAtRef.current = null;
      syncFlushAgentProcessing();
    };
    if (wait > 0) {
      agentStopMinDelayTimerRef.current = setTimeout(finish, wait);
    } else {
      finish();
    }
  }, [syncFlushAgentProcessing]);

  const beginAgentTypingPulse = useCallback(
    (payload, traceId, onStop) => {
      agentTypingTraceRef.current = traceId || null;
      agentTypingPayloadRef.current = payload;
      const stopFn = typeof onStop === "function" ? onStop : stopAgentTypingIndicator;
      const tick = () => postChatTypingHttp({ ...payload, isTyping: true }).catch(() => {});
      tick();
      agentTypingIntervalRef.current = setInterval(tick, 2500);
      agentTypingSafetyTimerRef.current = setTimeout(() => stopFn(), 120000);
    },
    [stopAgentTypingIndicator]
  );

  const startAgentTypingIndicator = useCallback(
    (payload, traceId) => {
      resetAgentProcessingUiImmediate();
      agentProcessingShownAtRef.current = Date.now();
      beginAgentTypingPulse(payload, traceId, stopAgentTypingIndicator);
    },
    [resetAgentProcessingUiImmediate, beginAgentTypingPulse, stopAgentTypingIndicator]
  );

  stopAgentTypingRef.current = stopAgentTypingIndicator;

  const emitTyping = useCallback(
    (isTyping) => {
      const socket = chatSocketRef.current;
      if (!socket || !activeChatRoom) return;
      const meNow = getStoredUser();
      const uid = Number(meNow?.member_id || meNow?.id || 0);
      if (uid <= 0) return;
      socket.emit("chat:typing", {
        channelId: activeChatRoom.channelId,
        senderUserId: uid,
        senderName: meNow?.display_name || undefined,
        isTyping,
      });
    },
    [activeChatRoom]
  );

  const sendAgentDispatch = useCallback(
    async (payload) => {
      const ws = apiCenterAgentWsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        chatDebug("dispatch via WS", payload?.trace_id, payload?.target_agent_id, payload?.channel_id);
        // Khớp contrat api-center /ws/agent-chat: { "event", "payload" }
        ws.send(
          JSON.stringify({
            event: "chat.message.created",
            payload,
          })
        );
        return { via: "ws" };
      }
      chatDebug("dispatch via HTTP (WS not OPEN)", ws?.readyState, payload?.trace_id);
      const ack = await apiPost("/integrations/api-center/chat/dispatch", payload);
      return { via: "http", ack };
    },
    []
  );

  const onSendChatMessage = useCallback(async () => {
    if (!activeChatRoom || !projectId) return;
    const content = chatInput.trim();
    if (!content) return;
    const me = getStoredUser();
    const body = {
      projectId,
      targetKind: activeChatRoom.targetKind,
      channelName: activeChatRoom.channelName || undefined,
      userId: activeChatRoom.userId || undefined,
      senderUserId: Number(me?.member_id || me?.id || 0),
      senderName: me?.display_name || undefined,
      content,
    };
    const res = await fetch(`${CHAT_API_BASE}/chat/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const er = await res.json().catch(() => ({}));
      throw new Error(er?.message || er?.error || "Send chat failed");
    }
    const sentPayload = await res.json().catch(() => ({}));
    const userMessageId = sentPayload?.id != null ? String(sentPayload.id) : "";
    const roomSnapshot = {
      targetKind: activeChatRoom.targetKind,
      channelName: activeChatRoom.channelName || null,
      userId: activeChatRoom.userId || null,
      channelId: activeChatRoom.channelId,
    };
    const selfFromProject = projectMembers.find((x) => Number(x.member_id) === Number(myChatUserId || 0))?.member
      ?.display_name;
    const myName =
      String(me?.display_name || selfFromProject || "")
        .trim() || "user";
    const mentionMatches = Array.from(content.matchAll(/@([^\s@]+)/g)).map((m) =>
      String(m[1] || "")
        .replace(/[.,;:!?)\]]+$/g, "")
        .toLowerCase()
    );
    const targetAgentFromMention = firstResolvedMentionedAgent(mentionMatches, apiCenterAgents, projectMembers);
    const directAgentTarget =
      roomSnapshot.targetKind === "private_user"
        ? (() => {
            const row = projectMembers.find((x) => Number(x.member_id) === Number(roomSnapshot.userId || 0));
            if (!row?.member?.agent_id) return null;
            return matchAgentIdToCatalog(String(row.member.agent_id || "").toLowerCase(), apiCenterAgents);
          })()
        : null;
    const targetAgent = targetAgentFromMention || directAgentTarget;
    const agentMemberForTyping = targetAgent
      ? resolveAiMemberForAgentReply(projectMembers, targetAgent.id, apiCenterAgents)
      : null;
    chatDebug("onSendChatMessage", {
      mentionMatches,
      targetAgentId: targetAgent?.id,
      apiCenterConnected,
      channelId: roomSnapshot.channelId,
    });
    setChatInput("");
    emitTyping(false);
    if (apiCenterConnected && targetAgent) {
      const history = (chatMessagesByChannel[roomSnapshot.channelId] || []).slice(-8).map((m) => ({
        sender_id: String(m.senderUserId),
        sender_type: Number(m.senderUserId) === Number(myChatUserId) ? "human" : "agent",
        content: String(m.content || ""),
        created_at: m.createdAt,
      }));
      const fromStories = findStoryKeysFromLoadedStories(content, stories);
      const fromSlugPattern = findStoryKeysByProjectSlugPattern(content, selectedProject?.slug);
      const mentionedStoryKeys = [...new Set([...fromStories, ...fromSlugPattern])];
      const dispatchPayload = {
        trace_id: `tr_${Date.now()}`,
        project_id: String(projectId),
        project_context: {
          name: selectedProject?.name || `Project ${projectId}`,
          id: projectId,
          slug: selectedProject?.slug ?? null,
          workspace_ref: selectedProject?.workspace_ref ?? null,
        },
        channel_id: roomSnapshot.channelId,
        channel_type: roomSnapshot.targetKind === "private_user" ? "direct" : "group",
        sender: { id: String(myChatUserId || 0), name: myName },
        message: content,
        mentions: mentionMatches,
        target_agent_id: String(targetAgent.id),
        conversation_history: history,
        ...(mentionedStoryKeys.length
          ? {
              story_context: {
                source: "message_mention",
                mentioned_story_keys: mentionedStoryKeys,
                primary_story_key: mentionedStoryKeys[0] || null,
              },
            }
          : {}),
      };
      if (agentMemberForTyping?.member_id && userMessageId) {
        resetAgentProcessingUiImmediate();
        const aid = Number(agentMemberForTyping.member_id);
        const typingPayload = {
          projectId,
          room: roomSnapshot,
          senderUserId: aid,
          senderName:
            agentMemberForTyping.member?.display_name || targetAgent.name || String(targetAgent.id),
          viewerMemberId: myChatUserId,
        };
        agentUiLeadTimerRef.current = setTimeout(() => {
          agentUiLeadTimerRef.current = null;
          agentProcessingShownAtRef.current = Date.now();
          agentReactCtxRef.current = {
            messageId: userMessageId,
            projectId,
            room: roomSnapshot,
            actorUserId: aid,
            viewerMemberId: myChatUserId,
          };
          postAgentMessageReaction({
            projectId,
            room: roomSnapshot,
            actorUserId: aid,
            viewerMemberId: myChatUserId,
            messageId: userMessageId,
            reaction: "seen",
            action: "add",
          }).catch(() => {});
          postAgentMessageReaction({
            projectId,
            room: roomSnapshot,
            actorUserId: aid,
            viewerMemberId: myChatUserId,
            messageId: userMessageId,
            reaction: "doing",
            action: "add",
          }).catch(() => {});
          beginAgentTypingPulse(typingPayload, dispatchPayload.trace_id, stopAgentTypingIndicator);
        }, AGENT_CHAT_UI_LEAD_MS);
      } else if (agentMemberForTyping?.member_id) {
        startAgentTypingIndicator(
          {
            projectId,
            room: roomSnapshot,
            senderUserId: Number(agentMemberForTyping.member_id),
            senderName:
              agentMemberForTyping.member?.display_name || targetAgent.name || String(targetAgent.id),
            viewerMemberId: myChatUserId,
          },
          dispatchPayload.trace_id
        );
      }
      sendAgentDispatch(dispatchPayload)
        .then(async ({ via, ack }) => {
          chatDebug("dispatch settled", { via, should_respond: ack?.should_respond, reply_len: ack?.reply_text?.length });
          if (via === "ws") return;
          try {
            if (!ack?.should_respond || !ack?.reply_text) return;
            const agentMember = resolveAiMemberForAgentReply(projectMembers, targetAgent.id, apiCenterAgents);
            if (!agentMember?.member_id) return;
            const dmPeerUserId = dmPeerUserIdForAgentSend(roomSnapshot, agentMember.member_id, myChatUserId);
            await fetch(`${CHAT_API_BASE}/chat/messages`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                projectId,
                targetKind: roomSnapshot.targetKind,
                channelName: roomSnapshot.channelName || undefined,
                userId: dmPeerUserId,
                senderUserId: Number(agentMember.member_id),
                senderName: agentMember.member?.display_name || targetAgent.name || String(targetAgent.id),
                content: String(ack.reply_text),
              }),
            });
          } finally {
            stopAgentTypingIndicator();
          }
        })
        .catch((err) => {
          chatDebug("dispatch failed", err);
          stopAgentTypingIndicator();
        });
    } else if (content.includes("@") && apiCenterConnected && !targetAgent) {
      chatDebug("mention nhưng không resolve được agent — kiểm tra catalog / member AI / @token");
    }
  }, [
    activeChatRoom,
    chatInput,
    projectId,
    apiCenterConnected,
    apiCenterAgents,
    chatMessagesByChannel,
    projectMembers,
    selectedProject,
    stories,
    myChatUserId,
    emitTyping,
    sendAgentDispatch,
    resetAgentProcessingUiImmediate,
    beginAgentTypingPulse,
    startAgentTypingIndicator,
    stopAgentTypingIndicator,
  ]);

  const onDeleteChatMessage = useCallback(
    async (msg) => {
      if (!activeChatRoom || !projectId || !msg?.id) return;
      if (!window.confirm("Remove this message?")) return;
      const uid = Number(me?.member_id || me?.id || 0);
      if (uid <= 0) {
        setErr("You need to login to remove messages.");
        return;
      }
      const params = new URLSearchParams({
        projectId: String(projectId),
        targetKind: activeChatRoom.targetKind,
        senderUserId: String(uid),
      });
      if (activeChatRoom.targetKind === "project_channel" && activeChatRoom.channelName) {
        params.set("channelName", activeChatRoom.channelName);
      }
      if (activeChatRoom.targetKind === "private_user" && activeChatRoom.userId) {
        params.set("userId", String(activeChatRoom.userId));
      }
      const res = await fetch(`${CHAT_API_BASE}/chat/messages/${encodeURIComponent(msg.id)}?${params.toString()}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const er = await res.json().catch(() => ({}));
        const detail = er?.message;
        const text = Array.isArray(detail) ? detail.map((x) => x?.constraints && Object.values(x.constraints).join(" ")).join("; ") : detail || er?.error;
        throw new Error(text || "Delete message failed");
      }
    },
    [activeChatRoom, projectId, myChatUserId]
  );

  const onReactChatMessage = useCallback(
    async (msg, reaction) => {
      if (!activeChatRoom || !projectId || !msg?.id) return;
      const uid = Number(me?.member_id || me?.id || 0);
      if (uid <= 0) {
        setErr("You need to login to react to messages.");
        return;
      }
      const res = await fetch(`${CHAT_API_BASE}/chat/messages/${encodeURIComponent(msg.id)}/reactions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          projectId,
          targetKind: activeChatRoom.targetKind,
          channelName: activeChatRoom.channelName || undefined,
          userId: activeChatRoom.userId || undefined,
          actorUserId: uid,
          reaction,
          action: "toggle",
        }),
      });
      if (!res.ok) {
        const er = await res.json().catch(() => ({}));
        throw new Error(er?.message || er?.error || "React message failed");
      }
    },
    [activeChatRoom, projectId, myChatUserId]
  );

  const storyDrawerOpen = storyId != null;
  useEffect(() => {
    if (!projectId || (mainTab !== "chat" && !storyDrawerOpen)) return;
    const socket = io(CHAT_WS_NAMESPACE, { transports: ["websocket", "polling"] });
    chatSocketRef.current = socket;
    socket.on("connect", () => setChatConnected(true));
    socket.on("disconnect", () => setChatConnected(false));
    socket.on("connect_error", (err) => {
      setChatConnected(false);
      setErr(err?.message || "Chat websocket connect failed");
    });
    socket.on("chat:message", (msg) => {
      if (!msg?.channelId) return;
      setChatMessagesByChannel((prev) => {
        const cur = prev[msg.channelId] || [];
        if (cur.some((x) => x.id === msg.id)) return prev;
        return { ...prev, [msg.channelId]: [...cur, msg] };
      });
    });
    socket.on("chat:event", (evt) => {
      if (!evt || evt.type !== "event") return;
      const pid = Number(evt.projectId);
      const sid = Number(evt.storyId);
      if (pid !== projectIdRef.current || sid !== storyIdRef.current) return;
      const et = evt.eventType;
      const pl = evt.payload && typeof evt.payload === "object" ? evt.payload : {};
      if (et === "story.comment.created") {
        const c = pl.comment;
        if (!c?.id) return;
        setComments((prev) => {
          if (prev.some((x) => x.id === c.id)) return prev;
          const next = [...prev, c];
          next.sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
          return next;
        });
      } else if (et === "story.comment.updated") {
        const c = pl.comment;
        if (!c?.id) return;
        setComments((prev) => prev.map((x) => (x.id === c.id ? c : x)));
      } else if (et === "story.comment.deleted") {
        const cid = Number(pl.comment_id);
        if (!Number.isFinite(cid)) return;
        setComments((prev) => prev.filter((x) => x.id !== cid));
      }
    });
    socket.on("chat:messageDeleted", (payload) => {
      if (!payload?.channelId || !payload?.id) return;
      setChatMessagesByChannel((prev) => {
        const cur = prev[payload.channelId];
        if (!cur?.length) return prev;
        return { ...prev, [payload.channelId]: cur.filter((x) => x.id !== payload.id) };
      });
    });
    socket.on("chat:messageReaction", (payload) => {
      if (!payload?.channelId || !payload?.id || !Array.isArray(payload?.reactions)) return;
      setChatMessagesByChannel((prev) => {
        const cur = prev[payload.channelId];
        if (!cur?.length) return prev;
        return {
          ...prev,
          [payload.channelId]: cur.map((m) => (m.id === payload.id ? { ...m, reactions: payload.reactions } : m)),
        };
      });
    });
    socket.on("chat:typing", (payload) => {
      if (!payload?.channelId || !payload?.senderUserId) return;
      const now = Date.now();
      setTypingByChannel((prev) => {
        const cur = prev[payload.channelId] || [];
        const next = cur.filter((x) => Number(x.senderUserId) !== Number(payload.senderUserId));
        if (payload.isTyping !== false) {
          next.push({
            senderUserId: Number(payload.senderUserId),
            senderName: payload.senderName || null,
            expiresAt: now + 3500,
          });
        }
        return { ...prev, [payload.channelId]: next };
      });
    });
    return () => {
      setChatConnected(false);
      setTypingByChannel({});
      socket.disconnect();
      chatSocketRef.current = null;
    };
  }, [mainTab, projectId, storyDrawerOpen]);

  useEffect(() => {
    const sock = chatSocketRef.current;
    if (!sock || !chatConnected || projectId == null || storyId == null) return;
    const channelId = storyCommentsChannelId(projectId, storyId);
    sock.emit("chat:join", { channelId });
    return () => {
      sock.emit("chat:leave", { channelId });
    };
  }, [projectId, storyId, chatConnected]);

  useEffect(() => {
    if (mainTab !== "chat") {
      setApiCenterAgentWsReady(false);
      return undefined;
    }
    if (!apiCenterConnected || !apiCenterChatWsUrl) {
      setApiCenterAgentWsReady(false);
      console.warn("[agile-chat] Không mở WebSocket API Center:", {
        tabChat: mainTab === "chat",
        apiCenterConnected,
        chat_ws_url_empty: !apiCenterChatWsUrl,
        hint:
          !apiCenterConnected
            ? "Connect API Center in Settings."
            : "Missing chat_ws_url — Settings → Reconnect API Center (to save endpoints.chat_ws).",
      });
      return undefined;
    }
    let ws;
    try {
      ws = new WebSocket(apiCenterChatWsUrl);
      apiCenterAgentWsRef.current = ws;
      chatDebug("API Center WS connecting", apiCenterChatWsUrl?.slice?.(0, 80));
      ws.onopen = () => {
        chatDebug("API Center WS open");
        setApiCenterAgentWsReady(true);
      };
      ws.onclose = (ev) => {
        chatDebug("API Center WS close", ev.code, ev.reason);
        stopAgentTypingRef.current();
        setApiCenterAgentWsReady(false);
      };
      ws.onerror = () => {
        chatDebug("API Center WS error");
        stopAgentTypingRef.current();
        setApiCenterAgentWsReady(false);
        setErr(
          "WebSocket API Center (chat) error — check chat_ws URL in Settings, API_CENTER_PUBLIC_BASE_URL (must have http/https), and port is open."
        );
      };
      ws.onmessage = async (evt) => {
        let packet;
        try {
          packet = JSON.parse(String(evt?.data || "{}"));
        } catch {
          return;
        }
        const evType = String(packet?.event || packet?.type || "");
        const p = packet && typeof packet === "object" ? packet : {};
        const data = p.data && typeof p.data === "object" ? { ...p, ...p.data } : p;
        chatDebug("[api-center ws]", evType, data?.trace_id || data?.channel_id, data?.reply_text?.slice?.(0, 80));
        if (evType === "chat.connected") return;
        if (evType === "chat.agent.error") {
          stopAgentTypingRef.current();
          const errMsg = String(data?.error || packet?.error || "").trim();
          if (errMsg) setErr(`API Center chat: ${errMsg}`);
          return;
        }
        /** Ack: policy không trả lời → dừng typing (không có `chat.agent.reply`). */
        if (evType === "chat.agent.ack") {
          const ackCh = String(data?.channel_id || data?.channelId || "");
          const pending = agentTypingPayloadRef.current;
          if (
            pending &&
            ackCh &&
            String(pending.room.channelId) === ackCh &&
            data?.should_respond !== true
          ) {
            stopAgentTypingRef.current();
          }
          return;
        }
        /** Không post từ `chat.agent.ack`: server gửi `chat.agent.reply` sau — chỉ post từ reply/legacy. */
        const isAgentReply = evType === "chat.agent.reply";
        const isLegacyCreated = evType === "chat.message.created";
        if (!isAgentReply && !isLegacyCreated) return;

        const channelId = String(data?.channel_id || data?.channelId || "");
        const replyTrace = String(data?.trace_id || "").trim();
        const stopTypingIfOurReply = () => {
          if (!replyTrace || replyTrace === agentTypingTraceRef.current) stopAgentTypingRef.current();
        };

        const content = String(data?.reply_text || data?.message || data?.content || "").trim();
        const targetAgentId = String(
          data?.target_agent_id || data?.agent_id || data?.selected_agent_id || data?.sender_id || ""
        ).trim();
        if (!channelId || !content) {
          stopTypingIfOurReply();
          return;
        }

        const traceId = replyTrace;
        if (traceId && postedAgentReplyTraceIdsRef.current.has(traceId)) {
          stopTypingIfOurReply();
          return;
        }

        const ctx = agentChatContextRef.current || {};
        const { room, members, pid, apiCenterAgents: agents, myMemberId } = ctx;
        if (!room || String(room.channelId) !== channelId) return;

        const agentMember = resolveAiMemberForAgentReply(members, targetAgentId, agents);
        if (!agentMember?.member_id) {
          console.warn("[agent-chat] Cannot map selected_agent_id → member AI:", targetAgentId, members);
          stopTypingIfOurReply();
          return;
        }
        const dmPeerUserId = dmPeerUserIdForAgentSend(room, agentMember.member_id, myMemberId);
        try {
          const res = await fetch(`${CHAT_API_BASE}/chat/messages`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              projectId: pid,
              targetKind: room.targetKind,
              channelName: room.channelName || undefined,
              userId: dmPeerUserId,
              senderUserId: Number(agentMember.member_id),
              senderName: agentMember.member?.display_name || targetAgentId || "AI Agent",
              content,
            }),
          });
          if (!res.ok) {
            const er = await res.json().catch(() => ({}));
            const detail = er?.message || er?.error || `HTTP ${res.status}`;
            setErr(typeof detail === "string" ? detail : "Cannot send agent message to chat.");
            return;
          }
          if (traceId) {
            postedAgentReplyTraceIdsRef.current.add(traceId);
            if (postedAgentReplyTraceIdsRef.current.size > 200) postedAgentReplyTraceIdsRef.current.clear();
          }
        } catch (e) {
          setErr(String(e?.message || e));
        } finally {
          stopTypingIfOurReply();
        }
      };
    } catch {
      apiCenterAgentWsRef.current = null;
      setApiCenterAgentWsReady(false);
      return undefined;
    }
    return () => {
      stopAgentTypingRef.current();
      setApiCenterAgentWsReady(false);
      try {
        ws.close();
      } catch {
        // ignore close errors
      }
      if (apiCenterAgentWsRef.current === ws) apiCenterAgentWsRef.current = null;
    };
  }, [mainTab, apiCenterConnected, apiCenterChatWsUrl]);

  useEffect(() => {
    if (chatTypingPurgeTimerRef.current) clearInterval(chatTypingPurgeTimerRef.current);
    chatTypingPurgeTimerRef.current = setInterval(() => {
      const now = Date.now();
      setTypingByChannel((prev) => {
        const out = {};
        let changed = false;
        for (const [channelId, rows] of Object.entries(prev)) {
          const keep = (rows || []).filter((x) => Number(x.expiresAt || 0) > now);
          if (keep.length) out[channelId] = keep;
          if (keep.length !== (rows || []).length) changed = true;
        }
        return changed ? out : prev;
      });
    }, 900);
    return () => {
      if (chatTypingPurgeTimerRef.current) clearInterval(chatTypingPurgeTimerRef.current);
      chatTypingPurgeTimerRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (mainTab !== "chat" || !activeChatRoom || !chatSocketRef.current) return;
    fetchChatMessages(activeChatRoom).catch((e) => setErr(e.message));
    chatSocketRef.current.emit("chat:join", { channelId: activeChatRoom.channelId });
    return () => {
      chatSocketRef.current?.emit("chat:leave", { channelId: activeChatRoom.channelId });
    };
  }, [mainTab, activeChatRoom, fetchChatMessages]);

  const memberNameById = useMemo(() => {
    const o = {};
    for (const row of projectMembers) {
      o[row.member_id] = row.member?.display_name || `Member #${row.member_id}`;
    }
    return o;
  }, [projectMembers]);

  useEffect(() => {
    if (mainTab !== "settings" || !selectedProject) return;
    const s = selectedProject.settings || {};
    setProjWorkspaceRef(selectedProject.workspace_ref || "");
    setProjGhRepo(s.github_repository || "");
    setProjGhBranch(s.github_default_branch || "");
    setProjGhToken("");
    setProjClearGhToken(false);
    setProjDocsPath(s.documents_storage_path || "");
    setProjNotes(s.notes || "");
    setProjSlackChannel(s.slack_channel || "");
    setProjSlackWebhook("");
    setProjClearSlackWebhook(false);
    setProjDiscordLabel(s.discord_channel_label || "");
    setProjDiscordWebhook("");
    setProjClearDiscordWebhook(false);
    // URL not returned from API; leave empty — enter new when needed.
    setProjAiWqUrl("");
    setProjAiWqSecret("");
    setProjClearAiWqUrl(false);
    setProjClearAiWqSecret(false);
    setProjAiWqAgentId(s.ai_working_queue_agent_id || "");
    setProjWorkflowTemplateId(s.workflow_template_id != null ? String(s.workflow_template_id) : "");
    setProjStorageOverview(s.storage_overview || "");
    setSettingsSaved(false);
  }, [mainTab, projectId, selectedProject?.id, selectedProject?.updated_at]);

  useEffect(() => {
    if (mainTab !== "settings") return;
    refreshApiCenterStatus().catch((e) => setErr(e.message));
  }, [mainTab, refreshApiCenterStatus]);

  useEffect(() => {
    if (mainTab !== "team") return;
    refreshApiCenterStatus().catch((e) => setErr(e.message));
  }, [mainTab, refreshApiCenterStatus]);

  /** Bắt buộc: lấy chat_ws_url từ Hub khi vào Chat — trước đây chỉ Settings/Team refresh nên WS không bao giờ mở. */
      useEffect(() => {
    if (mainTab !== "chat") return;
    refreshApiCenterStatus().catch((e) => setErr(e.message));
  }, [mainTab, refreshApiCenterStatus]);

  useEffect(() => {
    if (mainTab !== "team" || !apiCenterConnected) return;
    refreshApiCenterAgents().catch((e) => setErr(e.message));
  }, [mainTab, apiCenterConnected, refreshApiCenterAgents]);

  useEffect(() => {
    if (mainTab !== "chat" || !apiCenterConnected) return;
    refreshApiCenterAgents().catch((e) => setErr(e.message));
  }, [mainTab, apiCenterConnected, refreshApiCenterAgents]);

  useEffect(() => {
    refreshProjects().catch((e) => setErr(e.message));
  }, [refreshProjects]);

  useEffect(() => {
    refreshMembers().catch((e) => setErr(e.message));
  }, [refreshMembers]);

  useEffect(() => {
    if (mainTab !== "master-data" && mainTab !== "settings") return;
    refreshWorkflowTemplates().catch((e) => setErr(e.message));
  }, [mainTab, refreshWorkflowTemplates]);

  useEffect(() => {
    const p = location.pathname;
    if (p === "/login" || p === "/register") return;
    if (parseWorkspacePath(location.pathname) === null) {
      navigate("/", { replace: true });
    }
  }, [location.pathname, navigate]);

  useEffect(() => {
    const p = parseWorkspacePath(location.pathname);
    if (p === null) return;
    if (p.projectId === null) {
      if (projectId !== null) {
        setProjectId(null);
        setProjectMembers([]);
        setStories([]);
        setReleases([]);
        closeStoryDrawer();
        setShowCreateStory(false);
      }
      return;
    }
    if (projectId !== p.projectId) {
      loadProject(p.projectId, { preserveStory: p.tab === "story" }).catch((er) => setErr(er.message));
    }
  }, [location.pathname, projectId, loadProject, closeStoryDrawer]);

  useEffect(() => {
    const p = parseWorkspacePath(location.pathname);
    if (p === null || p.tab !== "story" || p.storyId == null) return;
    if (storyId !== p.storyId) {
      loadStory(p.storyId).catch((er) => setErr(er.message));
    }
  }, [location.pathname, storyId, loadStory]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (showNotifPanel) {
        setShowNotifPanel(false);
        return;
      }
      if (storyDetail) {
        const w = parseWorkspacePath(window.location.pathname);
        if (w?.tab === "story" && w.projectId != null) {
          navigate(`/p/${w.projectId}/board`);
          closeStoryDrawer();
        } else {
          closeStoryDrawer();
        }
      } else if (mainTab === "master-data") {
        closeMasterDataHub();
      } else if (showProjectsHub) closeProjectsHub();
      else if (showCreateStory) closeCreateStory();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [storyDetail, mainTab, showProjectsHub, showCreateStory, showNotifPanel, closeStoryDrawer, closeProjectsHub, closeMasterDataHub, closeCreateStory, navigate]);

  const onNavbarProjectChange = (e) => {
    const v = e.target.value;
    const cur = parseWorkspacePath(location.pathname);
    const tab = cur?.tab ?? "board";
    if (!v) {
      if (tab === "team") navigate("/team");
      else if (tab === "master-data") navigate("/master-data");
      else navigate("/");
      return;
    }
    const pid = Number(v);
    if (cur?.tab === "story") {
      navigate(`/p/${pid}/board`);
      return;
    }
    if (tab === "master-data") {
      navigate(`/p/${pid}/board`);
      return;
    }
    navigate(`/p/${pid}/${tab}`);
  };

  const onCreateProject = async (e) => {
    e.preventDefault();
    setErr(null);
    try {
      const created = await apiPost("/projects", {
        slug: slug.trim().toLowerCase(),
        name: pname.trim(),
        workspace_ref: wsRef.trim() || null,
      });
      setSlug("");
      setPname("");
      setWsRef("");
      await refreshProjects();
      if (created?.id != null) {
        pushNotif({
          type: "project",
          title: "Project created",
          body: created.name ?? pname.trim(),
          link: `/p/${created.id}/board`,
        });
        navigate(`/p/${created.id}/board`);
        closeProjectsHub();
      }
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onPickProjectFromHub = (pid) => {
    navigate(`/p/${pid}/board`);
    closeProjectsHub();
  };

  const onCreateMember = async (e) => {
    e.preventDefault();
    setErr(null);
    try {
      const body = {
        member_type: mType,
        display_name: mName.trim(),
        agent_id: mType === "ai" ? mAgent.trim() || null : null,
      };
      await apiPost("/members", body);
      pushNotif({
        type: "team",
        title: "Workspace member created",
        body: mName.trim(),
        link: "/team",
      });
      setMName("");
      setMAgent("");
      await refreshMembers();
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onAddProjectMember = async (e) => {
    e.preventDefault();
    if (!projectId || !addMemId) return;
    setErr(null);
    try {
      const mid = Number(addMemId);
      await apiPost(`/projects/${projectId}/members`, { member_id: mid, role: addRole });
      const added = members.find((m) => m.id === mid);
      pushNotif({
        type: "team",
        title: "Member added to project",
        body: added?.display_name ?? `Member #${mid}`,
        link: `/p/${projectId}/team`,
      });
      setAddMemId("");
      await loadProject(projectId);
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onRemoveProjectMember = async (mid) => {
    if (!projectId || !confirm("Remove this member from the project?")) return;
    setErr(null);
    try {
      await apiDelete(`/projects/${projectId}/members/${mid}`);
      await loadProject(projectId);
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onCreateStory = async (e) => {
    e.preventDefault();
    if (!projectId) return;
    if (!hasProjectWorkflow) {
      setErr("Please select a workflow template in Project Settings before creating stories.");
      return;
    }
    setErr(null);
    try {
      const createdTitle = stTitle.trim();
      const body = {
        title: createdTitle,
        description: stDesc.trim() || null,
        status: stStatus,
      };
      if (stReleaseId) {
        const rid = Number(stReleaseId);
        if (Number.isFinite(rid)) body.release_id = rid;
      }
      if (stAssigneeIds.length) {
        body.assignee_ids = stAssigneeIds.map((x) => Number(x));
      }
      await apiPost(`/projects/${projectId}/stories`, body);
      pushNotif({
        type: "story",
        title: "Story created",
        body: createdTitle,
        link: `/p/${projectId}/board`,
      });
      setStTitle("");
      setStDesc("");
      setStStatus("icebox_in_progress");
      setStReleaseId("");
      setStAssigneeIds([]);
      setShowCreateStory(false);
      await loadProject(projectId);
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onPatchStoryRelease = async (sid, releaseId) => {
    if (!projectId) return;
    if (!hasProjectWorkflow) {
      setErr("Please select a workflow template in Project Settings before updating stories.");
      return;
    }
    setErr(null);
    try {
      await apiPatch(`/stories/${sid}`, { release_id: releaseId });
      await loadProject(projectId);
      if (storyId === sid) await loadStory(sid);
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onPatchStoryAssignees = async (sid, assigneeIds) => {
    if (!projectId) return;
    if (!hasProjectWorkflow) {
      setErr("Please select a workflow template in Project Settings before updating stories.");
      return;
    }
    setErr(null);
    try {
      await apiPatch(`/stories/${sid}`, { assignee_ids: assigneeIds });
      await loadProject(projectId);
      if (storyId === sid) await loadStory(sid);
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onCreateRelease = async (e) => {
    e.preventDefault();
    if (!projectId || !newReleaseName.trim()) return;
    setErr(null);
    const body = {
      name: newReleaseName.trim(),
      status: newRelStatus,
    };
    if (newRelDesc.trim()) body.description = newRelDesc.trim();
    if (newRelDateMode === "day" && newRelDay) {
      body.starts_at = localYmdToIsoStart(newRelDay);
    } else if (newRelDateMode === "range" && newRelStart) {
      body.starts_at = localYmdToIsoStart(newRelStart);
      body.ends_at = newRelEnd ? localYmdToIsoEnd(newRelEnd) : localYmdToIsoEnd(newRelStart);
    }
    try {
      await apiPost(`/projects/${projectId}/releases`, body);
      setNewReleaseName("");
      setNewRelDesc("");
      setNewRelStatus("planning");
      setNewRelDateMode("none");
      setNewRelDay("");
      setNewRelStart("");
      setNewRelEnd("");
      await loadProject(projectId, { preserveStory: true });
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onCreateWorkflowTemplate = async (e) => {
    e.preventDefault();
    setErr(null);
    try {
      await apiPost("/workflow-templates", {
        name: wfName.trim(),
        description: wfDesc.trim() || null,
      });
      setWfName("");
      setWfDesc("");
      await refreshWorkflowTemplates();
      pushNotif({
        type: "project",
        title: "Workflow template created",
        body: "Master data",
        link: "/master-data",
      });
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const beginEditRelease = (r) => {
    setErr(null);
    setEditingReleaseId(r.id);
    setEditName(r.name);
    setEditStatus(r.status);
    setEditDesc(r.description ?? "");
    const a = releaseIsoYmd(r.starts_at);
    const b = releaseIsoYmd(r.ends_at);
    if (!a) {
      setEditDateMode("none");
      setEditDay("");
      setEditStart("");
      setEditEnd("");
    } else if (!b || a === b) {
      setEditDateMode("day");
      setEditDay(a);
      setEditStart("");
      setEditEnd("");
    } else {
      setEditDateMode("range");
      setEditDay("");
      setEditStart(a);
      setEditEnd(b);
    }
  };

  const cancelEditRelease = () => {
    setEditingReleaseId(null);
  };

  const onSaveEditRelease = async (e) => {
    e?.preventDefault?.();
    if (!projectId || editingReleaseId == null) return;
    setErr(null);
    const name = editName.trim();
    if (!name) {
      setErr("Name is required.");
      return;
    }
    const body = { name, status: editStatus, description: editDesc.trim() || null };
    if (editDateMode === "none") {
      body.starts_at = null;
      body.ends_at = null;
    } else if (editDateMode === "day") {
      if (!editDay) {
        setErr("Choose a day or set window to None.");
        return;
      }
      body.starts_at = localYmdToIsoStart(editDay);
      body.ends_at = null;
    } else {
      if (!editStart) {
        setErr("Start date is required for a range.");
        return;
      }
      body.starts_at = localYmdToIsoStart(editStart);
      body.ends_at = editEnd ? localYmdToIsoEnd(editEnd) : localYmdToIsoEnd(editStart);
    }
    try {
      await apiPatch(`/releases/${editingReleaseId}`, body);
      setEditingReleaseId(null);
      await loadProject(projectId, { preserveStory: true });
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onDeleteRelease = async (rid) => {
    if (!projectId || !window.confirm("Delete this release? Stories will be unlinked from it.")) return;
    setErr(null);
    try {
      await apiDelete(`/releases/${rid}`);
      await loadProject(projectId, { preserveStory: true });
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onPatchStoryStatus = async (sid, status) => {
    if (!hasProjectWorkflow) {
      setErr("Please select a workflow template in Project Settings before updating stories.");
      return;
    }
    setErr(null);
    try {
      const row = stories.find((x) => x.id === sid);
      await apiPatch(`/stories/${sid}`, { status });
      const t = row?.title ?? (storyDetail?.id === sid ? storyDetail.title : undefined);
      pushNotif({
        type: "story",
        title: "Story updated",
        body: t ? `“${t}” → ${status}` : `Status → ${status}`,
        link: projectId ? `/p/${projectId}/story/${sid}` : null,
      });
      await loadProject(projectId);
      if (storyId === sid) await loadStory(sid);
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onPatchStoryDetails = async (sid, { title, description }) => {
    if (!projectId) return;
    if (!hasProjectWorkflow) {
      setErr("Please select a workflow template in Project Settings before updating stories.");
      return;
    }
    setErr(null);
    const body = {};
    if (title !== undefined) body.title = title;
    if (description !== undefined) body.description = description;
    try {
      await apiPatch(`/stories/${sid}`, body);
      await loadProject(projectId);
      if (storyId === sid) await loadStory(sid);
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onPostComment = async (e) => {
    e.preventDefault();
    if (!storyId || !cmBody.trim()) return;
    setErr(null);
    try {
      const created = await apiPost(`/stories/${storyId}/comments`, {
        body: cmBody.trim(),
      });
      setCmBody("");
      setComments((prev) => {
        if (prev.some((x) => x.id === created.id)) return prev;
        const next = [...prev, created];
        next.sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
        return next;
      });
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onPatchComment = async (commentId, body) => {
    if (!storyId) return;
    setErr(null);
    try {
      const updated = await apiPatch(`/stories/${storyId}/comments/${commentId}`, { body });
      setComments((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onDeleteComment = async (commentId) => {
    if (!storyId || !window.confirm("Delete this comment?")) return;
    setErr(null);
    try {
      await apiDelete(`/stories/${storyId}/comments/${commentId}`);
      setComments((prev) => prev.filter((c) => c.id !== commentId));
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onSaveProjectSettings = async (e) => {
    e.preventDefault();
    if (!projectId) return;
    setErr(null);
    const settings = {
      storage_overview: projStorageOverview.trim(),
    };
    settings.workflow_template_id = projWorkflowTemplateId ? Number(projWorkflowTemplateId) : 0;
    try {
      const detail = await apiPatch(`/projects/${projectId}`, {
        settings,
      });
      setProjects((prev) => {
        const i = prev.findIndex((x) => x.id === detail.id);
        if (i === -1) return [detail, ...prev];
        const next = [...prev];
        next[i] = detail;
        return next;
      });
      setProjStorageOverview(detail?.settings?.storage_overview || "");
      setSettingsSaved(true);
      pushNotif({
        type: "project",
        title: "Project settings saved",
        body: selectedProject?.name ?? "Project",
        link: projectId ? `/p/${projectId}/settings` : null,
      });
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onConnectApiCenter = async () => {
    setErr(null);
    try {
      await apiPost("/integrations/api-center/connect", {
        endpoint: apiCenterEndpoint.trim(),
        secret: apiCenterSecret,
      });
      setApiCenterSecret("");
      await refreshApiCenterStatus();
      await refreshApiCenterAgents();
      setSettingsSaved(true);
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onAllowApiCenterMcp = async () => {
    setErr(null);
    try {
      await apiPost("/integrations/api-center/allow-mcp-access", {
        mcp_server_id: "agile-studio",
        mcp_url: apiCenterMcpUrl.trim(),
        metadata: { source: "agile-studio-web" },
      });
      await refreshApiCenterStatus();
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const onAddApiAgentToProject = async (e) => {
    e.preventDefault();
    if (!projectId || !selectedApiAgentId) return;
    setErr(null);
    try {
      const agent = apiCenterAgents.find((x) => String(x.id) === String(selectedApiAgentId));
      if (!agent) throw new Error("Agent not found");
      let member = members.find((m) => m.member_type === "ai" && String(m.agent_id || "") === String(agent.id));
      if (!member) {
        member = await apiPost("/members", {
          member_type: "ai",
          display_name: String(agent.name || agent.id),
          agent_id: String(agent.id),
          meta_json: { role: agent.role || null, workspace: agent.workspace || null },
        });
        await refreshMembers();
      }
      await apiPost(`/projects/${projectId}/members`, {
        member_id: Number(member.id),
        role: addRole || "member",
      });
      setSelectedApiAgentId("");
      await loadProject(projectId);
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const memberIdsInProject = new Set(projectMembers.map((x) => x.member_id));
  const membersNotInProject = members.filter((m) => !memberIdsInProject.has(m.id));
  const apiAgentsNotInProject = apiCenterAgents.filter((a) => {
    const found = members.find((m) => m.member_type === "ai" && String(m.agent_id || "") === String(a.id));
    return !found || !memberIdsInProject.has(found.id);
  });
  const authUser = getStoredUser();

  const releaseNameById = useMemo(() => {
    const m = {};
    for (const r of releases) m[r.id] = r.name;
    return m;
  }, [releases]);

  const unreadNotifCount = useMemo(() => notifications.filter((n) => !n.read).length, [notifications]);

  const markNotificationRead = (id) => {
    setNotifications((prev) => {
      const next = prev.map((x) => (x.id === id ? { ...x, read: true } : x));
      saveNotifications(next);
      return next;
    });
  };

  const markAllNotificationsRead = () => {
    setNotifications((prev) => {
      const next = prev.map((x) => ({ ...x, read: true }));
      saveNotifications(next);
      return next;
    });
  };

  const clearAllNotifications = () => {
    saveNotifications([]);
    setNotifications([]);
  };

  return (
    <div className="as-app">
      <header className="as-topbar">
        <Link to="/" className="as-brand text-decoration-none text-reset">
          <span className="as-brand-mark">
            <i className="bi bi-kanban text-white" aria-hidden />
          </span>
          <span className="as-brand-text">
            <div className="as-title">Agile Studio</div>
            <div className="as-tagline">Projects &amp; stories</div>
          </span>
        </Link>
        <div className="as-topbar-actions">
          <button
            type="button"
            className="btn btn-sm btn-outline-light flex-shrink-0"
            onClick={() => setShowProjectsHub(true)}
            title="Browse and create projects"
          >
            <i className="bi bi-folder2 me-1" aria-hidden />
            Projects
          </button>
          <button
            type="button"
            className={`btn btn-sm flex-shrink-0 ${mainTab === TABS.masterData.id ? "btn-light text-dark" : "btn-outline-light"}`}
            onClick={() => navigate("/master-data")}
            title="Master data"
          >
            <i className={`${TABS.masterData.icon} me-1`} aria-hidden />
            {TABS.masterData.label}
          </button>
          <div className="as-project-select-wrap">
            <select
              className="form-select as-project-select"
              aria-label="Select project"
              value={projectId ?? workspace?.projectId ?? ""}
              onChange={onNavbarProjectChange}
            >
              <option value="">— Select project —</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.slug})
                </option>
              ))}
            </select>
          </div>
          {authUser ? (
            <span className="text-white-50 small d-none d-lg-inline text-truncate flex-shrink-1" style={{ maxWidth: 140 }} title={authUser.email}>
              {authUser.display_name}
            </span>
          ) : null}
          <div className="position-relative flex-shrink-0" ref={notifDropdownRef}>
            <button
              type="button"
              className="btn btn-sm btn-outline-light position-relative"
              onClick={() => setShowNotifPanel((p) => !p)}
              title="Notifications"
              aria-expanded={showNotifPanel}
              aria-haspopup="dialog"
            >
              <i className="bi bi-bell" aria-hidden />
              {unreadNotifCount > 0 ? (
                <span className="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger px-1" style={{ fontSize: "0.65rem" }}>
                  {unreadNotifCount > 99 ? "99+" : unreadNotifCount}
                </span>
              ) : null}
            </button>
            {showNotifPanel ? (
              <div className="as-notif-panel shadow border rounded-3 bg-white text-dark" role="dialog" aria-label="Notifications">
                <div className="as-notif-panel-hd d-flex align-items-center justify-content-between gap-2 px-3 py-2 border-bottom">
                  <span className="fw-semibold small">Notifications</span>
                  <div className="d-flex gap-1 flex-shrink-0">
                    {notifications.length > 0 ? (
                      <>
                        <button type="button" className="btn btn-link btn-sm p-0 text-decoration-none" onClick={markAllNotificationsRead}>
                          Mark read
                        </button>
                        <button type="button" className="btn btn-link btn-sm p-0 text-decoration-none text-danger" onClick={clearAllNotifications}>
                          Clear
                        </button>
                      </>
                    ) : null}
                  </div>
                </div>
                <div className="as-notif-panel-bd overflow-y-auto">
                  {notifications.length === 0 ? (
                    <div className="px-3 py-4 text-center text-secondary small">No notifications yet. Story changes, comments, and @mentions appear here.</div>
                  ) : (
                    <ul className="list-unstyled mb-0">
                      {notifications.map((n) => (
                        <li key={n.id} className={`as-notif-item border-bottom ${n.read ? "opacity-75" : ""}`}>
                          <button
                            type="button"
                            className="as-notif-item-btn w-100 text-start btn btn-link text-decoration-none text-dark p-3 rounded-0"
                            onClick={() => {
                              markNotificationRead(n.id);
                              if (n.link) navigate(n.link);
                              setShowNotifPanel(false);
                            }}
                          >
                            <div className="d-flex gap-2">
                              <span className="as-notif-icon flex-shrink-0 text-primary">
                                <i className={`bi ${notificationIconClass(n.type)}`} aria-hidden />
                              </span>
                              <span className="min-w-0">
                                <div className="fw-semibold small">{n.title}</div>
                                {n.body ? <div className="small text-secondary text-truncate">{n.body}</div> : null}
                                <div className="small text-muted mt-1">{new Date(n.createdAt).toLocaleString()}</div>
                              </span>
                            </div>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            ) : null}
          </div>
          <button
            type="button"
            className="btn btn-sm btn-outline-light flex-shrink-0"
            onClick={() => {
              clearAuth();
              navigate("/login");
            }}
          >
            <i className="bi bi-box-arrow-right me-1" aria-hidden />
            Sign out
          </button>
        </div>
      </header>

      <div className="as-body">
        <aside className="as-sidenav">
          <div className="as-sidenav-label">Workspace</div>
          <button
            type="button"
            className={`as-nav-btn mb-1 ${mainTab === TABS.board.id || isStoryPage ? "active" : ""}`}
            disabled={!projectId}
            onClick={() => projectId && navigate(`/p/${projectId}/board`)}
          >
            <i className={TABS.board.icon} aria-hidden />
            {TABS.board.label}
          </button>
          <button
            type="button"
            className={`as-nav-btn mb-1 ${mainTab === TABS.team.id ? "active" : ""}`}
            onClick={() => (projectId ? navigate(`/p/${projectId}/team`) : navigate("/team"))}
          >
            <i className={TABS.team.icon} aria-hidden />
            {TABS.team.label}
          </button>
          <button
            type="button"
            className={`as-nav-btn mb-1 ${mainTab === TABS.chat.id ? "active" : ""}`}
            disabled={!projectId}
            onClick={() => projectId && navigate(`/p/${projectId}/chat`)}
          >
            <i className={TABS.chat.icon} aria-hidden />
            {TABS.chat.label}
          </button>
          <button
            type="button"
            className={`as-nav-btn mb-1 ${mainTab === TABS.releases.id ? "active" : ""}`}
            disabled={!projectId}
            onClick={() => projectId && navigate(`/p/${projectId}/releases`)}
            title="Create and manage releases (milestones)"
          >
            <i className={TABS.releases.icon} aria-hidden />
            {TABS.releases.label}
          </button>
          <button
            type="button"
            className={`as-nav-btn ${mainTab === TABS.settings.id ? "active" : ""}`}
            disabled={!projectId}
            onClick={() => projectId && navigate(`/p/${projectId}/settings`)}
          >
            <i className={TABS.settings.icon} aria-hidden />
            {TABS.settings.label}
          </button>
          <div className="as-sidenav-footer">
            {selectedProject ? (
              <>
                <strong>{selectedProject.name}</strong>
                <div className="text-truncate">{selectedProject.slug}</div>
              </>
            ) : (
              <>No project selected</>
            )}
          </div>
        </aside>

        <main className="as-main">
          {err && (
            <div className="alert alert-danger py-2 small mb-3" role="alert">
              {err}
            </div>
          )}

          {isStoryPage ? (
            <div className="as-story-page">
              {!workspace?.projectId || !workspace?.storyId ? (
                <div className="as-panel">
                  <div className="as-empty py-5">
                    <p className="mb-0 text-secondary">Invalid story URL.</p>
                  </div>
                </div>
              ) : !storyDetail || storyDetail.id !== workspace.storyId ? (
                <div className="d-flex align-items-center gap-2 text-secondary py-5">
                  <div className="spinner-border spinner-border-sm" role="status" aria-hidden />
                  <span>Loading story…</span>
                </div>
              ) : (
                <>
                  <div className="as-page-head d-flex flex-wrap align-items-center justify-content-between gap-2 mb-4">
                    <div className="d-flex flex-wrap align-items-center gap-2 min-w-0">
                      <button
                        type="button"
                        className="btn btn-outline-secondary btn-sm flex-shrink-0"
                        onClick={() => {
                          navigate(`/p/${workspace.projectId}/board`);
                          closeStoryDrawer();
                        }}
                      >
                        <i className="bi bi-arrow-left me-1" aria-hidden />
                        Back to board
                      </button>
                      <div className="min-w-0">
                        {storyDetail.story_key ? (
                          <div className="small text-secondary font-monospace mb-0">{storyDetail.story_key}</div>
                        ) : null}
                        <h1 className="as-page-title mb-0 text-truncate">{storyDetail.title}</h1>
                      </div>
                    </div>
                    <button
                      type="button"
                      className="btn btn-sm btn-outline-secondary flex-shrink-0"
                      title="Copy link to this story page"
                      onClick={() => {
                        const u = `${window.location.origin}${window.location.pathname}`;
                        navigator.clipboard?.writeText(u).catch(() => {});
                      }}
                    >
                      <i className="bi bi-link-45deg me-1" aria-hidden />
                      Copy link
                    </button>
                  </div>
                  <div className="as-panel">
                    <div className="as-panel-bd">
                      <StoryDetailBody
                        storyDetail={storyDetail}
                        statusEvents={storyStatusEventsById[storyDetail.id] || []}
                        comments={comments}
                        projectMembers={projectMembers}
                        releases={releases}
                        cmBody={cmBody}
                        setCmBody={setCmBody}
                        onPatchStoryStatus={onPatchStoryStatus}
                        onPatchStoryDetails={onPatchStoryDetails}
                        onPatchStoryRelease={onPatchStoryRelease}
                        onPatchStoryAssignees={onPatchStoryAssignees}
                        onPostComment={onPostComment}
                        onPatchComment={onPatchComment}
                        onDeleteComment={onDeleteComment}
                      />
                    </div>
                  </div>
                </>
              )}
            </div>
          ) : (
            <>
          {mainTab === "board" && (
            <>
              {!projectId ? (
                <>
                  <div className="as-page-head d-flex flex-wrap justify-content-between align-items-start gap-2">
                    <div>
                      <h1 className="as-page-title">Board</h1>
                      <p className="as-page-desc">Pick a project from the dropdown or open Projects in the top bar.</p>
                    </div>
                  </div>
                  <div className="as-panel">
                    <div className="as-empty">
                      <div className="as-empty-icon">
                        <i className="bi bi-columns-gap" />
                      </div>
                      <p className="mb-2">No project selected.</p>
                      <button type="button" className="btn btn-primary btn-sm" onClick={() => setShowProjectsHub(true)}>
                        Open project list
                      </button>
                    </div>
                  </div>
                </>
              ) : showCreateStory ? (
                <div className="as-create-story">
                  <div className="as-create-story-bar d-flex flex-wrap align-items-center justify-content-between gap-2 mb-4">
                    <button type="button" className="btn btn-outline-secondary" onClick={closeCreateStory}>
                      <i className="bi bi-arrow-left me-2" aria-hidden />
                      Back to board
                    </button>
                    <button type="button" className="btn btn-outline-secondary btn-sm" onClick={() => setShowProjectsHub(true)}>
                      <i className="bi bi-folder2 me-1" aria-hidden />
                      Switch project
                    </button>
                  </div>
                  <div className="as-create-story-hero mb-4">
                    <p className="as-create-story-kicker small text-secondary text-uppercase fw-semibold mb-2">New story</p>
                    <h1 className="as-page-title mb-2">Create story</h1>
                    <p className="as-page-desc mb-0">Add a new work item to the board.</p>
                    {!hasProjectWorkflow ? (
                      <p className="small text-warning mt-2 mb-0">
                        Select a workflow template in <strong>Project settings</strong> before creating stories.
                      </p>
                    ) : null}
                  </div>
                  <div className="as-panel as-create-story-panel mx-auto">
                    <div className="as-panel-bd">
                      <form onSubmit={onCreateStory} className="vstack gap-4">
                        <div>
                          <label className="form-label fw-semibold" htmlFor="as-new-story-title">
                            Title
                          </label>
                          <input
                            id="as-new-story-title"
                            className="form-control form-control-lg"
                            placeholder="Short summary of the value to deliver"
                            value={stTitle}
                            onChange={(e) => setStTitle(e.target.value)}
                            required
                            autoFocus
                          />
                        </div>
                        <div>
                          <label className="form-label fw-semibold" htmlFor="as-new-story-desc">
                            Description
                          </label>
                          <MarkdownEditorField
                            value={stDesc}
                            onChange={setStDesc}
                            height={260}
                            placeholder="Context, acceptance criteria, links... (optional)"
                            textareaProps={{ id: "as-new-story-desc" }}
                          />
                          <div className="form-text">Leave blank if details come later — you can edit the story anytime.</div>
                        </div>
                        <div>
                          <label className="form-label fw-semibold" htmlFor="as-new-story-status">
                            Initial status
                          </label>
                          <select id="as-new-story-status" className="form-select" value={stStatus} onChange={(e) => setStStatus(e.target.value)}>
                            {STORY_STATUSES.map((x) => (
                              <option key={x} value={x}>
                                {x}
                              </option>
                            ))}
                          </select>
                          <div className="form-text">Maps to Kanban columns (icebox / backlog / current / done).</div>
                        </div>
                        <div>
                          <label className="form-label fw-semibold" htmlFor="as-new-story-release">
                            Release (optional)
                          </label>
                          <select
                            id="as-new-story-release"
                            className="form-select"
                            value={stReleaseId}
                            onChange={(e) => setStReleaseId(e.target.value)}
                          >
                            <option value="">— None —</option>
                            {releases.map((r) => (
                              <option key={r.id} value={r.id}>
                                {r.name}
                              </option>
                            ))}
                          </select>
                          <div className="form-text">
                            If empty: open the <strong>Releases</strong> tab on the left to create one.
                          </div>
                        </div>
                        <div>
                          <label className="form-label fw-semibold" htmlFor="as-new-story-assignees">
                            Assignees (optional)
                          </label>
                          <select
                            id="as-new-story-assignees"
                            className="form-select"
                            multiple
                            size={Math.max(2, Math.min(8, projectMembers.length))}
                            value={stAssigneeIds}
                            onChange={(e) => setStAssigneeIds(Array.from(e.target.selectedOptions, (o) => o.value))}
                            aria-label="Assignees"
                          >
                            {projectMembers.map((row) => (
                              <option key={row.member_id} value={row.member_id}>
                                {row.member?.display_name ?? `Member #${row.member_id}`}
                                {row.member?.member_type === "ai" ? " (AI)" : ""}
                              </option>
                            ))}
                          </select>
                          <div className="form-text">Hold Cmd/Ctrl to select multiple project members.</div>
                        </div>
                        <div className="d-flex flex-wrap gap-2 pt-2 border-top">
                          <button className="btn btn-primary px-4" type="submit" disabled={!hasProjectWorkflow}>
                            Create story
                          </button>
                          <button type="button" className="btn btn-outline-secondary" onClick={closeCreateStory}>
                            Cancel
                          </button>
                        </div>
                      </form>
                    </div>
                  </div>
                </div>
              ) : (
                <>
                  <div className="as-page-head d-flex flex-wrap justify-content-between align-items-start gap-2">
                    <div>
                      <h1 className="as-page-title">Board</h1>
                      <p className="as-page-desc">{selectedProject ? "Manage stories on the Kanban board." : null}</p>
                    </div>
                    <div className="d-flex flex-wrap gap-2">
                      <button
                        type="button"
                        className="btn btn-outline-primary"
                        onClick={() => projectId && navigate(`/p/${projectId}/releases`)}
                        title="Create milestone / release"
                      >
                        <i className="bi bi-rocket-takeoff me-1" aria-hidden />
                        Releases
                      </button>
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={() => setShowCreateStory(true)}
                        disabled={!hasProjectWorkflow}
                        title={!hasProjectWorkflow ? "Select a workflow template in Project settings first" : undefined}
                      >
                        <i className="bi bi-plus-lg me-1" aria-hidden />
                        New story
                      </button>
                    </div>
                  </div>
                  <div className="as-panel">
                    <div className="as-panel-bd">
                      <KanbanBoard
                        stories={stories}
                        releaseNameById={releaseNameById}
                        memberNameById={memberNameById}
                        onMoveStory={(sid, status) => onPatchStoryStatus(sid, status)}
                        onOpenStory={(sid) => loadStory(sid).catch((e) => setErr(e.message))}
                      />
                    </div>
                  </div>
                </>
              )}
            </>
          )}

          {mainTab === "team" && (
            <>
              <div className="as-page-head">
                <h1 className="as-page-title">Team</h1>
                <p className="as-page-desc">Workspace members and assignment to the selected project.</p>
              </div>
              <div className="row g-4">
                <div className="col-lg-6">
                  <div className="as-panel h-100">
                    <div className="as-panel-hd">All members</div>
                    <div className="as-panel-bd p-0">
                      <div className="table-responsive">
                        <table className="table table-hover align-middle mb-0 small">
                          <thead className="table-light">
                            <tr>
                              <th className="ps-3">Name</th>
                              <th>Type</th>
                              <th className="pe-3 text-end">ID</th>
                            </tr>
                          </thead>
                          <tbody>
                            {members.map((m) => (
                              <tr key={m.id}>
                                <td className="ps-3 fw-medium">{m.display_name}</td>
                                <td className="text-secondary">
                                  {m.member_type}
                                  {m.agent_id ? ` · ${m.agent_id}` : ""}
                                </td>
                                <td className="pe-3 text-end text-muted">{m.id}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                    <div className="as-panel-bd border-top">
                      <div className="fw-semibold small mb-3">Add member</div>
                      <form onSubmit={onCreateMember} className="vstack gap-2">
                        <select className="form-select form-select-sm" value={mType} onChange={(e) => setMType(e.target.value)}>
                          <option value="human">human</option>
                          <option value="ai">ai</option>
                        </select>
                        <input className="form-control form-control-sm" placeholder="Display name" value={mName} onChange={(e) => setMName(e.target.value)} required />
                        {mType === "ai" && (
                          <input className="form-control form-control-sm" placeholder="agent_id" value={mAgent} onChange={(e) => setMAgent(e.target.value)} />
                        )}
                        <button className="btn btn-outline-primary btn-sm" type="submit">
                          Create member
                        </button>
                      </form>
                    </div>
                  </div>
                </div>
                <div className="col-lg-6">
                  <div className="as-panel h-100">
                    <div className="as-panel-hd">In project {selectedProject ? `«${selectedProject.slug}»` : "—"}</div>
                    {!projectId ? (
                      <div className="as-empty py-5">
                        <div className="as-empty-icon">
                          <i className="bi bi-diagram-3" />
                        </div>
                        Select a project from the dropdown or Projects in the top bar to assign members.
                      </div>
                    ) : (
                      <>
                        <ul className="list-group list-group-flush">
                          {projectMembers.map((row) => (
                            <li key={row.member_id} className="list-group-item d-flex justify-content-between align-items-center py-3">
                              <span>
                                <span className="fw-medium">{row.member?.display_name || `#${row.member_id}`}</span>
                                <span className="text-secondary small ms-2">{row.role}</span>
                              </span>
                              <button
                                type="button"
                                className="btn btn-outline-danger btn-sm"
                                onClick={() => onRemoveProjectMember(row.member_id)}
                              >
                                Remove
                              </button>
                            </li>
                          ))}
                        </ul>
                        <div className="as-panel-bd border-top">
                          <div className="fw-semibold small mb-3">Assign member</div>
                          <form onSubmit={onAddProjectMember} className="vstack gap-2">
                            <select className="form-select form-select-sm" value={addMemId} onChange={(e) => setAddMemId(e.target.value)} required>
                              <option value="">— Select member —</option>
                              {membersNotInProject.map((m) => (
                                <option key={m.id} value={m.id}>
                                  {m.display_name} ({m.member_type})
                                </option>
                              ))}
                            </select>
                            <input className="form-control form-control-sm" placeholder="Role" value={addRole} onChange={(e) => setAddRole(e.target.value)} />
                            <button className="btn btn-primary btn-sm" type="submit" disabled={!addMemId}>
                              Add to project
                            </button>
                          </form>
                          {apiCenterConnected ? (
                            <form onSubmit={onAddApiAgentToProject} className="vstack gap-2 mt-3 pt-3 border-top">
                              <div className="small fw-semibold">Assign AI agent from API Center</div>
                              <select
                                className="form-select form-select-sm"
                                value={selectedApiAgentId}
                                onChange={(e) => setSelectedApiAgentId(e.target.value)}
                              >
                                <option value="">— Select API Center agent —</option>
                                {apiAgentsNotInProject.map((a) => (
                                  <option key={a.id} value={a.id}>
                                    {(a.name || a.id) + (a.role ? ` · ${a.role}` : "")}
                                  </option>
                                ))}
                              </select>
                              <button className="btn btn-outline-primary btn-sm" type="submit" disabled={!selectedApiAgentId}>
                                Create/Use AI member and add
                              </button>
                            </form>
                          ) : (
                            <div className="small text-secondary mt-2">Connect API Center in Settings to load AI agents.</div>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}

          {mainTab === "master-data" && (
            <div className="as-page-head">
              <h1 className="as-page-title">Master data</h1>
            </div>
          )}

          {mainTab === "chat" && (
            <>
              <div className="as-page-head">
                <h1 className="as-page-title">Chat</h1>
                <p className="as-page-desc">Project channels chats.</p>
              </div>
              {!projectId ? (
                <div className="as-panel">
                  <div className="as-empty py-5">
                    <div className="as-empty-icon">
                      <i className="bi bi-chat-dots" />
                    </div>
                    <p className="mb-2">Select a project first to open chat channels.</p>
                    <button type="button" className="btn btn-primary btn-sm" onClick={() => setShowProjectsHub(true)}>
                      Open project
                    </button>
                  </div>
                </div>
              ) : (
                <div className="row g-3 align-items-stretch as-chat-layout">
                  <div className="col-12 col-lg-3">
                    <div className="as-panel as-chat-sidebar">
                      <div className="as-panel-hd d-flex align-items-center justify-content-between flex-shrink-0">
                        <span>Channels</span>
                        <span className="badge text-bg-light border">{chatChannelItems.length}</span>
                      </div>
                      <div className="list-group list-group-flush as-chat-channel-list">
                        {chatChannelItems.map((ch) => (
                          <button
                            key={ch.id}
                            type="button"
                            className={`list-group-item list-group-item-action py-2 as-chat-channel-item ${activeChatId === ch.id ? "active" : ""}`}
                            onClick={() => setActiveChatId(ch.id)}
                          >
                            <div className="fw-semibold d-flex align-items-center gap-2">
                              <i className={`bi ${ch.id === "general" ? "bi-hash" : "bi-person-circle"}`} aria-hidden />
                              <span>{ch.id === "general" ? "general" : ch.label}</span>
                            </div>
                            <div className={`small ${activeChatId === ch.id ? "text-white-50" : "text-secondary"}`}>{ch.subtitle}</div>
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                  <div className="col-12 col-lg-9">
                    <div className="as-panel d-flex flex-column as-chat-window">
                      <div className="as-panel-hd d-flex align-items-center justify-content-between as-chat-window-hd flex-shrink-0">
                        <div className="d-flex align-items-center gap-2 min-w-0">
                          <span className="as-chat-avatar">
                            <i className={`bi ${activeChatChannel?.id === "general" ? "bi-hash" : "bi-person-fill"}`} aria-hidden />
                          </span>
                          <div className="min-w-0">
                            <div className="fw-semibold text-truncate">{activeChatChannel?.id === "general" ? "general" : activeChatChannel?.label || "Chat"}</div>
                            <div className="small text-secondary text-truncate">{activeChatChannel?.subtitle || "Conversation"}</div>
                          </div>
                        </div>
                        <div className="d-flex align-items-center gap-1 flex-shrink-0">
                          <span className={`badge ${chatConnected ? "text-bg-success" : "text-bg-secondary"}`} title="Socket.IO chat-service">
                            {chatConnected ? "Live" : "Offline"}
                          </span>
                          {apiCenterConnected && apiCenterChatWsUrl ? (
                            <span
                              className={`badge ${apiCenterAgentWsReady ? "text-bg-success" : "text-bg-warning"}`}
                              title="WebSocket tới API Center (nhận reply agent)"
                            >
                              API {apiCenterAgentWsReady ? "WS" : "WS…"}
                            </span>
                          ) : apiCenterConnected && !apiCenterChatWsUrl ? (
                            <span
                              className="badge text-bg-danger"
                              title="Chưa có chat_ws trong Hub — mở Settings → Reconnect API Center để lưu endpoints."
                            >
                              API WS URL missing
                            </span>
                          ) : null}
                        </div>
                      </div>
                      <div ref={chatMessagesScrollRef} className="as-panel-bd flex-grow-1 as-chat-messages-wrap">
                        <div className="vstack gap-2 as-chat-messages">
                          {activeChatMessages.map((message) => {
                            const mine = myChatUserId > 0 && Number(message.senderUserId) === myChatUserId;
                            return (
                              <div key={message.id} className={`as-chat-msg-row ${mine ? "mine" : ""}`}>
                                <div className={`as-chat-msg-bubble ${mine ? "mine" : ""}${mine ? " as-chat-msg-bubble--mine-actions" : ""}`}>
                                  {mine ? (
                                    <button
                                      type="button"
                                      className="as-chat-msg-delete"
                                      aria-label="Remove message"
                                      title="Remove message"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        onDeleteChatMessage(message).catch((er) => setErr(er.message));
                                      }}
                                    >
                                      <i className="bi bi-trash" aria-hidden />
                                    </button>
                                  ) : null}
                                  <div className="small fw-semibold as-chat-msg-author">
                                    {resolveChatSenderDisplayName(message.senderUserId, message.senderName)}
                                  </div>
                                  <div className="small">{renderChatMessageContent(message.content)}</div>
                                  <div className={`small as-chat-msg-time ${mine ? "text-dark" : "text-secondary"}`}>
                                    {formatChatMessageTime(message.createdAt)}
                                  </div>
                                  <div className="as-chat-reactions mt-1">
                                    {(message.reactions || [])
                                      .filter((x) => Number(x.count || 0) > 0)
                                      .map((stat) => {
                                        const r = CHAT_REACTIONS.find((x) => x.type === stat.type);
                                        if (!r) return null;
                                        return (
                                          <button
                                            key={r.type}
                                            type="button"
                                            className={`btn btn-sm ${stat.mine ? "btn-primary" : "btn-outline-secondary"} as-chat-react-chip`}
                                            title={r.label}
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              onReactChatMessage(message, r.type).catch((er) => setErr(er.message));
                                            }}
                                          >
                                            <i className={`bi ${r.icon}`} aria-hidden /> <span>{Number(stat.count || 0)}</span>
                                          </button>
                                        );
                                      })}
                                  </div>
                                  {!mine ? (
                                    <div className="as-chat-reaction-quick mt-1">
                                      {CHAT_REACTIONS.map((r) => {
                                        const stat = (message.reactions || []).find((x) => x.type === r.type);
                                        const mineReact = Boolean(stat?.mine);
                                        return (
                                          <button
                                            key={r.type}
                                            type="button"
                                            className={`btn btn-sm ${mineReact ? "btn-primary" : "btn-outline-secondary"} as-chat-react-btn`}
                                            title={r.label}
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              onReactChatMessage(message, r.type).catch((er) => setErr(er.message));
                                            }}
                                          >
                                            <i className={`bi ${r.icon}`} aria-hidden />
                                          </button>
                                        );
                                      })}
                                    </div>
                                  ) : null}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                      <div className="as-panel-bd border-top as-chat-compose flex-shrink-0">
                        {mentionSuggestions.length > 0 ? (
                          <div className="as-chat-mention-suggest mb-2">
                            {mentionSuggestions.map((m) => (
                              <button key={m.id} type="button" className="btn btn-sm btn-outline-secondary" onClick={() => onPickMention(m.name)}>
                                @{mentionKeyFromName(m.name)}
                              </button>
                            ))}
                          </div>
                        ) : null}
                        <div className="input-group as-chat-input-group">
                          <span className="input-group-text bg-white align-items-start pt-2">
                            <i className="bi bi-chat-text text-secondary" aria-hidden />
                          </span>
                          <textarea
                            className="form-control as-chat-textarea"
                            rows={2}
                            placeholder="Type your message... (Enter send, Shift+Enter newline)"
                            value={chatInput}
                            onChange={(e) => {
                              setChatInput(e.target.value);
                              emitTyping(true);
                              if (chatTypingStopTimerRef.current) clearTimeout(chatTypingStopTimerRef.current);
                              chatTypingStopTimerRef.current = setTimeout(() => emitTyping(false), 1400);
                            }}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" && !e.shiftKey) {
                                e.preventDefault();
                                onSendChatMessage().catch((er) => setErr(er.message));
                              }
                            }}
                          />
                          <button
                            className="btn btn-primary d-flex align-items-center gap-1 align-self-stretch"
                            type="button"
                            disabled={!chatInput.trim() || !chatConnected}
                            onClick={() => onSendChatMessage().catch((er) => setErr(er.message))}
                          >
                            <i className="bi bi-send" aria-hidden />
                            <span>Send</span>
                          </button>
                        </div>
                      </div>
                      {activeTypingRows.length > 0 ? (
                        <div className="as-chat-typing px-3 pb-2 small text-secondary">
                          {activeTypingRows
                            .map((x) => resolveChatSenderDisplayName(x.senderUserId, x.senderName))
                            .slice(0, 3)
                            .join(", ")}
                          {" is typing..."}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {mainTab === "releases" && (
            <>
              <div className="as-page-head d-flex flex-wrap justify-content-between align-items-start gap-2">
                <div>
                  <h1 className="as-page-title">Releases</h1>
                  <p className="as-page-desc mb-0">
                    Create milestones and assign them to stories on the Board or in story details.
                  </p>
                </div>
                {projectId ? (
                  <button type="button" className="btn btn-outline-secondary btn-sm flex-shrink-0" onClick={() => setShowProjectsHub(true)}>
                    <i className="bi bi-folder2 me-1" aria-hidden />
                    Switch project
                  </button>
                ) : null}
              </div>
              {!projectId ? (
                <div className="as-panel">
                  <div className="as-empty">
                    <div className="as-empty-icon">
                      <i className="bi bi-rocket-takeoff" />
                    </div>
                    <p className="mb-2">Select a project (dropdown above) to create a release.</p>
                    <button type="button" className="btn btn-primary btn-sm" onClick={() => setShowProjectsHub(true)}>
                      Open project
                    </button>
                  </div>
                </div>
              ) : (
                <div className="as-panel">
                  <div className="as-panel-hd">Create release</div>
                  <div className="as-panel-bd">
                    <form onSubmit={onCreateRelease} className="vstack gap-3 mb-4">
                      <div className="row g-3">
                        <div className="col-12 col-md-6">
                          <label className="form-label small text-secondary mb-1" htmlFor="as-new-release-name">
                            Name
                          </label>
                          <input
                            id="as-new-release-name"
                            className="form-control"
                            value={newReleaseName}
                            onChange={(e) => setNewReleaseName(e.target.value)}
                            placeholder="v1.0, Sprint 12, …"
                            maxLength={255}
                            required
                          />
                        </div>
                        <div className="col-12 col-md-3">
                          <label className="form-label small text-secondary mb-1" htmlFor="as-new-release-status">
                            Status
                          </label>
                          <select
                            id="as-new-release-status"
                            className="form-select"
                            value={newRelStatus}
                            onChange={(e) => setNewRelStatus(e.target.value)}
                          >
                            {RELEASE_STATUSES.map((s) => (
                              <option key={s} value={s}>
                                {s}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div className="col-12">
                          <label className="form-label small text-secondary mb-1" htmlFor="as-new-release-desc">
                            Description (optional)
                          </label>
                          <input
                            id="as-new-release-desc"
                            className="form-control"
                            value={newRelDesc}
                            onChange={(e) => setNewRelDesc(e.target.value)}
                            maxLength={2000}
                          />
                        </div>
                        <div className="col-12">
                          <span className="form-label small text-secondary d-block mb-1">Planning window (optional)</span>
                          <div className="btn-group flex-wrap" role="group" aria-label="Date mode">
                            <input
                              type="radio"
                              className="btn-check"
                              name="newRelDateMode"
                              id="nrd-none"
                              autoComplete="off"
                              checked={newRelDateMode === "none"}
                              onChange={() => setNewRelDateMode("none")}
                            />
                            <label className="btn btn-outline-secondary btn-sm" htmlFor="nrd-none">
                              None
                            </label>
                            <input
                              type="radio"
                              className="btn-check"
                              name="newRelDateMode"
                              id="nrd-day"
                              autoComplete="off"
                              checked={newRelDateMode === "day"}
                              onChange={() => setNewRelDateMode("day")}
                            />
                            <label className="btn btn-outline-secondary btn-sm" htmlFor="nrd-day">
                              One day
                            </label>
                            <input
                              type="radio"
                              className="btn-check"
                              name="newRelDateMode"
                              id="nrd-range"
                              autoComplete="off"
                              checked={newRelDateMode === "range"}
                              onChange={() => setNewRelDateMode("range")}
                            />
                            <label className="btn btn-outline-secondary btn-sm" htmlFor="nrd-range">
                              From–to
                            </label>
                          </div>
                          {newRelDateMode === "day" ? (
                            <input
                              type="date"
                              className="form-control form-control-sm mt-2"
                              value={newRelDay}
                              onChange={(e) => setNewRelDay(e.target.value)}
                            />
                          ) : null}
                          {newRelDateMode === "range" ? (
                            <div className="d-flex flex-wrap align-items-center gap-2 mt-2">
                              <input
                                type="date"
                                className="form-control form-control-sm"
                                style={{ maxWidth: 180 }}
                                value={newRelStart}
                                onChange={(e) => setNewRelStart(e.target.value)}
                                aria-label="Start"
                              />
                              <span className="text-secondary small">→</span>
                              <input
                                type="date"
                                className="form-control form-control-sm"
                                style={{ maxWidth: 180 }}
                                value={newRelEnd}
                                onChange={(e) => setNewRelEnd(e.target.value)}
                                aria-label="End"
                              />
                            </div>
                          ) : null}
                          <div className="form-text">One day fills that calendar day. From–to uses start (00:00) and end (end of end date).</div>
                        </div>
                        <div className="col-12">
                          <button className="btn btn-primary" type="submit" disabled={!newReleaseName.trim()}>
                            Create release
                          </button>
                        </div>
                      </div>
                    </form>
                    <h2 className="h6 text-secondary border-top pt-3 mt-1 mb-3">Created</h2>
                    {releases.length === 0 ? (
                      <p className="small text-secondary mb-0">
                        No releases yet. Enter a name above and click Create release.
                      </p>
                    ) : (
                      <div className="table-responsive">
                        <table className="table table-sm align-middle mb-0">
                          <thead>
                            <tr>
                              <th>Name</th>
                              <th>Status</th>
                              <th>Window</th>
                              <th className="text-end">Actions</th>
                            </tr>
                          </thead>
                          <tbody>
                            {releases.map((r) =>
                              editingReleaseId === r.id ? (
                                <tr key={r.id}>
                                  <td colSpan={4} className="bg-light">
                                    <form
                                      onSubmit={onSaveEditRelease}
                                      className="p-2 vstack gap-2"
                                      onClick={(e) => e.stopPropagation()}
                                    >
                                      <div className="row g-2">
                                        <div className="col-12 col-md-4">
                                          <label className="form-label small mb-0" htmlFor={`er-name-${r.id}`}>
                                            Name
                                          </label>
                                          <input
                                            id={`er-name-${r.id}`}
                                            className="form-control form-control-sm"
                                            value={editName}
                                            onChange={(e) => setEditName(e.target.value)}
                                            maxLength={255}
                                            required
                                          />
                                        </div>
                                        <div className="col-6 col-md-2">
                                          <label className="form-label small mb-0" htmlFor={`er-st-${r.id}`}>
                                            Status
                                          </label>
                                          <select
                                            id={`er-st-${r.id}`}
                                            className="form-select form-select-sm"
                                            value={editStatus}
                                            onChange={(e) => setEditStatus(e.target.value)}
                                          >
                                            {RELEASE_STATUSES.map((s) => (
                                              <option key={s} value={s}>
                                                {s}
                                              </option>
                                            ))}
                                          </select>
                                        </div>
                                        <div className="col-12 col-md-6">
                                          <label className="form-label small mb-0" htmlFor={`er-d-${r.id}`}>
                                            Description
                                          </label>
                                          <input
                                            id={`er-d-${r.id}`}
                                            className="form-control form-control-sm"
                                            value={editDesc}
                                            onChange={(e) => setEditDesc(e.target.value)}
                                          />
                                        </div>
                                      </div>
                                      <div>
                                        <span className="form-label small d-block mb-1">Window</span>
                                        <div className="btn-group flex-wrap" role="group">
                                          {["none", "day", "range"].map((mode) => (
                                            <div key={mode} className="d-inline">
                                              <input
                                                type="radio"
                                                className="btn-check"
                                                name={`editRelMode-${r.id}`}
                                                id={`e-${mode}-${r.id}`}
                                                autoComplete="off"
                                                checked={editDateMode === mode}
                                                onChange={() => setEditDateMode(mode)}
                                              />
                                              <label
                                                className="btn btn-outline-secondary btn-sm"
                                                htmlFor={`e-${mode}-${r.id}`}
                                              >
                                                {mode === "none" ? "None" : mode === "day" ? "One day" : "From–to"}
                                              </label>
                                            </div>
                                          ))}
                                        </div>
                                        {editDateMode === "day" ? (
                                          <input
                                            type="date"
                                            className="form-control form-control-sm mt-1"
                                            value={editDay}
                                            onChange={(e) => setEditDay(e.target.value)}
                                          />
                                        ) : null}
                                        {editDateMode === "range" ? (
                                          <div className="d-flex flex-wrap gap-1 align-items-center mt-1">
                                            <input
                                              type="date"
                                              className="form-control form-control-sm"
                                              style={{ maxWidth: 150 }}
                                              value={editStart}
                                              onChange={(e) => setEditStart(e.target.value)}
                                            />
                                            <span className="small">→</span>
                                            <input
                                              type="date"
                                              className="form-control form-control-sm"
                                              style={{ maxWidth: 150 }}
                                              value={editEnd}
                                              onChange={(e) => setEditEnd(e.target.value)}
                                            />
                                          </div>
                                        ) : null}
                                      </div>
                                      <div className="d-flex flex-wrap gap-2">
                                        <button type="submit" className="btn btn-primary btn-sm">
                                          Save
                                        </button>
                                        <button
                                          type="button"
                                          className="btn btn-outline-secondary btn-sm"
                                          onClick={cancelEditRelease}
                                        >
                                          Cancel
                                        </button>
                                      </div>
                                    </form>
                                  </td>
                                </tr>
                              ) : (
                                <tr key={r.id}>
                                  <td className="fw-medium">{r.name}</td>
                                  <td className="text-secondary small text-capitalize">{r.status}</td>
                                  <td className="text-secondary small font-monospace">
                                    {formatReleasePeriod(r)}
                                  </td>
                                  <td className="text-end text-nowrap">
                                    <button
                                      type="button"
                                      className="btn btn-outline-primary btn-sm me-1"
                                      onClick={() => beginEditRelease(r)}
                                    >
                                      Edit
                                    </button>
                                    <button
                                      type="button"
                                      className="btn btn-outline-danger btn-sm"
                                      onClick={() => onDeleteRelease(r.id)}
                                    >
                                      Delete
                                    </button>
                                  </td>
                                </tr>
                              )
                            )}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          )}

          {mainTab === "settings" && (
            <div className="as-settings-layout">
              <div className="as-page-head d-flex flex-wrap justify-content-between align-items-start gap-2">
                <div>
                  <h1 className="as-page-title">Project settings</h1>
                  <p className="as-page-desc">
                    {selectedProject ? (
                      <>
                        {selectedProject.name} · <span className="text-secondary">{selectedProject.slug}</span>
                      </>
                    ) : (
                      "Select a project to configure GitHub, Slack/Discord, document storage, and workspace."
                    )}
                  </p>
                </div>
                {projectId && (
                  <button type="button" className="btn btn-outline-secondary btn-sm flex-shrink-0" onClick={() => setShowProjectsHub(true)}>
                    <i className="bi bi-folder2 me-1" aria-hidden />
                    Switch project
                  </button>
                )}
              </div>
              {!projectId ? (
                <div className="as-panel">
                  <div className="as-empty">
                    <div className="as-empty-icon">
                      <i className="bi bi-gear" />
                    </div>
                    <p className="mb-0">Select a project to edit settings.</p>
                  </div>
                </div>
              ) : (
                <div className="as-panel">
                  <div className="as-panel-hd">Workflow settings</div>
                  <div className="as-panel-bd">
                    <form onSubmit={onSaveProjectSettings} className="vstack gap-4">
                      <div>
                        <h2 className="h6 fw-semibold border-bottom pb-2 mb-3">Workflow template</h2>
                        <label className="form-label small text-secondary" htmlFor="as-set-workflow-template">
                          Workflow template
                        </label>
                        <select
                          id="as-set-workflow-template"
                          className="form-select"
                          value={projWorkflowTemplateId}
                          onChange={(e) => setProjWorkflowTemplateId(e.target.value)}
                        >
                          <option value="">— Select workflow template —</option>
                          {workflowTemplates.map((wf) => (
                            <option key={wf.id} value={wf.id}>
                              {wf.name}
                            </option>
                          ))}
                        </select>
                        <div className="form-text">
                          Required for story operations. If not selected, creating/updating stories is blocked.
                        </div>
                      </div>
                      <div>
                        <h2 className="h6 fw-semibold border-bottom pb-2 mb-3">Storage overview</h2>
                        <label className="form-label small text-secondary" htmlFor="as-set-storage-overview">
                          Where all data of project is stored
                        </label>
                        <MarkdownEditorField
                          value={projStorageOverview}
                          onChange={setProjStorageOverview}
                          height={300}
                          placeholder={`Example:\n- Source code: github.com/org/repo (branching model ...)\n- Folder structure: /apps, /services, /infra\n- Product docs: docs/product/\n- Technical docs: docs/architecture/\n- Release notes: docs/releases/\n- Release checklist: docs/releases/checklist.md\n- Deployment scripts: infra/deploy/\n- Runbooks: docs/runbooks/`}
                          textareaProps={{ id: "as-set-storage-overview" }}
                        />
                        <div className="form-text">
                          Write down all storage locations: repo, folder structure, product/tech docs, release notes, release checklist, source code, and any project-related data.
                        </div>
                      </div>
                      <div>
                        <h2 className="h6 fw-semibold border-bottom pb-2 mb-3">API Center integration</h2>
                        <div className="vstack gap-2">
                          <input
                            className="form-control"
                            placeholder="API Center endpoint (e.g. http://127.0.0.1:18881)"
                            value={apiCenterEndpoint}
                            onChange={(e) => setApiCenterEndpoint(e.target.value)}
                            required
                          />
                          <input
                            type="password"
                            className="form-control"
                            placeholder="Connect secret"
                            value={apiCenterSecret}
                            onChange={(e) => setApiCenterSecret(e.target.value)}
                            required={!apiCenterConnected}
                          />
                          <div className="d-flex align-items-center gap-2">
                            <button
                              type="button"
                              className="btn btn-outline-primary btn-sm"
                              disabled={!apiCenterEndpoint.trim()}
                              onClick={() => onConnectApiCenter().catch((e) => setErr(e.message))}
                            >
                              {apiCenterConnected ? "Reconnect" : "Connect"}
                            </button>
                            <span className={`small ${apiCenterConnected ? "text-success" : "text-secondary"}`}>
                              {apiCenterConnected ? "Connected" : "Not connected"}
                            </span>
                          </div>
                        </div>
                        {apiCenterConnected ? (
                          <div className="border rounded p-2 mt-3 bg-light-subtle">
                            <input
                              className="form-control form-control-sm"
                              placeholder="Hub base http://host:9120 hoặc MCP tools http://host:9121/mcp (API Center tự suy URL còn lại)"
                              value={apiCenterMcpUrl}
                              onChange={(e) => setApiCenterMcpUrl(e.target.value)}
                            />
                            <div className="form-text small text-secondary mt-1">
                              Sau khi Allow, API Center ghi MCP vào config của các agent trong agents.json (cần restart gateway nếu đang chạy).
                            </div>
                            <div className="d-flex align-items-center gap-2 mt-2 flex-wrap">
                              <button
                                type="button"
                                className="btn btn-primary btn-sm"
                                disabled={!apiCenterMcpUrl.trim()}
                                onClick={onAllowApiCenterMcp}
                              >
                                Allow access MCP
                              </button>
                              {apiCenterHasMcpKey ? (
                                <span className="small text-success">MCP key stored ({apiCenterMcpMasked || "masked"})</span>
                              ) : (
                                <span className="small text-secondary">No MCP key stored yet.</span>
                              )}
                            </div>
                          </div>
                        ) : null}
                      </div>
                      <div className="as-settings-actions">
                        <span className="small text-secondary d-none d-md-inline">Review before saving.</span>
                        <div className="as-settings-actions-end">
                          {settingsSaved && <span className="small text-success">Saved.</span>}
                          <button type="submit" className="btn btn-primary px-4">
                            Save settings
                          </button>
                        </div>
                      </div>
                    </form>
                  </div>
                </div>
              )}
            </div>
          )}
            </>
          )}
        </main>
      </div>

      {showProjectsHub && (
        <>
          <div className="as-hub-backdrop" role="presentation" onClick={closeProjectsHub} aria-hidden />
          <aside className="as-hub-drawer" aria-label="Project list">
            <div className="as-hub-hd">
              <div>
                <div className="fw-semibold">Projects</div>
                <div className="small text-secondary">Pick an existing project or create a new one</div>
              </div>
              <button type="button" className="btn btn-sm btn-outline-secondary" onClick={closeProjectsHub} aria-label="Close">
                <i className="bi bi-x-lg" />
              </button>
            </div>
            <div className="as-hub-bd">
              <div className="as-panel mb-4">
                <div className="as-panel-hd">All projects</div>
                <div className="list-group list-group-flush rounded-0 border-0">
                  {projects.length === 0 ? (
                    <div className="as-empty border-0 py-4">
                      <div className="as-empty-icon">
                        <i className="bi bi-inbox" />
                      </div>
                      No projects yet. Create your first one below.
                    </div>
                  ) : (
                    projects.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        className={`list-group-item list-group-item-action d-flex justify-content-between align-items-start py-3 px-3 ${
                          p.id === projectId ? "active" : ""
                        }`}
                        onClick={() => onPickProjectFromHub(p.id)}
                      >
                        <div className="text-start">
                          <div className="fw-semibold">{p.name}</div>
                          <div className="small opacity-75">{p.slug}</div>
                        </div>
                        <i className="bi bi-chevron-right opacity-50" aria-hidden />
                      </button>
                    ))
                  )}
                </div>
              </div>
              <div className="as-panel">
                <div className="as-panel-hd">New project</div>
                <div className="as-panel-bd">
                  <form onSubmit={onCreateProject} className="vstack gap-3">
                    <div>
                      <label className="form-label small text-secondary mb-1">Slug (URL id)</label>
                      <input className="form-control" value={slug} onChange={(e) => setSlug(e.target.value)} required placeholder="my-product" />
                    </div>
                    <div>
                      <label className="form-label small text-secondary mb-1">Display name</label>
                      <input className="form-control" value={pname} onChange={(e) => setPname(e.target.value)} required placeholder="My product" />
                    </div>
                    <div>
                      <label className="form-label small text-secondary mb-1">workspace_ref (optional)</label>
                      <input
                        className="form-control"
                        value={wsRef}
                        onChange={(e) => setWsRef(e.target.value)}
                        placeholder="projects/my-app"
                      />
                    </div>
                    <button className="btn btn-primary" type="submit">
                      Create project
                    </button>
                  </form>
                </div>
              </div>
            </div>
          </aside>
        </>
      )}

      {mainTab === "master-data" && (
        <>
          <div className="as-hub-backdrop" role="presentation" onClick={closeMasterDataHub} aria-hidden />
          <aside className="as-hub-drawer" aria-label="Master data">
            <div className="as-hub-hd">
              <div>
                <div className="fw-semibold">Master data</div>
                <div className="small text-secondary">Workflow templates (global, not bound to a project)</div>
              </div>
              <button type="button" className="btn btn-sm btn-outline-secondary" onClick={closeMasterDataHub} aria-label="Close">
                <i className="bi bi-x-lg" />
              </button>
            </div>
            <div className="as-hub-bd">
              <div className="as-panel mb-4">
                <div className="as-panel-hd d-flex align-items-center justify-content-between">
                  <span>Workflow templates</span>
                  <span className="badge text-bg-light border">{workflowTemplates.length}</span>
                </div>
                <div className="as-panel-bd p-0">
                  {workflowTemplates.length === 0 ? (
                    <div className="as-empty border-0 py-4">
                      <div className="as-empty-icon">
                        <i className="bi bi-diagram-3" />
                      </div>
                      No workflow templates yet.
                    </div>
                  ) : (
                    <div className="list-group list-group-flush rounded-0 border-0">
                      {workflowTemplates.map((wf) => (
                        <div key={wf.id} className="list-group-item py-3 px-3">
                          <div className="fw-semibold">{wf.name}</div>
                          <div className="small text-secondary mt-1">{wf.description || "—"}</div>
                          <div className="small text-muted mt-1">{new Date(wf.created_at).toLocaleString()}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <div className="as-panel">
                <div className="as-panel-hd">Create workflow template</div>
                <div className="as-panel-bd">
                  <form className="vstack gap-3" onSubmit={onCreateWorkflowTemplate}>
                    <div>
                      <label className="form-label small text-secondary mb-1">Workflow template name</label>
                      <input
                        className="form-control"
                        value={wfName}
                        onChange={(e) => setWfName(e.target.value)}
                        placeholder="VD: Delivery lifecycle"
                        maxLength={255}
                        required
                      />
                    </div>
                    <div>
                      <label className="form-label small text-secondary mb-1">Description</label>
                      <MarkdownEditorField
                        value={wfDesc}
                        onChange={setWfDesc}
                        height={180}
                        placeholder="Short description of the workflow..."
                      />
                    </div>
                    <button className="btn btn-primary" type="submit" disabled={!wfName.trim()}>
                      Create workflow template
                    </button>
                  </form>
                </div>
              </div>
            </div>
          </aside>
        </>
      )}

      {storyDetail && !isStoryPage && (
        <>
          <div className="as-drawer-backdrop" role="presentation" onClick={closeStoryDrawer} aria-hidden />
          <aside className="as-drawer" aria-label="Story details">
            <div className="as-drawer-hd">
              <div className="min-w-0 flex-grow-1">
                {storyDetail.story_key ? (
                  <div className="small text-white-50 font-monospace text-truncate mb-0">{storyDetail.story_key}</div>
                ) : null}
                <span className="fw-semibold text-truncate d-block">{storyDetail.title}</span>
              </div>
              {projectId ? (
                <button
                  type="button"
                  className="btn btn-sm btn-outline-primary flex-shrink-0"
                  title="Open full story page (shareable URL)"
                  onClick={() => navigate(`/p/${projectId}/story/${storyDetail.id}`)}
                >
                  <i className="bi bi-box-arrow-up-right me-1" aria-hidden />
                  Full page
                </button>
              ) : null}
              <button type="button" className="btn btn-sm btn-outline-secondary flex-shrink-0" onClick={closeStoryDrawer} aria-label="Close">
                <i className="bi bi-x-lg" />
              </button>
            </div>
            <div className="as-drawer-bd">
              <StoryDetailBody
                storyDetail={storyDetail}
                statusEvents={storyStatusEventsById[storyDetail.id] || []}
                comments={comments}
                projectMembers={projectMembers}
                releases={releases}
                cmBody={cmBody}
                setCmBody={setCmBody}
                onPatchStoryStatus={onPatchStoryStatus}
                onPatchStoryDetails={onPatchStoryDetails}
                onPatchStoryRelease={onPatchStoryRelease}
                onPatchStoryAssignees={onPatchStoryAssignees}
                onPostComment={onPostComment}
                onPatchComment={onPatchComment}
                onDeleteComment={onDeleteComment}
              />
            </div>
          </aside>
        </>
      )}
    </div>
  );
}
