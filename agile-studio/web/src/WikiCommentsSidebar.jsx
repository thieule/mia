import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPost, getStoredUser } from "./api.js";
import { mentionKeyFromName } from "./mentionText.jsx";
import { renderMarkdownWithMentions } from "./markdownWithMentions.jsx";
import { buildWikiTextAnchor, resolveWikiTextAnchor } from "./wikiCommentAnchor.js";

function formatDt(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
  } catch {
    return iso;
  }
}

function excerptForQuotePlain(text, maxLen = 420) {
  const t = (text || "").trim().replace(/\s+/g, " ");
  if (t.length > maxLen) return `${t.slice(0, maxLen - 1)}…`;
  return t;
}

/** Thời điểm “hoạt động” của một comment (sửa / trả lời cập nhật updated_at). */
function commentActivityTs(c) {
  if (!c) return 0;
  const raw = c.updated_at || c.created_at;
  const x = new Date(raw || 0).getTime();
  return Number.isNaN(x) ? 0 : x;
}

/** Thread: max(activity) trên root + mọi reply — thread có reply mới nhảy lên đầu danh sách. */
function threadActivityTs(bundle) {
  const { root, replies } = bundle || {};
  let m = commentActivityTs(root);
  for (const r of replies || []) {
    m = Math.max(m, commentActivityTs(r));
  }
  return m;
}

/** Non-empty selection wholly inside this comment card (if user highlighted before Quote). */
function getQuoteSnippetFromComment(commentId) {
  if (!commentId || typeof document === "undefined") return "";
  /* Body only — selection must overlap stored comment.content, not header / quoted block. */
  const root = document.querySelector(`[data-as-wiki-cmt-body="${commentId}"]`);
  if (!root) return "";
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return "";
  const range = sel.getRangeAt(0);
  try {
    if (!root.contains(range.commonAncestorContainer)) return "";
  } catch {
    return "";
  }
  const text = sel.toString().trim();
  return text;
}

