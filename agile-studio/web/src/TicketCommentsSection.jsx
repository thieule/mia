import { useCallback, useEffect, useMemo, useState } from "react";
import MarkdownEditorField from "./MarkdownEditorField.jsx";
import { apiDelete, apiGet, apiPatch, apiPost, getStoredUser } from "./api.js";
import { mentionKeyFromName, replaceTrailingMention } from "./mentionText.jsx";
import { renderMarkdownWithMentions } from "./markdownWithMentions.jsx";

export default function TicketCommentsSection({ projectId, taskId, projectMembers, setErr }) {
  const me = getStoredUser();
  const onProject = me?.member_id != null && projectMembers.some((row) => row.member_id === me.member_id);

  const [comments, setComments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [posting, setPosting] = useState(false);
  const [cmBody, setCmBody] = useState("");
  const [editingCommentId, setEditingCommentId] = useState(null);
  const [editDraft, setEditDraft] = useState("");
  const [commentMentionCaretCreate, setCommentMentionCaretCreate] = useState(null);
  const [commentMentionCaretEdit, setCommentMentionCaretEdit] = useState(null);

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

  const loadComments = useCallback(async () => {
    if (!projectId || !taskId) return;
    setLoading(true);
    setErr(null);
    try {
      const rows = await apiGet(`/projects/${projectId}/tasks/${taskId}/comments`);
      setComments(Array.isArray(rows) ? rows : []);
    } catch (e) {
      setComments([]);
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, [projectId, taskId, setErr]);

  useEffect(() => {
    loadComments();
  }, [loadComments]);

  const onPickCommentMention = useCallback(
    (displayName, mode) => {
      if (mode === "edit") {
        const { next, caret } = replaceTrailingMention(editDraft, displayName);
        if (next !== editDraft) {
          setEditDraft(next);
          setCommentMentionCaretEdit({ start: caret, end: caret });
        }
        return;
      }
      const { next, caret } = replaceTrailingMention(cmBody, displayName);
      if (next !== cmBody) {
        setCmBody(next);
        setCommentMentionCaretCreate({ start: caret, end: caret });
      }
    },
    [cmBody, editDraft]
  );

  const startEdit = (c) => {
    setEditingCommentId(c.id);
    setEditDraft(c.body ?? "");
  };

  const cancelEdit = () => {
    setEditingCommentId(null);
    setEditDraft("");
  };

  const saveEdit = async () => {
    if (!editingCommentId || !editDraft.trim()) return;
    setErr(null);
    try {
      const updated = await apiPatch(`/projects/${projectId}/tasks/${taskId}/comments/${editingCommentId}`, {
        body: editDraft.trim(),
      });
      setComments((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
      cancelEdit();
    } catch (e2) {
      setErr(e2.message);
    }
  };

  /** Must not use <form> here: TicketPage wraps the page in a form (invalid nested forms break submit). */
  const postComment = async () => {
    const text = cmBody.trim();
    if (!text || posting || !onProject) return;
    setErr(null);
    const pendingKey = `pending-${Date.now()}`;
    const optimistic = {
      id: pendingKey,
      story_task_id: taskId,
      author_member_id: me?.member_id ?? 0,
      body: text,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      author: me
        ? {
            id: me.member_id,
            display_name: me.display_name || `Member #${me.member_id}`,
            email: me.email ?? null,
            member_type: me.member_type || "human",
          }
        : null,
    };
    setCmBody("");
    setComments((prev) => {
      const next = [...prev.filter((c) => c.id !== pendingKey), optimistic];
      next.sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
      return next;
    });
    setPosting(true);
    try {
      const created = await apiPost(`/projects/${projectId}/tasks/${taskId}/comments`, {
        body: text,
      });
      setComments((prev) => {
        const without = prev.filter((c) => c.id !== pendingKey);
        if (without.some((x) => x.id === created.id)) return without;
        const next = [...without, created];
        next.sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
        return next;
      });
    } catch (e2) {
      setComments((prev) => prev.filter((c) => c.id !== pendingKey));
      setCmBody(text);
      setErr(e2.message);
    } finally {
      setPosting(false);
    }
  };

  const onDeleteComment = async (commentId) => {
    if (!window.confirm("Delete this comment?")) return;
    setErr(null);
    try {
      await apiDelete(`/projects/${projectId}/tasks/${taskId}/comments/${commentId}`);
      setComments((prev) => prev.filter((c) => c.id !== commentId));
    } catch (e2) {
      setErr(e2.message);
    }
  };

  if (!projectId || !taskId) return null;

  return (
    <section className="as-ticket-fieldset mt-4">
      <h2 className="as-ticket-fieldset-title">Comments</h2>
      <p className="as-ticket-fieldset-hint small text-secondary mb-3">
        Same markdown and @mentions as story comments (project members only).
      </p>
      {loading ? (
        <p className="small text-secondary mb-3">Loading comments…</p>
      ) : (
        <ul className="list-unstyled small mb-4">
          {comments.map((c) => {
            const isPending = typeof c.id === "string" && String(c.id).startsWith("pending-");
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
                    {c.author?.member_type === "ai" ? (
                      <span className="badge bg-secondary ms-1 small">AI</span>
                    ) : null}
                    <span className="text-muted"> · {new Date(c.created_at).toLocaleString()}</span>
                    {edited ? <span className="text-muted fst-italic ms-1">(edited)</span> : null}
                  </div>
                  {isPending ? (
                    <span className="badge bg-secondary-subtle text-secondary small">Sending…</span>
                  ) : null}
                  {isAuthor && editingCommentId !== c.id && !isPending ? (
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
                  <div className="vstack gap-2 mt-1">
                    {editCommentMentionSuggestions.length > 0 ? (
                      <div className="as-chat-mention-suggest mb-1">
                        {editCommentMentionSuggestions.map((m) => (
                          <button
                            key={m.id}
                            type="button"
                            className="btn btn-sm btn-outline-secondary"
                            onClick={() => onPickCommentMention(m.name, "edit")}
                          >
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
                      selectionFocus={commentMentionCaretEdit}
                      onSelectionFocusDone={() => setCommentMentionCaretEdit(null)}
                      projectId={projectId}
                    />
                    <div className="d-flex gap-2">
                      <button className="btn btn-primary btn-sm" type="button" disabled={!editDraft.trim()} onClick={saveEdit}>
                        Save
                      </button>
                      <button className="btn btn-outline-secondary btn-sm" type="button" onClick={cancelEdit}>
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="mt-1 as-comment-md">{renderCommentContent(c.body)}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <div className="vstack gap-2">
        {me ? (
          <p className="small text-secondary mb-0">
            Posting as <strong>{me.display_name}</strong>.
            {!onProject ? (
              <span className="d-block text-warning mt-1">Join this project in Team before commenting.</span>
            ) : null}
          </p>
        ) : null}
        {createCommentMentionSuggestions.length > 0 ? (
          <div className="as-chat-mention-suggest mb-1">
            {createCommentMentionSuggestions.map((m) => (
              <button
                key={m.id}
                type="button"
                className="btn btn-sm btn-outline-secondary"
                onClick={() => onPickCommentMention(m.name, "create")}
              >
                @{mentionKeyFromName(m.name)}
              </button>
            ))}
          </div>
        ) : null}
        <MarkdownEditorField
          value={cmBody}
          onChange={setCmBody}
          height={170}
          placeholder="Comment"
          textareaProps={{ required: false }}
          insertToolbar
          projectId={projectId}
          selectionFocus={commentMentionCaretCreate}
          onSelectionFocusDone={() => setCommentMentionCaretCreate(null)}
        />
        <button
          className="btn btn-primary btn-sm"
          type="button"
          disabled={!cmBody.trim() || (me != null && !onProject) || posting}
          title={me != null && !onProject ? "Join this project in Team to comment" : undefined}
          onClick={postComment}
        >
          {posting ? (
            <>
              <span className="spinner-border spinner-border-sm me-1" aria-hidden />
              Posting…
            </>
          ) : (
            "Post comment"
          )}
        </button>
      </div>
    </section>
  );
}
