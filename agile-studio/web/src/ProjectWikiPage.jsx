import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import MarkdownEditorField from "./MarkdownEditorField.jsx";
import { apiDelete, apiGet, apiPost, apiPut } from "./api.js";

function sortIds(a, b) {
  return a - b;
}

function flattenWikiFolders(nodes, prefix = "") {
  const out = [];
  for (const n of nodes || []) {
    const label = prefix ? `${prefix} / ${n.name}` : n.name;
    out.push({ id: n.id, label });
    out.push(...flattenWikiFolders(n.children || [], label));
  }
  return out;
}

function collectFolderIds(nodes, s = new Set()) {
  for (const n of nodes || []) {
    s.add(n.id);
    collectFolderIds(n.children, s);
  }
  return s;
}

function WikiFolderTree({
  nodes,
  depth,
  expandedFolders,
  toggleFolder,
  listFilter,
  onPickFolder,
  onAddChild,
  onDeleteFolder,
}) {
  if (!nodes?.length) return null;
  return (
    <ul className={`as-wiki-folder-tree-ul${depth > 0 ? " as-wiki-folder-tree-nested" : ""}`}>
      {nodes.map((node) => {
        const hasChildren = node.children?.length > 0;
        const open = expandedFolders.has(node.id);
        const selected = listFilter.type === "folder" && listFilter.id === node.id;
        return (
          <li key={node.id}>
            <div className="as-wiki-folder-row">
              {hasChildren ? (
                <button
                  type="button"
                  className="as-wiki-folder-caret"
                  onClick={() => toggleFolder(node.id)}
                  aria-expanded={open}
                  aria-label={open ? "Collapse" : "Expand"}
                >
                  <i className={`bi ${open ? "bi-chevron-down" : "bi-chevron-right"}`} aria-hidden />
                </button>
              ) : (
                <span className="as-wiki-folder-caret as-wiki-folder-caret--spacer" aria-hidden />
              )}
              <button
                type="button"
                className={`as-wiki-folder-name ${selected ? "is-active" : ""}`}
                onClick={() => onPickFolder(node.id)}
              >
                <i className="bi bi-folder2 me-1" aria-hidden />
                <span className="text-truncate">{node.name}</span>
              </button>
              <button
                type="button"
                className="as-wiki-folder-mini"
                onClick={(e) => {
                  e.stopPropagation();
                  onAddChild(node.id);
                }}
                title="New subfolder"
              >
                <i className="bi bi-folder-plus" />
              </button>
              <button
                type="button"
                className="as-wiki-folder-mini as-wiki-folder-mini--danger"
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteFolder(node);
                }}
                title="Delete folder"
              >
                <i className="bi bi-trash" />
              </button>
            </div>
            {hasChildren && open ? (
              <WikiFolderTree
                nodes={node.children}
                depth={depth + 1}
                expandedFolders={expandedFolders}
                toggleFolder={toggleFolder}
                listFilter={listFilter}
                onPickFolder={onPickFolder}
                onAddChild={onAddChild}
                onDeleteFolder={onDeleteFolder}
              />
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

/** Project Documentation / wiki: folder tree, list, search, edit, story links, wiki:slug. */
export default function ProjectWikiPage({ projectId, initialSlug, setErr }) {
  const navigate = useNavigate();
  const [docs, setDocs] = useState([]);
  const [folderTree, setFolderTree] = useState([]);
  const [expandedFolders, setExpandedFolders] = useState(() => new Set());
  const [listFilter, setListFilter] = useState(/** @type {{ type: 'all' } | { type: 'unfiled' } | { type: 'folder', id: number }} */ ({ type: "all" }));
  const [docFolderId, setDocFolderId] = useState(null);
  const [stories, setStories] = useState([]);
  const [kw, setKw] = useState("");
  const [sem, setSem] = useState("");
  const [selId, setSelId] = useState(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [isDraft, setIsDraft] = useState(true);
  const [linkedStoryIds, setLinkedStoryIds] = useState([]);
  const [storySearch, setStorySearch] = useState("");
  const [storySuggestOpen, setStorySuggestOpen] = useState(false);
  const blurSuggestTimer = useRef(null);
  const lastSavedRef = useRef({
    title: "",
    body: "",
    id: null,
    storyKey: "",
    folderKey: "null",
    isDraft: true,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const loadStories = useCallback(async () => {
    if (!projectId) return;
    try {
      const rows = await apiGet(`/projects/${projectId}/stories?limit=500`);
      setStories(Array.isArray(rows) ? rows : []);
    } catch (e) {
      setErr?.(e?.message || String(e));
    }
  }, [projectId, setErr]);

  const loadFolderTree = useCallback(async () => {
    if (!projectId) return;
    try {
      const res = await apiGet(`/projects/${projectId}/wiki-folders/tree`);
      const tree = Array.isArray(res?.tree) ? res.tree : [];
      setFolderTree(tree);
      setExpandedFolders(collectFolderIds(tree));
    } catch (e) {
      setErr?.(e?.message || String(e));
    }
  }, [projectId, setErr]);

  const refresh = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      let path = `/projects/${projectId}/docs?limit=500`;
      if (listFilter.type === "unfiled") path += "&unfiled=true";
      else if (listFilter.type === "folder") path += `&in_folder=${listFilter.id}`;
      const rows = await apiGet(path);
      setDocs(Array.isArray(rows) ? rows : []);
    } catch (e) {
      setErr?.(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [projectId, listFilter, setErr]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    loadStories();
  }, [loadStories]);

  useEffect(() => {
    loadFolderTree();
  }, [loadFolderTree]);

  const flatFolderOptions = useMemo(() => flattenWikiFolders(folderTree), [folderTree]);

  useEffect(
    () => () => {
      if (blurSuggestTimer.current) clearTimeout(blurSuggestTimer.current);
    },
    []
  );

  const linkedKey = useMemo(() => [...linkedStoryIds].sort(sortIds).join(","), [linkedStoryIds]);
  const folderKey = docFolderId == null ? "null" : String(docFolderId);

  const docStoryIdsFromApi = (d) => {
    if (d == null) return [];
    if (Array.isArray(d.story_ids) && d.story_ids.length) return [...d.story_ids].sort(sortIds);
    if (d.story_id != null) return [d.story_id];
    return [];
  };

  const applyDoc = useCallback(
    (d, { syncUrl = true } = {}) => {
      if (!d) return;
      setSelId(d.id);
      setTitle(d.title || "");
      setBody(d.content || "");
      setIsDraft(Boolean(d.is_draft));
      setDocFolderId(d.folder_id != null ? Number(d.folder_id) : null);
      const ids = docStoryIdsFromApi(d);
      setLinkedStoryIds(ids);
      const fk = d.folder_id != null ? String(d.folder_id) : "null";
      lastSavedRef.current = {
        title: d.title || "",
        body: d.content || "",
        id: d.id,
        storyKey: ids.join(","),
        folderKey: fk,
        isDraft: Boolean(d.is_draft),
      };
      if (syncUrl && projectId && d.slug) {
        const want = `/p/${projectId}/wiki/${encodeURIComponent(d.slug)}`;
        if (window.location.pathname !== want) navigate(want, { replace: true });
      }
    },
    [navigate, projectId]
  );

  useEffect(() => {
    if (!projectId || !initialSlug) return;
    let cancelled = false;
    const slug = decodeURIComponent(initialSlug);
    (async () => {
      try {
        const d = await apiGet(`/projects/${projectId}/docs/slug/${encodeURIComponent(slug)}`);
        if (!cancelled) applyDoc(d, { syncUrl: false });
      } catch {
        if (!cancelled) setErr?.("Document not found for this slug.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, initialSlug, applyDoc, setErr]);

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
    if (
      ls.id === selId &&
      title === ls.title &&
      body === ls.body &&
      linkedKey === ls.storyKey &&
      folderKey === ls.folderKey &&
      isDraft === ls.isDraft
    )
      return;
    const t = setTimeout(async () => {
      setSaving(true);
      try {
        await apiPut(`/projects/${projectId}/docs/${selId}`, {
          title: title.trim() || "Untitled",
          content: body,
          is_draft: isDraft,
          folder_id: docFolderId,
          story_ids: linkedStoryIds.filter((x) => Number.isFinite(x) && x > 0),
        });
        lastSavedRef.current = {
          title: title.trim(),
          body,
          id: selId,
          storyKey: linkedKey,
          folderKey,
          isDraft,
        };
        await refresh();
      } catch (e) {
        setErr?.(e?.message || String(e));
      } finally {
        setSaving(false);
      }
    }, 2000);
    return () => clearTimeout(t);
  }, [
    title,
    body,
    isDraft,
    linkedKey,
    folderKey,
    docFolderId,
    linkedStoryIds,
    selId,
    projectId,
    refresh,
    setErr,
  ]);

  const runSearch = async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const semQ = sem.trim();
      const kwQ = kw.trim();
      if (semQ) {
        const q = new URLSearchParams({ semantic_query: semQ, top_k: "25" });
        const res = await apiGet(`/projects/${projectId}/docs/search?${q}`);
        setDocs(Array.isArray(res?.results) ? res.results : []);
      } else if (kwQ) {
        const q = new URLSearchParams({ query: kwQ, top_k: "50" });
        const res = await apiGet(`/projects/${projectId}/docs/search?${q}`);
        setDocs(Array.isArray(res?.results) ? res.results : []);
      } else {
        await refresh();
      }
    } catch (e) {
      setErr?.(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  const linkedStoriesResolved = useMemo(() => {
    const map = new Map(stories.map((s) => [s.id, s]));
    return linkedStoryIds.map((id) => map.get(id)).filter(Boolean);
  }, [linkedStoryIds, stories]);

  const storySuggestions = useMemo(() => {
    const q = storySearch.trim().toLowerCase();
    const pool = stories
      .filter((s) => !linkedStoryIds.includes(s.id))
      .sort((a, b) => (Number(a.story_number) || 0) - (Number(b.story_number) || 0));
    if (!q) return pool.slice(0, 14);
    const out = [];
    for (const s of pool) {
      const key = String(s.story_key || "").toLowerCase();
      const tit = String(s.title || "").toLowerCase();
      if (key.includes(q) || tit.includes(q) || String(s.id) === q) out.push(s);
      if (out.length >= 14) break;
    }
    return out;
  }, [stories, storySearch, linkedStoryIds]);

  const addStoryLink = useCallback((sid) => {
    setLinkedStoryIds((prev) => (prev.includes(sid) ? prev : [...prev, sid].sort(sortIds)));
    setStorySearch("");
    setStorySuggestOpen(true);
  }, []);

  const removeStoryLink = useCallback((sid) => {
    setLinkedStoryIds((prev) => prev.filter((x) => x !== sid));
  }, []);

  const onStorySearchBlur = useCallback(() => {
    blurSuggestTimer.current = window.setTimeout(() => setStorySuggestOpen(false), 180);
  }, []);

  const onStorySearchFocus = useCallback(() => {
    if (blurSuggestTimer.current) clearTimeout(blurSuggestTimer.current);
    setStorySuggestOpen(true);
  }, []);

  const toggleFolder = useCallback((id) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const onPickFolder = useCallback((folderId) => {
    setListFilter({ type: "folder", id: folderId });
  }, []);

  const createFolder = useCallback(
    async (parentId) => {
      const label = parentId == null ? "New folder name (root level)" : "New subfolder name";
      const name = window.prompt(label);
      if (!name?.trim() || !projectId) return;
      try {
        await apiPost(`/projects/${projectId}/wiki-folders`, { name: name.trim(), parent_id: parentId });
        await loadFolderTree();
      } catch (e) {
        setErr?.(e?.message || String(e));
      }
    },
    [projectId, loadFolderTree, setErr]
  );

  const onDeleteFolderNode = useCallback(
    async (node) => {
      if (
        !projectId ||
        !window.confirm(
          `Delete folder "${node.name}" and all subfolders? Documents in these folders will move to library root (unfiled).`
        )
      )
        return;
      try {
        await apiDelete(`/projects/${projectId}/wiki-folders/${node.id}`);
        setListFilter((f) => (f.type === "folder" && f.id === node.id ? { type: "all" } : f));
        await loadFolderTree();
        await refresh();
      } catch (e) {
        setErr?.(e?.message || String(e));
      }
    },
    [projectId, loadFolderTree, refresh, setErr]
  );

  const onCreate = async () => {
    try {
      const folder_id = listFilter.type === "folder" ? listFilter.id : null;
      const d = await apiPost(`/projects/${projectId}/docs`, {
        title: "New document",
        content: "",
        story_ids: [],
        folder_id,
        is_draft: true,
      });
      await refresh();
      applyDoc(d);
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
      lastSavedRef.current = {
        title: "",
        body: "",
        id: null,
        storyKey: "",
        folderKey: "null",
        isDraft: true,
      };
      navigate(`/p/${projectId}/wiki`, { replace: true });
      await refresh();
    } catch (e) {
      setErr?.(e?.message || String(e));
    }
  };

  const selectedDoc = selId ? docs.find((x) => x.id === selId) : null;

  return (
    <div className="as-wiki-page">
      <header className="as-wiki-header as-page-head d-flex flex-wrap justify-content-between align-items-start gap-3 mb-4">
        <div>
          <p className="as-wiki-kicker mb-2">Knowledge base</p>
          <h1 className="as-wiki-page-title">Documentation</h1>
          <p className="as-wiki-lead mb-0">
            Markdown, semantic search, cross-links{" "}
            <code className="as-wiki-code-hint user-select-all">[label](wiki:slug)</code> — a document can link to multiple stories.
          </p>
        </div>
        {saving ? (
          <span className="as-wiki-save-pill">
            <span className="spinner-border spinner-border-sm me-1" role="status" />
            Saving…
          </span>
        ) : null}
      </header>

      <div className="row g-4 as-wiki-grid">
        <div className="col-lg-4">
          <aside className="as-wiki-sidebar as-panel h-100">
            <div className="as-wiki-sidebar-toolbar">
              <div className="input-group as-wiki-search-group mb-3">
                <span className="input-group-text">
                  <i className="bi bi-search" aria-hidden />
                </span>
                <input
                  type="search"
                  className="form-control"
                  placeholder="Search title or body…"
                  value={kw}
                  onChange={(e) => setKw(e.target.value)}
                  aria-label="Keyword search"
                />
              </div>
              <div className="input-group as-wiki-search-group mb-3">
                <span className="input-group-text" title="Semantic">
                  <i className="bi bi-stars" aria-hidden />
                </span>
                <input
                  type="search"
                  className="form-control"
                  placeholder="Semantic search…"
                  value={sem}
                  onChange={(e) => setSem(e.target.value)}
                  aria-label="Semantic search"
                />
              </div>
              <div className="d-flex flex-wrap gap-2 mb-4">
                <button type="button" className="btn btn-primary as-wiki-btn" onClick={runSearch}>
                  Search
                </button>
                <button
                  type="button"
                  className="btn btn-outline-secondary as-wiki-btn"
                  onClick={() => {
                    setKw("");
                    setSem("");
                    setListFilter({ type: "all" });
                  }}
                >
                  Reset
                </button>
              </div>

              <div className="as-wiki-folder-panel mb-4">
                <div className="as-wiki-folder-panel-hd d-flex align-items-center justify-content-between gap-2 mb-2">
                  <span>Folders</span>
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-primary"
                    onClick={() => createFolder(null)}
                    title="New root folder"
                  >
                    <i className="bi bi-folder-plus me-1" aria-hidden />
                    Folder
                  </button>
                </div>
                <div className="as-wiki-folder-filter d-flex flex-wrap gap-1 mb-2">
                  <button
                    type="button"
                    className={`btn btn-sm ${listFilter.type === "all" ? "btn-primary" : "btn-outline-secondary"}`}
                    onClick={() => setListFilter({ type: "all" })}
                  >
                    All
                  </button>
                  <button
                    type="button"
                    className={`btn btn-sm ${listFilter.type === "unfiled" ? "btn-primary" : "btn-outline-secondary"}`}
                    onClick={() => setListFilter({ type: "unfiled" })}
                  >
                    Unfiled
                  </button>
                </div>
                {folderTree.length > 0 ? (
                  <WikiFolderTree
                    nodes={folderTree}
                    depth={0}
                    expandedFolders={expandedFolders}
                    toggleFolder={toggleFolder}
                    listFilter={listFilter}
                    onPickFolder={onPickFolder}
                    onAddChild={(pid) => createFolder(pid)}
                    onDeleteFolder={onDeleteFolderNode}
                  />
                ) : (
                  <p className="small text-secondary mb-0 as-wiki-folder-empty">No folders yet — create one above.</p>
                )}
              </div>

              <button type="button" className="btn btn-outline-primary w-100 mb-4 as-wiki-new-btn" onClick={onCreate}>
                <i className="bi bi-plus-lg me-1" aria-hidden />
                New document
              </button>
            </div>
            <div className="as-wiki-list-hd">Library</div>
            <div className="as-wiki-list list-group list-group-flush">
              {loading ? (
                <div className="as-wiki-list-empty py-4 text-secondary small">Loading…</div>
              ) : docs.length === 0 ? (
                <div className="as-wiki-list-empty py-4 text-secondary small">No documents yet.</div>
              ) : (
                docs.map((d) => {
                  const keys = Array.isArray(d.story_keys) ? d.story_keys : d.story_key ? [d.story_key] : [];
                  return (
                    <button
                      key={d.id}
                      type="button"
                      className={`as-wiki-list-item list-group-item list-group-item-action ${d.id === selId ? "active" : ""}`}
                      onClick={() => applyDoc(d)}
                    >
                      <div className="as-wiki-list-title text-truncate">{d.title || "Untitled"}</div>
                      <div className="as-wiki-list-meta text-truncate">
                        <span className="font-monospace">{d.slug}</span>
                        {d.is_draft ? (
                          <span className="badge rounded-pill bg-warning text-dark ms-1 as-wiki-draft-badge">Draft</span>
                        ) : null}
                      </div>
                      {keys.length ? (
                        <div className="as-wiki-story-chips">
                          {keys.slice(0, 4).map((k) => (
                            <span key={k} className="as-wiki-chip">
                              {k}
                            </span>
                          ))}
                          {keys.length > 4 ? <span className="as-wiki-chip as-wiki-chip-more">+{keys.length - 4}</span> : null}
                        </div>
                      ) : null}
                    </button>
                  );
                })
              )}
            </div>
          </aside>
        </div>

        <div className="col-lg-8">
          <main className="as-wiki-editor-wrap as-panel">
            {selId ? (
              <>
                <div className="as-wiki-editor-toolbar">
                  <div className="d-flex flex-wrap align-items-center gap-3 mb-4 as-wiki-title-row">
                    <input
                      className="form-control form-control-lg as-wiki-title-input"
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="Document title"
                      aria-label="Document title"
                    />
                    <div className="form-check form-switch ms-auto as-wiki-draft-switch">
                      <input
                        className="form-check-input"
                        type="checkbox"
                        id="wiki-draft-toggle"
                        checked={isDraft}
                        onChange={(e) => setIsDraft(e.target.checked)}
                      />
                      <label className="form-check-label" htmlFor="wiki-draft-toggle">
                        Draft
                      </label>
                    </div>
                    <button type="button" className="btn btn-outline-danger as-wiki-btn" onClick={onDelete}>
                      <i className="bi bi-trash me-1" aria-hidden />
                      Delete
                    </button>
                  </div>
                  <div className="d-flex flex-wrap align-items-center gap-2 mb-1 as-wiki-folder-doc-row">
                    <label htmlFor="wiki-doc-folder" className="small fw-semibold text-secondary mb-0 flex-shrink-0">
                      Folder
                    </label>
                    <select
                      id="wiki-doc-folder"
                      className="form-select form-select-sm as-wiki-doc-folder-select"
                      value={docFolderId == null ? "" : String(docFolderId)}
                      onChange={(e) => {
                        const v = e.target.value;
                        setDocFolderId(v === "" ? null : Number(v));
                      }}
                    >
                      <option value="">Library root (unfiled)</option>
                      {flatFolderOptions.map((o) => (
                        <option key={o.id} value={String(o.id)}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="as-panel-bd as-wiki-editor-bd">
                  <MarkdownEditorField
                    value={body}
                    onChange={setBody}
                    height={520}
                    previewMode="live"
                    previewOptions={wikiPreviewOptions}
                  />

                  <section
                    className="as-wiki-link-section as-wiki-link-section--below"
                    aria-labelledby="wiki-story-links-label"
                  >
                    <div className="as-wiki-link-section-hd" id="wiki-story-links-label">
                      <span className="as-wiki-link-label">Linked stories</span>
                      <span className="as-wiki-link-hint">
                        Search to add stories. They appear as tags; use × to remove a link.
                      </span>
                    </div>

                    <div className="as-wiki-story-tags-bar" role="group" aria-label="Linked stories">
                      {linkedStoriesResolved.length === 0 ? (
                        <span className="as-wiki-story-tags-empty">No stories linked — use the search field below.</span>
                      ) : (
                        linkedStoriesResolved.map((s) => (
                          <span key={s.id} className="as-wiki-story-tag">
                            <span className="as-wiki-story-tag-key font-monospace">{s.story_key || `#${s.story_number}`}</span>
                            <span className="as-wiki-story-tag-title text-truncate" title={s.title}>
                              {s.title}
                            </span>
                            <Link className="as-wiki-story-tag-open" to={`/p/${projectId}/story/${s.id}`} title="Open story">
                              <i className="bi bi-box-arrow-up-right" aria-hidden />
                            </Link>
                            <button
                              type="button"
                              className="as-wiki-story-tag-remove"
                              aria-label={`Remove ${s.story_key || s.id}`}
                              onClick={() => removeStoryLink(s.id)}
                            >
                              <i className="bi bi-x-lg" aria-hidden />
                            </button>
                          </span>
                        ))
                      )}
                    </div>

                    <div className="as-wiki-story-add-wrap">
                      <label className="visually-hidden" htmlFor="wiki-story-search">
                        Search stories to add
                      </label>
                      <div className="as-wiki-story-add-inner">
                        <i className="bi bi-plus-lg as-wiki-story-add-icon" aria-hidden />
                        <input
                          id="wiki-story-search"
                          type="search"
                          className="form-control as-wiki-story-search-input"
                          placeholder="Search by key or title, then pick from the list…"
                          value={storySearch}
                          onChange={(e) => {
                            setStorySearch(e.target.value);
                            setStorySuggestOpen(true);
                          }}
                          onFocus={onStorySearchFocus}
                          onBlur={onStorySearchBlur}
                          autoComplete="off"
                          disabled={stories.length === 0}
                        />
                      </div>
                      {stories.length === 0 ? (
                        <p className="as-wiki-story-add-msg mb-0">Could not load stories.</p>
                      ) : storySuggestOpen ? (
                        <ul className="as-wiki-story-suggest-list" role="listbox">
                          {storySuggestions.length === 0 ? (
                            <li className="as-wiki-story-suggest-empty" role="presentation">
                              {storySearch.trim()
                                ? "No matching stories — try different keywords."
                                : "All available stories are already linked."}
                            </li>
                          ) : (
                            storySuggestions.map((s) => (
                              <li key={s.id} role="option">
                                <button
                                  type="button"
                                  className="as-wiki-story-suggest-item"
                                  onMouseDown={(e) => e.preventDefault()}
                                  onClick={() => addStoryLink(s.id)}
                                >
                                  <span className="as-wiki-story-suggest-key font-monospace">{s.story_key || `#${s.story_number}`}</span>
                                  <span className="as-wiki-story-suggest-title text-truncate">{s.title}</span>
                                </button>
                              </li>
                            ))
                          )}
                        </ul>
                      ) : null}
                    </div>
                  </section>

                  <footer className="as-wiki-editor-foot mt-3 d-flex flex-wrap gap-3 align-items-center">
                    <span className="as-wiki-foot-slug font-monospace user-select-all">/{selectedDoc?.slug}</span>
                    {linkedStoryIds.length > 0 ? (
                      <span className="as-wiki-foot-meta">
                        {linkedStoryIds.length} {linkedStoryIds.length === 1 ? "story" : "stories"} linked
                      </span>
                    ) : (
                      <span className="as-wiki-foot-meta">Library only (no story links)</span>
                    )}
                  </footer>
                </div>
              </>
            ) : (
              <div className="as-panel-bd as-wiki-empty-state">
                <div className="as-empty as-wiki-empty-inner">
                  <div className="as-empty-icon" aria-hidden>
                    <i className="bi bi-journal-text" />
                  </div>
                  <p className="mb-2 fw-medium">Select a document or create a new one</p>
                  <p className="small text-secondary mb-0">
                    Use the sidebar search or New document to get started.
                  </p>
                </div>
              </div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
