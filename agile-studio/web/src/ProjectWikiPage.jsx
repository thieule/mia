import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
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

/** Root key for expand/collapse of unfiled docs block (must not collide with numeric folder ids). */
const UNFILED_SECTION_KEY = "unfiled";

function docStoryKeys(d) {
  if (Array.isArray(d.story_keys)) return d.story_keys;
  if (d.story_key) return [d.story_key];
  return [];
}

function sortDocsByTitle(a, b) {
  const ta = (a.title || "").toLowerCase();
  const tb = (b.title || "").toLowerCase();
  if (ta !== tb) return ta < tb ? -1 : 1;
  return (a.id || 0) - (b.id || 0);
}

function WikiTreeDocRow({ doc, selId, onSelectDoc }) {
  const keys = docStoryKeys(doc);
  return (
    <li className="as-wiki-tree-doc-li">
      <button
        type="button"
        className={`as-wiki-tree-doc-btn ${doc.id === selId ? "is-active" : ""}`}
        onClick={() => onSelectDoc(doc)}
      >
        <span className="as-wiki-folder-caret as-wiki-folder-caret--spacer" aria-hidden />
        <i className="bi bi-file-earmark-text as-wiki-tree-doc-icon" aria-hidden />
        <span className="as-wiki-tree-doc-title text-truncate">{doc.title || "Untitled"}</span>
        {doc.is_draft ? (
          <span className="badge rounded-pill bg-warning text-dark as-wiki-draft-badge flex-shrink-0">Draft</span>
        ) : null}
      </button>
      {keys.length ? (
        <div className="as-wiki-tree-doc-meta">
          <span className="font-monospace text-truncate">{doc.slug}</span>
          <div className="as-wiki-story-chips as-wiki-story-chips--compact">
            {keys.slice(0, 3).map((k) => (
              <span key={k} className="as-wiki-chip">
                {k}
              </span>
            ))}
            {keys.length > 3 ? <span className="as-wiki-chip as-wiki-chip-more">+{keys.length - 3}</span> : null}
          </div>
        </div>
      ) : (
        <div className="as-wiki-tree-doc-meta">
          <span className="font-monospace text-truncate">{doc.slug}</span>
        </div>
      )}
    </li>
  );
}

