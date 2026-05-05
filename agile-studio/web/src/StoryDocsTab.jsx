import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import MarkdownEditorField from "./MarkdownEditorField.jsx";
import { apiDelete, apiGet, apiPost, apiPut } from "./api.js";

/**
 * Story » Docs tab: markdown + live preview, autosave, wiki:slug.
 * New docs attach the current story; a doc can link to more stories from project Documentation.
 */
export default function StoryDocsTab({ projectId, storyId, setErr }) {
  const [docs, setDocs] = useState([]);
  const [selId, setSelId] = useState(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [isDraft, setIsDraft] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const lastSavedRef = useRef({ title: "", body: "", id: null });

  const refresh = useCallback(async () => {
    if (!projectId || !storyId) return;
    setLoading(true);
    try {
      const rows = await apiGet(`/projects/${projectId}/docs?story_id=${storyId}&limit=100`);
      setDocs(Array.isArray(rows) ? rows : []);
    } catch (e) {
      setErr?.(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [projectId, storyId, setErr]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const selectDoc = useCallback((d) => {
    if (!d) return;
    setSelId(d.id);
    setTitle(d.title || "");
    setBody(d.content || "");
    setIsDraft(Boolean(d.is_draft));
    lastSavedRef.current = { title: d.title || "", body: d.content || "", id: d.id };
  }, []);

  useEffect(() => {
    if (!selId && docs.length && !loading) {
      selectDoc(docs[0]);
    }
  }, [docs, selId, loading, selectDoc]);

  const wikiPreviewOptions = useMemo(
    () => ({
      components: {
        a: ({ href, children, ...rest }) => {
          const h = href || "";
          if (h.startsWith("wiki:")) {
            const slug = encodeURIComponent(h.slice(5).replace(/^\/*/, ""));
            return (
              <Link to={`/p/${projectId}/wiki/${slug}`} {...rest}>
                {children}
              </Link>
            );
          }
          return (
            <a href={h} target="_blank" rel="noopener noreferrer" {...rest}>
              {children}
            </a>
          );
        },
      },
    }),
    [projectId]
  );

  useEffect(() => {
    if (!selId || !projectId) return;
    const ls = lastSavedRef.current;
    if (ls.id === selId && title === ls.title && body === ls.body) return;
    const t = setTimeout(async () => {
      setSaving(true);
      try {
        await apiPut(`/projects/${projectId}/docs/${selId}`, {
          title: title.trim() || "Untitled",
          content: body,
          is_draft: isDraft,
        });
        lastSavedRef.current = { title: title.trim(), body, id: selId };
        await refresh();
      } catch (e) {
        setErr?.(e?.message || String(e));
      } finally {
        setSaving(false);
      }
    }, 1800);
    return () => clearTimeout(t);
  }, [title, body, selId, projectId, isDraft, refresh, setErr]);

  const onCreate = async () => {
    try {
      const d = await apiPost(`/projects/${projectId}/docs`, {
        title: "New document",
        content: "",
        story_ids: [storyId],
        is_draft: true,
      });
      await refresh();
      selectDoc(d);
    } catch (e) {
      setErr?.(e?.message || String(e));
    }
  };

  const onDelete = async () => {
    if (!selId) return;
    if (!window.confirm("Delete this document?")) return;
    try {
      await apiDelete(`/projects/${projectId}/docs/${selId}`);
      setSelId(null);
      setTitle("");
      setBody("");
      lastSavedRef.current = { title: "", body: "", id: null };
      await refresh();
    } catch (e) {
      setErr?.(e?.message || String(e));
    }
  };

  const publish = async () => {
    if (!selId) return;
    setSaving(true);
    try {
      await apiPut(`/projects/${projectId}/docs/${selId}`, {
        title: title.trim() || "Untitled",
        content: body,
        is_draft: false,
      });
      setIsDraft(false);
      lastSavedRef.current = { title: title.trim(), body, id: selId };
      await refresh();
    } catch (e) {
      setErr?.(e?.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  const active = docs.find((d) => d.id === selId);
  const storyIds = active && Array.isArray(active.story_ids) ? active.story_ids : [];
  const otherStories =
    active && storyIds.length > 1 ? storyIds.filter((id) => Number(id) !== Number(storyId)) : [];

  if (loading && !docs.length) {
    return (
      <div className="as-story-docs as-story-wiki-tab d-flex align-items-center gap-2 text-secondary small py-3">
        <div className="spinner-border spinner-border-sm" />
        Loading documents…
      </div>
    );
  }

  return (
    <div className="as-story-docs as-story-wiki-tab">
      <header className="as-story-docs-head mb-3">
        <p className="as-story-docs-lead small text-secondary mb-2">
          Markdown và xem trước trực tiếp. Liên kết chéo:{" "}
          <code className="user-select-all as-wiki-code-hint">[chi tiết](wiki:slug-doc)</code>
          . Autosave ~1,8s. Một doc có thể gắn thêm story khác từ mục Documentation trong project.
        </p>
        {otherStories.length > 0 ? (
          <div className="as-story-docs-shared alert alert-light border py-2 px-3 small mb-0" role="status">
            <i className="bi bi-link-45deg me-1" aria-hidden />
            This doc is also linked to {otherStories.length} other{" "}
            {otherStories.length === 1 ? "story" : "stories"} — edit links in{" "}
            <Link
              to={
                active?.slug
                  ? `/p/${projectId}/wiki/${encodeURIComponent(active.slug)}`
                  : `/p/${projectId}/wiki`
              }
            >
              Documentation
            </Link>
            .
          </div>
        ) : null}
      </header>

      <div className="d-flex flex-wrap gap-2 mb-3 align-items-center as-story-docs-actions">
        <button type="button" className="btn btn-sm btn-primary" onClick={onCreate}>
          <i className="bi bi-file-earmark-plus me-1" />
          New document
        </button>
        <Link className="btn btn-sm btn-outline-primary" to={`/p/${projectId}/wiki`}>
          <i className="bi bi-journal-text me-1" />
          Open Documentation
        </Link>
        <div className="d-flex flex-wrap gap-1 flex-grow-1 justify-content-end">
          {docs.map((d) => (
            <button
              key={d.id}
              type="button"
              className={`btn btn-sm ${d.id === selId ? "btn-secondary" : "btn-outline-secondary"} as-story-doc-pill`}
              onClick={() => selectDoc(d)}
            >
              <span className="text-truncate" style={{ maxWidth: 200 }}>
                {d.title || "Untitled"}
              </span>
              {d.is_draft ? (
                <span className="badge bg-warning text-dark ms-1 as-wiki-draft-badge">draft</span>
              ) : null}
            </button>
          ))}
        </div>
        {saving ? <span className="small text-secondary">Saving…</span> : null}
        {!isDraft ? <span className="small text-success">Published</span> : null}
      </div>

      {selId ? (
        <>
          <div className="as-story-docs-editor-hd d-flex flex-wrap gap-2 mb-2 align-items-center">
            <input
              className="form-control form-control-sm flex-grow-1 as-story-docs-title"
              style={{ maxWidth: 520 }}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Title"
            />
            <button type="button" className="btn btn-sm btn-success" onClick={publish} disabled={!isDraft}>
              Publish
            </button>
            <button type="button" className="btn btn-sm btn-outline-danger" onClick={onDelete}>
              Delete
            </button>
          </div>
          <MarkdownEditorField
            value={body}
            onChange={setBody}
            height={420}
            previewMode="live"
            previewOptions={wikiPreviewOptions}
            placeholder="Write documentation…"
          />
        </>
      ) : (
        <p className="text-secondary small mb-0">
          {docs.length === 0
            ? "No documents yet — click New document or open Documentation."
            : "Select a document."}
        </p>
      )}
    </div>
  );
}