export default function WikiCommentsSidebar({
  projectId,
  docId,
  markdownBody,
  mdSelection,
  onClearMdSelection,
  onFocusMarkdownRange,
  setErr,
  /** Collapse the feedback column (wider document area). */
  onCollapseSidebar,
  /** Refresh parent feedback badge (e.g. after create / edit / resolve). */
  onCommentsInvalidate,
}) {
  const [comments, setComments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [threadTotals, setThreadTotals] = useState({ open: 0, resolved: 0 });
  const [includeResolved, setIncludeResolved] = useState(false);
  const [newBody, setNewBody] = useState("");
  const [replyParentId, setReplyParentId] = useState(null);
  /** Reply quoting another message in the same thread (server stores snapshot). */
  const [quotedRef, setQuotedRef] = useState(null);
  const [activeThreadId, setActiveThreadId] = useState(null);
  const [editDraft, setEditDraft] = useState({ id: "", text: "" });
  const [projectMembers, setProjectMembers] = useState([]);

  const me = getStoredUser()?.member_id;
  const setErrRef = useRef(setErr);
  setErrRef.current = setErr;
  /** Bumped on each load start; also bump after local mutations so stale in-flight GET cannot restore removed rows. */
  const loadGenRef = useRef(0);

  useEffect(() => {
    if (!projectId) {
      setProjectMembers([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const pm = await apiGet(`/projects/${projectId}/members`);
        if (!cancelled) setProjectMembers(Array.isArray(pm) ? pm : []);
      } catch {
        if (!cancelled) setProjectMembers([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const mentionMembers = useMemo(
    () =>
      projectMembers
        .filter((row) => row && row.member_id != null && row.member?.display_name)
        .map((row) => ({
          id: row.member_id,
          name: row.member.display_name,
        })),
    [projectMembers],
  );

  const mentionIndex = useMemo(() => {
    const map = new Map();
    for (const m of mentionMembers) {
      map.set(mentionKeyFromName(m.name), m.name);
    }
    return map;
  }, [mentionMembers]);

  const newBodyMentionSuggestions = useMemo(() => {
    const m = newBody.match(/(?:^|\s)@([^\s@]*)$/);
    if (!m) return [];
    const q = (m[1] || "").toLowerCase();
    return mentionMembers.filter((x) => mentionKeyFromName(x.name).includes(q)).slice(0, 8);
  }, [newBody, mentionMembers]);

  const editMentionSuggestions = useMemo(() => {
    const m = editDraft.text.match(/(?:^|\s)@([^\s@]*)$/);
    if (!m) return [];
    const q = (m[1] || "").toLowerCase();
    return mentionMembers.filter((x) => mentionKeyFromName(x.name).includes(q)).slice(0, 8);
  }, [editDraft.text, mentionMembers]);

  const pickNewMention = useCallback((displayName) => {
    const tok = `@${mentionKeyFromName(displayName)}`;
    setNewBody((prev) => prev.replace(/(?:^|\s)@([^\s@]*)$/, (all) => all.replace(/@([^\s@]*)$/, `${tok} `)));
  }, []);

  const pickEditMention = useCallback((displayName) => {
    const tok = `@${mentionKeyFromName(displayName)}`;
    setEditDraft((p) => ({
      ...p,
      text: p.text.replace(/(?:^|\s)@([^\s@]*)$/, (all) => all.replace(/@([^\s@]*)$/, `${tok} `)),
    }));
  }, []);

  const load = useCallback(async () => {
    if (!projectId || !docId) return;
    const gen = ++loadGenRef.current;
    setLoading(true);
    const qs = includeResolved ? "?include_resolved=true" : "";
    const noCache = { cache: "no-store" };
    try {
      const rows = await apiGet(`/projects/${projectId}/docs/${docId}/comments${qs}`, noCache);
      if (gen !== loadGenRef.current) return;
      setComments(Array.isArray(rows) ? rows : []);
    } catch (e) {
      if (gen === loadGenRef.current) setErrRef.current?.(e?.message || String(e));
    } finally {
      if (gen === loadGenRef.current) setLoading(false);
    }
    try {
      const cnt = await apiGet(`/projects/${projectId}/docs/${docId}/comments/count`, noCache);
      if (gen !== loadGenRef.current) return;
      setThreadTotals({
        open: cnt?.open_thread_count ?? 0,
        resolved: cnt?.resolved_thread_count ?? 0,
      });
    } catch {
      /* Count must not block list refresh (Promise.all hid new comments/deletes otherwise). */
    }
  }, [projectId, docId, includeResolved]);

  useEffect(() => {
    load();
  }, [load]);

  const threads = useMemo(() => {
    const flat = [...comments].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    );
    const roots = flat.filter((c) => !c.parent_id);
    return roots.map((root) => {
      const replies = flat
        .filter((x) => x.parent_id === root.id)
        .sort((a, b) => commentActivityTs(b) - commentActivityTs(a));
      const anchor = resolveWikiTextAnchor(markdownBody || "", root);
      return { root, replies, anchor };
    });
  }, [comments, markdownBody]);

  const { anchoredThreads, orphanedThreads } = useMemo(() => {
    const anchored = [];
    const orphan = [];
    for (const t of threads) {
      const rq = (t.root.quote || "").trim();
      if (!rq || t.anchor.orphaned) {
        orphan.push(t);
      } else {
        anchored.push(t);
      }
    }
    const byNewestActivity = (a, b) => threadActivityTs(b) - threadActivityTs(a);
    anchored.sort(byNewestActivity);
    orphan.sort(byNewestActivity);
    return { anchoredThreads: anchored, orphanedThreads: orphan };
  }, [threads]);

  const replyTargetContext = useMemo(() => {
    if (!replyParentId) return null;
    const root = comments.find((x) => String(x.id) === String(replyParentId) && !x.parent_id);
    if (!root) {
      return { missing: true, shortId: String(replyParentId).slice(0, 8) };
    }
    const rq = (root.quote || "").trim();
    const anchor = resolveWikiTextAnchor(markdownBody || "", root);
    let variant = "document";
    let preview = excerptForQuotePlain(root.content || "", 220);
    if (rq) {
      if (anchor.orphaned) {
        variant = "orphaned";
        preview =
          excerptForQuotePlain(root.content || "", 220) || excerptForQuotePlain(rq, 220) || "…";
      } else {
        variant = "quote";
        preview = excerptForQuotePlain(rq, 220);
      }
    }
    const opener = (root.author_display_name || "").trim() || `Member ${root.author_member_id}`;
    const kindLabel =
      variant === "quote" ? "Anchored quote" : variant === "orphaned" ? "Orphaned quote" : "Document-level";
    return { missing: false, opener, kindLabel, preview, startedAt: root.created_at };
  }, [replyParentId, comments, markdownBody]);

  const submitNew = async (modePost) => {
    const mode = modePost === "force_doc" ? "force_doc" : "auto";
    const text = (newBody || "").trim();
    if (!text || !projectId || !docId) return;
    try {
      let payload;
      if (replyParentId) {
        payload = { content: text, parent_id: replyParentId };
        if (quotedRef?.id) payload.quoted_comment_id = quotedRef.id;
        if (quotedRef?.quotedTextForApi) payload.quoted_text = quotedRef.quotedTextForApi;
      } else if (mode === "force_doc" || !mdSelection?.text?.trim()) {
        payload = { content: text };
      } else {
        payload = {
          content: text,
          ...buildWikiTextAnchor(markdownBody || "", mdSelection.start, mdSelection.end),
        };
      }
      const created = await apiPost(`/projects/${projectId}/docs/${docId}/comments`, payload);
      if (created && typeof created === "object" && created.id) {
        setComments((prev) =>
          prev.some((x) => x.id === created.id) ? prev : [...prev, created],
        );
      }
      setNewBody("");
      setReplyParentId(null);
      setQuotedRef(null);
      onClearMdSelection?.();
      await load();
      if (created?.id) {
        setComments((prev) =>
          prev.some((x) => x.id === created.id) ? prev : [...prev, created],
        );
      }
      onCommentsInvalidate?.();
    } catch (e) {
      setErr?.(e?.message || String(e));
    }
  };

  const resolveComment = async (c) => {
    if (!c?.id || !projectId || !docId) return;
    try {
      await apiPatch(`/projects/${projectId}/docs/${docId}/comments/${c.id}`, { status: "resolved" });
      await load();
      onCommentsInvalidate?.();
    } catch (e) {
      setErr?.(e?.message || String(e));
    }
  };

  const reopenComment = async (c) => {
    if (!c?.id || !projectId || !docId) return;
    try {
      await apiPatch(`/projects/${projectId}/docs/${docId}/comments/${c.id}`, { status: "open" });
      await load();
      onCommentsInvalidate?.();
    } catch (e) {
      setErr?.(e?.message || String(e));
    }
  };

  const deleteComment = async (c) => {
    if (!c?.id || !projectId || !docId) return;
    const isThreadRoot = c.parent_id == null || String(c.parent_id || "").trim() === "";
    const ok = window.confirm(
      isThreadRoot
        ? "Delete this feedback thread and all replies? This cannot be undone."
        : "Delete this comment? This cannot be undone.",
    );
    if (!ok) return;
    loadGenRef.current += 1;
    if (isThreadRoot) {
      setComments((prev) => {
        const removeIds = new Set([c.id]);
        const rootId = String(c.id);
        for (const x of prev) {
          const pid = x.parent_id == null ? "" : String(x.parent_id);
          if (pid === rootId) removeIds.add(x.id);
        }
        return prev.filter((x) => !removeIds.has(x.id));
      });
    } else {
      setComments((prev) => prev.filter((x) => x.id !== c.id));
    }
    if (isThreadRoot) {
      const wasResolved = String(c.status || "").toLowerCase() === "resolved";
      setThreadTotals((prev) => ({
        open: wasResolved ? prev.open : Math.max(0, prev.open - 1),
        resolved: wasResolved ? Math.max(0, prev.resolved - 1) : prev.resolved,
      }));
    }
    if (activeThreadId === c.id) setActiveThreadId(null);
    if (editDraft.id === c.id) setEditDraft({ id: "", text: "" });
    if (replyParentId === c.id) setReplyParentId(null);
    try {
      await apiDelete(`/projects/${projectId}/docs/${docId}/comments/${c.id}`);
      onCommentsInvalidate?.();
    } catch (e) {
      setErr?.(e?.message || String(e));
      await load();
    }
  };

  const saveEdit = async () => {
    const id = (editDraft.id || "").trim();
    const txt = (editDraft.text || "").trim();
    if (!id || !txt || !projectId || !docId) return;
    try {
      await apiPatch(`/projects/${projectId}/docs/${docId}/comments/${id}`, { content: txt });
      setEditDraft({ id: "", text: "" });
      await load();
      onCommentsInvalidate?.();
    } catch (e) {
      setErr?.(e?.message || String(e));
    }
  };

  const jumpToQuote = (root) => {
    const rq = (root.quote || "").trim();
    if (!rq) return;
    const pos = resolveWikiTextAnchor(markdownBody || "", root);
    if (pos.orphaned) return;
    onFocusMarkdownRange?.(pos.start, pos.end);
  };

  const renderCommentCard = (c, { dense, threadRootId } = {}) => {
    const isMine = me != null && c.author_member_id === me;
    const isThreadRoot = c.parent_id == null || String(c.parent_id || "").trim() === "";
    const editing = editDraft.id === c.id;
    return (
      <div
        key={c.id}
        className={`as-wiki-cmt-card ${dense ? "as-wiki-cmt-card--reply" : ""} ${
          c.status === "resolved" ? "as-wiki-cmt-card--resolved" : ""
        }`}
      >
        <div className="as-wiki-cmt-card-head d-flex justify-content-between align-items-start gap-2">
          <div className="min-w-0">
            <span className="as-wiki-cmt-author">{c.author_display_name || `Member ${c.author_member_id}`}</span>{" "}
            <span className="as-wiki-cmt-time text-secondary">{formatDt(c.created_at)}</span>
          </div>
          <div className="as-wiki-cmt-actions d-flex flex-shrink-0 gap-1">
            {isMine ? (
              <button
                type="button"
                className="btn btn-sm btn-link p-0 as-wiki-cmt-mini"
                onClick={() => setEditDraft({ id: c.id, text: c.content })}
              >
                Edit
              </button>
            ) : null}
            {isMine ? (
              <button
                type="button"
                className="btn btn-sm btn-link p-0 as-wiki-cmt-mini text-danger"
                onClick={() => deleteComment(c)}
              >
                {isThreadRoot ? "Delete thread" : "Delete"}
              </button>
            ) : null}
            {isThreadRoot ? (
              c.status === "resolved" ? (
                <button type="button" className="btn btn-sm btn-link p-0 as-wiki-cmt-mini" onClick={() => reopenComment(c)}>
                  Reopen
                </button>
              ) : (
                <button type="button" className="btn btn-sm btn-link p-0 as-wiki-cmt-mini" onClick={() => resolveComment(c)}>
                  Resolve
                </button>
              )
            ) : null}
            {threadRootId ? (
              <button
                type="button"
                className="btn btn-sm btn-link p-0 as-wiki-cmt-mini"
                title='Select text in this comment, then Quote — or Quote without selecting for the full message'
                onMouseDown={(e) => {
                  /* Keep selection alive so Quote can read the highlight (Chrome clears it on blur). */
                  e.preventDefault();
                }}
                onClick={() => {
                  const chosenRaw = getQuoteSnippetFromComment(c.id);
                  const usePartial = !!chosenRaw;
                  const excerpt = usePartial ? excerptForQuotePlain(chosenRaw) : excerptForQuotePlain(c.content);
                  setReplyParentId(threadRootId);
                  setQuotedRef({
                    id: c.id,
                    author_display_name: c.author_display_name || `Member ${c.author_member_id}`,
                    excerpt,
                    quotedTextForApi: usePartial ? chosenRaw : null,
                  });
                }}
              >
                Quote
              </button>
            ) : null}
          </div>
        </div>
        {editing ? (
          <div className="as-wiki-cmt-edit mt-2">
            {editMentionSuggestions.length ? (
              <div className="as-chat-mention-suggest mb-1">
                {editMentionSuggestions.map((mem) => (
                  <button
                    key={mem.id}
                    type="button"
                    className="btn btn-sm btn-outline-secondary"
                    onClick={() => pickEditMention(mem.name)}
                  >
                    @{mentionKeyFromName(mem.name)}
                  </button>
                ))}
              </div>
            ) : null}
            <textarea
              className="form-control form-control-sm"
              rows={4}
              value={editDraft.text}
              onChange={(e) => setEditDraft((p) => ({ ...p, text: e.target.value }))}
            />
            <div className="d-flex gap-2 mt-1">
              <button type="button" className="btn btn-sm btn-primary" onClick={saveEdit}>
                Save
              </button>
              <button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => setEditDraft({ id: "", text: "" })}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <>
            {(c.quoted_excerpt || "").trim() ? (
              <div className="as-wiki-cmt-comment-quote-ref small mt-2 mb-1">
                <div className="text-secondary mb-1">
                  Quoting {(c.quoted_author_display_name || "").trim() || "Comment"}
                </div>
                <div className="as-wiki-cmt-comment-quote-ref-body border-start border-secondary border-2 ps-2 text-secondary">
                  {c.quoted_excerpt}
                </div>
              </div>
            ) : null}
            <div data-as-wiki-cmt-body={c.id} className="min-w-0">
              <div
                className={`as-wiki-cmt-body as-wiki-cmt-body-selectable as-wiki-cmt-md mb-0 small ${
                  (c.quoted_excerpt || "").trim() ? "mt-1" : "mt-2"
                }`}
              >
                {renderMarkdownWithMentions(c.content, mentionIndex)}
              </div>
            </div>
          </>
        )}
      </div>
    );
  };

  const renderThread = (bundle) => {
    const { root, replies } = bundle;
    const branchOrdered = [root, ...(replies || [])].sort(
      (a, b) => commentActivityTs(b) - commentActivityTs(a),
    );
    const rq = (root.quote || "").trim();
    const open = activeThreadId === root.id;
    const anchor = rq ? resolveWikiTextAnchor(markdownBody || "", root) : null;
    return (
      <li key={root.id} className="as-wiki-cmt-thread">
        <div className="as-wiki-cmt-thread-item">
          <button
            type="button"
            className={`as-wiki-cmt-thread-hd btn btn-sm w-100 text-start ${open ? "is-open" : ""}`}
            onClick={() => setActiveThreadId((x) => (x === root.id ? null : root.id))}
          >
            {!rq ? (
              <span
                className="badge bg-secondary bg-opacity-25 text-dark align-middle me-1 text-truncate"
                style={{ maxWidth: "10rem", verticalAlign: "middle" }}
                title={
                  root.author_display_name?.trim?.() ||
                  (root.author_member_id != null ? `Member ${root.author_member_id}` : "Document discussion")
                }
              >
                {root.author_display_name?.trim?.() ||
                  (root.author_member_id != null ? `Member ${root.author_member_id}` : "Document")}
              </span>
            ) : anchor?.orphaned ? (
              <span className="badge bg-warning bg-opacity-50 text-dark align-middle me-1">Orphaned</span>
            ) : (
              <span className="badge as-wiki-cmt-quote-badge bg-warning bg-opacity-25 text-dark align-middle me-1">Quote</span>
            )}
            <span className="as-wiki-cmt-thread-snippet text-truncate d-inline-block" style={{ maxWidth: "78%" }}>
              {rq ? rq.slice(0, 120) + (rq.length > 120 ? "…" : "") : (root.content || "").slice(0, 120)}
            </span>
            <span className="float-end small text-secondary">{replies.length ? `${replies.length + 1} msgs` : ""}</span>
          </button>
          <div className="as-wiki-cmt-thread-ts text-secondary">{formatDt(root.created_at)}</div>
        </div>
        {open ? (
          <div className="as-wiki-cmt-thread-bd">
            {rq && !anchor?.orphaned ? (
              <button type="button" className="btn btn-sm btn-outline-secondary mb-2" onClick={() => jumpToQuote(root)}>
                Show in editor
              </button>
            ) : null}
            {!rq ? (
              <p className="small text-secondary mb-2">Discussion at document level.</p>
            ) : anchor?.orphaned ? (
              <p className="small text-secondary mb-2">
                Quoted text no longer matches this revision — add a reply here or resolve.
              </p>
            ) : (
              <pre className="as-wiki-cmt-quote-block small">{rq}</pre>
            )}
            {branchOrdered.map((c) =>
              renderCommentCard(c, {
                dense: String(c.id) !== String(root.id),
                threadRootId: root.id,
              }),
            )}
            <div className="as-wiki-cmt-reply mt-2">
              <button
                type="button"
                className="btn btn-sm btn-outline-primary"
                onClick={() => {
                  setReplyParentId(root.id);
                  setQuotedRef(null);
                }}
              >
                Reply
              </button>
            </div>
          </div>
        ) : null}
      </li>
    );
  };

  const threadSummaryLine = (
    <p className="small text-secondary mb-2">
      {threadTotals.open} open · {threadTotals.resolved} resolved · {threadTotals.open + threadTotals.resolved} total threads
      {threadTotals.resolved > 0 && !includeResolved ? (
        <span className="d-block mt-1">Enable &quot;Resolved&quot; above to list closed threads.</span>
      ) : null}
    </p>
  );

  return (
    <aside className="as-wiki-comments-panel h-100 d-flex flex-column" aria-label="Wiki feedback">
      <div className="as-wiki-comments-panel-hd px-3 py-2 border-bottom">
        <div className="d-flex justify-content-between align-items-center gap-2 flex-wrap">
          <span className="fw-semibold">Feedback</span>
          <div className="d-flex align-items-center gap-2 flex-shrink-0">
            {typeof onCollapseSidebar === "function" ? (
              <button
                type="button"
                className="btn btn-sm btn-outline-secondary as-wiki-comments-collapse border-0 px-2 py-0 lh-1"
                onClick={() => onCollapseSidebar()}
                aria-label="Hide feedback panel"
                title="Hide feedback panel"
              >
                <i className="bi bi-layout-sidebar-inset-reverse fs-6" aria-hidden />
              </button>
            ) : null}
            <div className="form-check form-switch mb-0 small">
              <input
                className="form-check-input"
                type="checkbox"
                id="wiki-cmt-show-resolved"
                checked={includeResolved}
                onChange={(e) => setIncludeResolved(e.target.checked)}
              />
              <label className="form-check-label" htmlFor="wiki-cmt-show-resolved">
                Resolved
              </label>
            </div>
          </div>
        </div>
        {loading ? <span className="small text-secondary">Loading…</span> : null}
      </div>

      <div className="as-wiki-comments-composer border-bottom px-3 py-2 bg-body-tertiary">
        {replyParentId ? (
          <div className="mb-2">
            <div className="d-flex justify-content-between align-items-start gap-2 mb-1">
              <span className="small fw-semibold">Reply in this feedback thread</span>
              <button
                type="button"
                className="btn btn-link btn-sm p-0 as-wiki-cmt-mini align-baseline flex-shrink-0"
                onClick={() => {
                  setReplyParentId(null);
                  setQuotedRef(null);
                }}
              >
                Cancel reply
              </button>
            </div>
            {quotedRef?.author_display_name ? (
              <p className="small text-secondary mb-2">
                Also quoting <span className="fw-medium text-body">{quotedRef.author_display_name}</span>
              </p>
            ) : null}
            {replyTargetContext?.missing ? (
              <p className="small text-secondary mb-0">
                Thread <code className="user-select-all">{replyTargetContext.shortId}…</code> (reload if this looks wrong)
              </p>
            ) : replyTargetContext ? (
              <div className="as-wiki-cmt-reply-context small rounded border px-2 py-2">
                <div className="text-secondary mb-1">
                  Started by <span className="text-body fw-medium">{replyTargetContext.opener}</span>
                  <span className="mx-1">·</span>
                  <span>{replyTargetContext.kindLabel}</span>
                  {replyTargetContext.startedAt ? (
                    <>
                      <span className="mx-1">·</span>
                      <span>{formatDt(replyTargetContext.startedAt)}</span>
                    </>
                  ) : null}
                </div>
                <div className="text-body mb-0 as-wiki-cmt-reply-context-snippet">{replyTargetContext.preview}</div>
              </div>
            ) : null}
          </div>
        ) : null}
        {replyParentId && quotedRef ? (
          <div className="alert alert-light border py-2 px-2 small mb-2 as-wiki-cmt-compose-quoteref">
            <div className="d-flex justify-content-between align-items-start gap-2">
              <span className="text-secondary">Quoted</span>
              <button type="button" className="btn btn-sm btn-link p-0" onClick={() => setQuotedRef(null)}>
                Remove quote
              </button>
            </div>
            <div className="text-body mt-1 mb-0 as-wiki-cmt-md small">{renderMarkdownWithMentions(quotedRef.excerpt, mentionIndex)}</div>
          </div>
        ) : null}
        {!replyParentId && mdSelection?.text?.trim() ? (
          <div className="alert alert-warning py-2 px-2 small mb-2 as-wiki-cmt-selection-preview">
            <span className="fw-semibold d-block mb-1">Selection</span>
            <span>{mdSelection.text.length > 400 ? `${mdSelection.text.slice(0, 400)}…` : mdSelection.text}</span>
          </div>
        ) : null}
        {newBodyMentionSuggestions.length ? (
          <div className="as-chat-mention-suggest mb-1">
            {newBodyMentionSuggestions.map((mem) => (
              <button
                key={mem.id}
                type="button"
                className="btn btn-sm btn-outline-secondary"
                onClick={() => pickNewMention(mem.name)}
              >
                @{mentionKeyFromName(mem.name)}
              </button>
            ))}
          </div>
        ) : null}
        <textarea
          className="form-control form-control-sm mb-2"
          rows={3}
          placeholder="Write feedback… (@mention)"
          value={newBody}
          onChange={(e) => setNewBody(e.target.value)}
        />
        <div className="d-flex flex-wrap gap-2 justify-content-end">
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={!newBody.trim()}
            onClick={() => submitNew("auto")}
          >
            {replyParentId ? "Post reply" : mdSelection?.text?.trim() ? "Post with quote" : "Post"}
          </button>
          {!replyParentId && mdSelection?.text?.trim() ? (
            <button
              type="button"
              className="btn btn-sm btn-outline-secondary"
              disabled={!newBody.trim()}
              onClick={() => submitNew("force_doc")}
            >
              Submit without quote
            </button>
          ) : null}
        </div>
      </div>

      <div className="as-wiki-comments-panel-scroll flex-grow-1 overflow-auto px-3 py-2">
        {!anchoredThreads.length && !orphanedThreads.length ? (
          loading ? null : threadTotals.open + threadTotals.resolved === 0 ? (
            <p className="small text-secondary mb-0">No feedback yet.</p>
          ) : (
            threadSummaryLine
          )
        ) : (
          <>
            {threadSummaryLine}
            <ul className="list-unstyled mb-4 as-wiki-cmt-thread-list">
              {anchoredThreads.map((t) => renderThread(t))}
            </ul>
            {orphanedThreads.length ? (
              <>
                <ul className="list-unstyled mb-0 as-wiki-cmt-thread-list">{orphanedThreads.map((t) => renderThread(t))}</ul>
              </>
            ) : null}
          </>
        )}
      </div>
    </aside>
  );
}
