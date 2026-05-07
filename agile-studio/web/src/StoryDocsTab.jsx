import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiGet, apiPut } from "./api.js";

/** Story » Docs: danh sách doc đã link; tạo mới hoặc link doc có sẵn qua popup. */
export default function StoryDocsTab({ projectId, storyId, onProject = false, setErr }) {
  const navigate = useNavigate();
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [linkModalOpen, setLinkModalOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [pickerRows, setPickerRows] = useState([]);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [linkingId, setLinkingId] = useState(null);

  const sid = storyId != null ? Number(storyId) : NaN;

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

  const linkedIds = useMemo(() => new Set(docs.map((d) => String(d.id))), [docs]);

  useEffect(() => {
    if (!linkModalOpen || !projectId) return;
    let cancelled = false;
    const q = pickerQuery.trim();
    const t = window.setTimeout(async () => {
      setPickerLoading(true);
      try {
        const qs = q ? `&q=${encodeURIComponent(q)}` : "";
        const rows = await apiGet(`/projects/${projectId}/docs?limit=120${qs}`);
        if (!cancelled) setPickerRows(Array.isArray(rows) ? rows : []);
      } catch (e) {
        if (!cancelled) setErr?.(e?.message || String(e));
      } finally {
        if (!cancelled) setPickerLoading(false);
      }
    }, 280);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [linkModalOpen, projectId, pickerQuery, setErr]);

  const openLinkModal = () => {
    setPickerQuery("");
    setPickerRows([]);
    setPickerLoading(true);
    setLinkModalOpen(true);
  };

  const closeLinkModal = () => {
    setLinkModalOpen(false);
    setPickerQuery("");
    setPickerRows([]);
    setPickerLoading(false);
    setLinkingId(null);
  };

  const linkDocumentToStory = async (doc) => {
    if (!projectId || !Number.isFinite(sid)) return;
    const idStr = String(doc.id);
    setLinkingId(idStr);
    try {
      const prev = Array.isArray(doc.story_ids) ? doc.story_ids.map(Number) : [];
      const next = [...new Set([...prev, sid])];
      await apiPut(`/projects/${projectId}/docs/${encodeURIComponent(idStr)}`, { story_ids: next });
      await refresh();
      closeLinkModal();
    } catch (e) {
      setErr?.(e?.message || String(e));
    } finally {
      setLinkingId(null);
    }
  };

  const unlinkDocument = async (doc) => {
    if (!projectId || !Number.isFinite(sid)) return;
    const idStr = String(doc.id);
    setLinkingId(idStr);
    try {
      const prev = Array.isArray(doc.story_ids) ? doc.story_ids.map(Number) : [];
      const next = prev.filter((x) => x !== sid);
      await apiPut(`/projects/${projectId}/docs/${encodeURIComponent(idStr)}`, { story_ids: next });
      await refresh();
    } catch (e) {
      setErr?.(e?.message || String(e));
    } finally {
      setLinkingId(null);
    }
  };

  const openNewDoc = () => {
    navigate(`/p/${projectId}/wiki`, {
      state: {
        createDocForStoryId: storyId,
        createDocNonce: `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`,
      },
    });
  };

  const pickerCandidates = useMemo(() => {
    return pickerRows.filter((d) => d && !linkedIds.has(String(d.id)));
  }, [pickerRows, linkedIds]);

  if (loading && docs.length === 0) {
    return (
      <div className="as-story-docs as-story-wiki-tab d-flex align-items-center gap-2 text-secondary small py-3">
        <div className="spinner-border spinner-border-sm" role="status" />
        Loading…
      </div>
    );
  }

  return (
    <div className="as-story-docs as-story-wiki-tab">
      <div className="as-story-docs-toolbar d-flex flex-wrap gap-2 justify-content-end align-items-center mb-2">
        <button type="button" className="btn btn-sm btn-primary" onClick={openNewDoc}>
          <i className="bi bi-plus-lg me-1" aria-hidden />
          New document
        </button>
        {onProject ? (
          <button type="button" className="btn btn-sm btn-outline-primary" onClick={openLinkModal}>
            <i className="bi bi-link-45deg me-1" aria-hidden />
            Link document…
          </button>
        ) : null}
      </div>

      {!onProject ? (
        <p className="small text-secondary mb-3">
          Join the project <strong>Team</strong> to link or unlink documents from this story.
        </p>
      ) : null}

      {docs.length === 0 ? (
        <p className="text-secondary small mb-0 py-2">No documents linked to this story.</p>
      ) : (
        <ul className="list-group as-story-docs-list">
          {docs.map((d) => (
            <li key={d.id} className="list-group-item p-0 d-flex align-items-stretch">
              <Link
                className="as-story-docs-list-link flex-grow-1 d-flex align-items-center gap-2 px-3 py-2 text-decoration-none text-body min-w-0"
                to={d.slug ? `/p/${projectId}/wiki/${encodeURIComponent(d.slug)}` : `/p/${projectId}/wiki`}
              >
                <i className="bi bi-file-earmark-text text-secondary flex-shrink-0" aria-hidden />
                <span className="text-truncate fw-medium">{d.title || "Untitled"}</span>
                {d.is_draft ? (
                  <span className="badge bg-warning text-dark ms-auto flex-shrink-0">Draft</span>
                ) : (
                  <span className="ms-auto flex-shrink-0 w-0" aria-hidden />
                )}
              </Link>
              {onProject ? (
                <div className="d-flex align-items-stretch border-start bg-body-secondary bg-opacity-25">
                  <button
                    type="button"
                    className="as-story-docs-unlink-btn btn btn-sm btn-outline-danger border-0 rounded-0 px-3 d-flex align-items-center justify-content-center"
                    title="Remove from this story"
                    aria-label="Remove from this story"
                    disabled={linkingId === String(d.id)}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      unlinkDocument(d);
                    }}
                  >
                    {linkingId === String(d.id) ? (
                      <span className="spinner-border spinner-border-sm" role="status" />
                    ) : (
                      <i className="bi bi-x-lg fs-5" aria-hidden />
                    )}
                  </button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {linkModalOpen ? (
        <>
          <div
            className="modal fade show d-block"
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-labelledby="as-story-link-doc-title"
          >
            <div className="modal-dialog modal-dialog-scrollable modal-lg">
              <div className="modal-content">
                <div className="modal-header">
                  <h5 className="modal-title" id="as-story-link-doc-title">
                    Link document to this story
                  </h5>
                  <button type="button" className="btn-close" onClick={closeLinkModal} aria-label="Close" />
                </div>
                <div className="modal-body">
                  <label className="form-label small text-secondary mb-1" htmlFor="as-story-doc-picker-search">
                    Search project documents
                  </label>
                  <input
                    id="as-story-doc-picker-search"
                    type="search"
                    className="form-control mb-3"
                    placeholder="Title or content…"
                    value={pickerQuery}
                    onChange={(e) => setPickerQuery(e.target.value)}
                    autoFocus
                  />
                  {pickerLoading ? (
                    <div className="d-flex align-items-center gap-2 text-secondary small py-4 justify-content-center">
                      <div className="spinner-border spinner-border-sm" role="status" />
                      Loading…
                    </div>
                  ) : pickerCandidates.length === 0 ? (
                    <p className="text-secondary small mb-0 py-2">
                      {pickerRows.length === 0
                        ? "No documents found. Try another search or create a new document."
                        : "Every document in this result is already linked to this story."}
                    </p>
                  ) : (
                    <ul className="list-group list-group-flush border rounded-2">
                      {pickerCandidates.map((d) => (
                        <li
                          key={d.id}
                          className="list-group-item d-flex align-items-center gap-2 flex-wrap py-2"
                        >
                          <i className="bi bi-file-earmark-text text-secondary flex-shrink-0" aria-hidden />
                          <div className="flex-grow-1 min-w-0">
                            <div className="fw-medium text-truncate">{d.title || "Untitled"}</div>
                            <div className="small text-secondary text-truncate">{d.slug ? `/${d.slug}` : "—"}</div>
                          </div>
                          {d.is_draft ? (
                            <span className="badge bg-warning text-dark flex-shrink-0">Draft</span>
                          ) : null}
                          <button
                            type="button"
                            className="btn btn-sm btn-primary flex-shrink-0"
                            disabled={linkingId === String(d.id)}
                            onClick={() => linkDocumentToStory(d)}
                          >
                            {linkingId === String(d.id) ? (
                              <span className="spinner-border spinner-border-sm" role="status" />
                            ) : (
                              "Add"
                            )}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="modal-footer">
                  <button type="button" className="btn btn-outline-secondary" onClick={closeLinkModal}>
                    Close
                  </button>
                </div>
              </div>
            </div>
          </div>
          <div className="modal-backdrop fade show" />
        </>
      ) : null}
    </div>
  );
}