/** One folder row + nested folders and documents (single `<li>`). */
function WikiFolderNode({
  node,
  expandedFolders,
  toggleFolder,
  docsByFolderId,
  createInFolderId,
  selId,
  onSelectDoc,
  onFolderNameClick,
  onAddChild,
  onDeleteFolder,
}) {
  const childFolders = node.children || [];
  const folderDocs = [...(docsByFolderId.get(node.id) || [])].sort(sortDocsByTitle);
  const open = expandedFolders.has(node.id);
  const hasSubtree = childFolders.length > 0 || folderDocs.length > 0;
  const folderTarget = createInFolderId === node.id;
  return (
    <li>
      <div className="as-wiki-folder-row">
        {hasSubtree ? (
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
          className={`as-wiki-folder-name ${folderTarget ? "is-create-target" : ""}`}
          onClick={() => onFolderNameClick(node.id)}
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
      {open ? (
        <>
          {childFolders.length > 0 ? (
            <ul className="as-wiki-folder-tree-ul as-wiki-folder-tree-nested">
              {childFolders.map((ch) => (
                <WikiFolderNode
                  key={ch.id}
                  node={ch}
                  expandedFolders={expandedFolders}
                  toggleFolder={toggleFolder}
                  docsByFolderId={docsByFolderId}
                  createInFolderId={createInFolderId}
                  selId={selId}
                  onSelectDoc={onSelectDoc}
                  onFolderNameClick={onFolderNameClick}
                  onAddChild={onAddChild}
                  onDeleteFolder={onDeleteFolder}
                />
              ))}
            </ul>
          ) : null}
          {folderDocs.length > 0 ? (
            <ul className="as-wiki-folder-tree-ul as-wiki-folder-tree-nested as-wiki-folder-tree-docs">
              {folderDocs.map((d) => (
                <WikiTreeDocRow key={d.id} doc={d} selId={selId} onSelectDoc={onSelectDoc} />
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </li>
  );
}

/** Project Documentation / wiki: folder tree, list, search, edit, story links, wiki:slug. */
export default function ProjectWikiPage({ projectId, initialSlug, setErr }) {
  const navigate = useNavigate();
  const [libraryDocs, setLibraryDocs] = useState([]);
  /** When non-null, sidebar shows search hits instead of full library (still grouped by folder). */
  const [searchHits, setSearchHits] = useState(null);
  const [folderTree, setFolderTree] = useState([]);
  const [expandedFolders, setExpandedFolders] = useState(() => new Set());
  /** New documents are created in this folder until cleared (click folder name to set). */
  const [createInFolderId, setCreateInFolderId] = useState(null);
  const [docFolderId, setDocFolderId] = useState(null);
  const [stories, setStories] = useState([]);
  const [kw, setKw] = useState("");
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
      setExpandedFolders(new Set([UNFILED_SECTION_KEY, ...collectFolderIds(tree)]));
    } catch (e) {
      setErr?.(e?.message || String(e));
    }
  }, [projectId, setErr]);

  const loadLibraryDocs = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const rows = await apiGet(`/projects/${projectId}/docs?limit=500`);
      setLibraryDocs(Array.isArray(rows) ? rows : []);
    } catch (e) {
      setErr?.(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [projectId, setErr]);

  useEffect(() => {
    loadLibraryDocs();
  }, [loadLibraryDocs]);

  useEffect(() => {
    loadStories();
  }, [loadStories]);

  useEffect(() => {
    loadFolderTree();
  }, [loadFolderTree]);

  const flatFolderOptions = useMemo(() => flattenWikiFolders(folderTree), [folderTree]);

  const docsForTree = searchHits !== null ? searchHits : libraryDocs;

  const docsByFolderId = useMemo(() => {
    const m = new Map();
    const arr = Array.isArray(docsForTree) ? docsForTree : [];
    for (const d of arr) {
      if (!d || typeof d !== "object") continue;
      const fid = d.folder_id != null ? Number(d.folder_id) : null;
      if (fid == null || !Number.isFinite(fid)) continue;
      if (!m.has(fid)) m.set(fid, []);
      m.get(fid).push(d);
    }
    return m;
  }, [docsForTree]);

  const unfiledDocs = useMemo(() => {
    const arr = Array.isArray(docsForTree) ? docsForTree : [];
    const out = [];
    for (const raw of arr) {
      const d = raw;
      if (!d || typeof d !== "object") continue;
      const fid = d.folder_id != null ? Number(d.folder_id) : null;
      if (fid == null || !Number.isFinite(fid)) out.push(d);
    }
    out.sort(sortDocsByTitle);
    return out;
  }, [docsForTree]);

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

  /** Story » Docs "New document": location.state.createDocForStoryId + nonce → tạo doc có story_ids, mở editor. */
  useEffect(() => {
    if (!projectId) return;
    const raw = location.state?.createDocForStoryId;
    const nonce = location.state?.createDocNonce;
    if (raw == null || typeof nonce !== "string") return;

    const sid = Number(raw);
    const pathPlusSearch = `${location.pathname}${location.search || ""}`;
    if (!Number.isFinite(sid) || sid <= 0) {
      navigate(pathPlusSearch, { replace: true, state: {} });
      return;
    }

    const dedupeKey = `asWikiCreate:${nonce}`;
    if (sessionStorage.getItem(dedupeKey)) return;
    sessionStorage.setItem(dedupeKey, "1");

    navigate(pathPlusSearch, { replace: true, state: {} });

    (async () => {
      try {
        const d = await apiPost(`/projects/${projectId}/docs`, {
          title: "New document",
          content: "",
          story_ids: [sid],
          folder_id: null,
          is_draft: true,
        });
        await loadLibraryDocs();
        applyDoc(d);
      } catch (e) {
        sessionStorage.removeItem(dedupeKey);
        setErr?.(e?.message || String(e));
      }
    })();
  }, [projectId, location.state, location.pathname, location.search, navigate, loadLibraryDocs, applyDoc, setErr]);

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
        await loadLibraryDocs();
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
    loadLibraryDocs,
    setErr,
  ]);

  const runSearch = async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const kwQ = kw.trim();
      if (kwQ) {
        const q = new URLSearchParams({ query: kwQ, top_k: "50" });
        const res = await apiGet(`/projects/${projectId}/docs/search?${q}`);
        setSearchHits(Array.isArray(res?.results) ? res.results : []);
      } else {
        setSearchHits(null);
        await loadLibraryDocs();
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

  const onFolderNameClick = useCallback((folderId) => {
    setCreateInFolderId(folderId);
    setExpandedFolders((prev) => new Set(prev).add(folderId));
  }, []);

  const onLibraryRootClick = useCallback(() => {
    setCreateInFolderId(null);
    setExpandedFolders((prev) => new Set(prev).add(UNFILED_SECTION_KEY));
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
        setCreateInFolderId((prev) => (prev === node.id ? null : prev));
        await loadFolderTree();
        await loadLibraryDocs();
      } catch (e) {
        setErr?.(e?.message || String(e));
      }
    },
    [projectId, loadFolderTree, loadLibraryDocs, setErr]
  );

  const onCreate = async () => {
    try {
      const folder_id = createInFolderId;
      const d = await apiPost(`/projects/${projectId}/docs`, {
        title: "New document",
        content: "",
        story_ids: [],
        folder_id,
        is_draft: true,
      });
      await loadLibraryDocs();
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
      await loadLibraryDocs();
    } catch (e) {
      setErr?.(e?.message || String(e));
    }
  };

  const selectedDoc = useMemo(() => {
    if (!selId) return null;
    const fromLib = libraryDocs.find((x) => x.id === selId);
    if (fromLib) return fromLib;
    const tree = Array.isArray(docsForTree) ? docsForTree : [];
    return tree.find((x) => x.id === selId) ?? null;
  }, [selId, libraryDocs, docsForTree]);

  return (
    <div className="as-wiki-page">
      <header className="as-wiki-header as-page-head d-flex flex-wrap justify-content-between align-items-start gap-3 mb-3">
        <div>
          <p className="as-wiki-kicker mb-2">Knowledge base</p>
          <h1 className="as-wiki-page-title">Documentation</h1>
          <p className="as-wiki-lead mb-0">
            Markdown, search, cross-links{" "}
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

      <div className="as-wiki-workbench">
        <div className="row g-0 as-wiki-grid">
        <div className="col-12 col-lg-4 col-xl-4 order-1 as-wiki-col as-wiki-col--nav">
          <aside className="as-wiki-sidebar h-100">
            <div className="as-wiki-sidebar-toolbar">
              <div className="input-group as-wiki-search-group mb-3">
                <input
                  type="search"
                  className="form-control"
                  placeholder="Search documents…"
                  value={kw}
                  onChange={(e) => setKw(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      runSearch();
                    }
                  }}
                  aria-label="Search documents"
                />
                <button
                  type="button"
                  className="btn btn-outline-secondary as-wiki-search-submit"
                  onClick={runSearch}
                  title="Search"
                  aria-label="Search"
                >
                  <i className="bi bi-search" aria-hidden />
                </button>
              </div>

              {searchHits !== null ? (
                <div className="alert alert-light border py-2 px-3 small mb-3 as-wiki-search-banner">
                  <span className="text-secondary">Showing search results.</span>{" "}
                  <button
                    type="button"
                    className="btn btn-link btn-sm p-0 align-baseline"
                    onClick={() => {
                      setSearchHits(null);
                      loadLibraryDocs();
                    }}
                  >
                    Show full library
                  </button>
                </div>
              ) : null}

              <div className="as-wiki-folder-panel mb-3">
                <div className="as-wiki-folder-panel-hd d-flex align-items-center justify-content-between gap-2 flex-wrap mb-2">
                  <span>Documents</span>
                  <div className="d-flex flex-wrap gap-1 align-items-center">
                    <button
                      type="button"
                      className="btn btn-sm btn-outline-primary"
                      onClick={() => createFolder(null)}
                      title="New root folder"
                    >
                      <i className="bi bi-folder-plus me-1" aria-hidden />
                      Folder
                    </button>
                    <button type="button" className="btn btn-sm btn-outline-primary" onClick={onCreate} title="New document">
                      <i className="bi bi-plus-lg me-1" aria-hidden />
                      New doc
                    </button>
                  </div>
                </div>
                <div className="as-wiki-folder-scroll">
                  {loading && libraryDocs.length === 0 ? (
                    <p className="small text-secondary mb-0 py-2">Loading library…</p>
                  ) : (
                    <ul className="as-wiki-folder-tree-ul as-wiki-library-tree-root">
                      <li>
                        <div className="as-wiki-folder-row">
                          <button
                            type="button"
                            className="as-wiki-folder-caret"
                            onClick={() => toggleFolder(UNFILED_SECTION_KEY)}
                            aria-expanded={expandedFolders.has(UNFILED_SECTION_KEY)}
                            aria-label={expandedFolders.has(UNFILED_SECTION_KEY) ? "Collapse" : "Expand"}
                          >
                            <i
                              className={`bi ${expandedFolders.has(UNFILED_SECTION_KEY) ? "bi-chevron-down" : "bi-chevron-right"}`}
                              aria-hidden
                            />
                          </button>
                          <button
                            type="button"
                            className="as-wiki-folder-name as-wiki-folder-name--root"
                            onClick={onLibraryRootClick}
                          >
                            <i className="bi bi-inbox me-1" aria-hidden />
                            <span className="text-truncate">Library root (unfiled)</span>
                          </button>
                        </div>
                        {expandedFolders.has(UNFILED_SECTION_KEY) ? (
                          <ul className="as-wiki-folder-tree-ul as-wiki-folder-tree-nested as-wiki-folder-tree-docs">
                            {unfiledDocs.length === 0 ? (
                              <li className="small text-secondary py-2 ps-1">No documents in library root.</li>
                            ) : (
                              unfiledDocs.map((d) => (
                                <WikiTreeDocRow key={d.id} doc={d} selId={selId} onSelectDoc={applyDoc} />
                              ))
                            )}
                          </ul>
                        ) : null}
                      </li>
                      {folderTree.length > 0
                        ? folderTree.map((node) => (
                            <WikiFolderNode
                              key={node.id}
                              node={node}
                              expandedFolders={expandedFolders}
                              toggleFolder={toggleFolder}
                              docsByFolderId={docsByFolderId}
                              createInFolderId={createInFolderId}
                              selId={selId}
                              onSelectDoc={applyDoc}
                              onFolderNameClick={onFolderNameClick}
                              onAddChild={(pid) => createFolder(pid)}
                              onDeleteFolder={onDeleteFolderNode}
                            />
                          ))
                        : null}
                    </ul>
                  )}
                  {!loading && folderTree.length === 0 ? (
                    <p className="small text-secondary mb-0 mt-2 as-wiki-folder-empty">
                      No folders — use Folder or New doc above, or keep docs in library root.
                    </p>
                  ) : null}
                </div>
              </div>
            </div>
          </aside>
        </div>

        <div className="col-12 col-lg-8 col-xl-8 order-2 as-wiki-col as-wiki-col--main">
          <main className="as-wiki-editor-wrap as-wiki-editor-wrap--main h-100">
            {selId ? (
              <>
                <div className="as-wiki-editor-toolbar">
                  <div className="as-wiki-title-row mb-0">
                    <input
                      className="form-control form-control-lg as-wiki-title-input w-100"
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="Document title"
                      aria-label="Document title"
                    />
                  </div>
                </div>

                <div className="as-panel-bd as-wiki-editor-bd">
                  <MarkdownEditorField
                    value={body}
                    onChange={setBody}
                    height={520}
                    previewMode="live"
                    insertToolbar
                    projectId={projectId}
                  />

                  <div className="as-wiki-editor-meta-row d-flex flex-wrap align-items-center gap-2 mt-3 pt-3">
                    <label htmlFor="wiki-doc-folder" className="small fw-semibold text-secondary mb-0 flex-shrink-0">
                      Folder
                    </label>
                    <select
                      id="wiki-doc-folder"
                      className="form-select form-select-sm as-wiki-doc-folder-select as-wiki-editor-folder-select-full"
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

                  <footer className="as-wiki-editor-foot mt-3 d-flex flex-wrap align-items-center justify-content-between gap-3">
                    <div className="d-flex flex-wrap gap-3 align-items-center as-wiki-editor-foot-primary">
                      <span className="as-wiki-foot-slug font-monospace user-select-all">/{selectedDoc?.slug}</span>
                      {linkedStoryIds.length > 0 ? (
                        <span className="as-wiki-foot-meta">
                          {linkedStoryIds.length} {linkedStoryIds.length === 1 ? "story" : "stories"} linked
                        </span>
                      ) : (
                        <span className="as-wiki-foot-meta">Library only (no story links)</span>
                      )}
                    </div>
                    <div className="d-flex flex-wrap align-items-center gap-3 justify-content-end as-wiki-editor-foot-actions">
                      <div className="form-check form-switch as-wiki-draft-switch mb-0">
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
                      <button type="button" className="btn btn-outline-danger as-wiki-btn flex-shrink-0" onClick={onDelete}>
                        <i className="bi bi-trash me-1" aria-hidden />
                        Delete
                      </button>
                    </div>
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
                    Choose a document in the tree on the left, or create a new one.
                  </p>
                </div>
              </div>
            )}
          </main>
        </div>
        </div>
      </div>
    </div>
  );
}
