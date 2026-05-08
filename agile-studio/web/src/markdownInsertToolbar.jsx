import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet } from "./api.js";

function mdLinkLabel(raw) {
  const s = String(raw ?? "").trim() || "Untitled";
  return s.replace(/[\[\]]/g, "");
}

function insertStoryMarkdown(story, textApi, close, execute) {
  const id = story?.id;
  if (id == null || !textApi) return;
  const key = story.story_key ? `${story.story_key}: ` : "";
  const label = mdLinkLabel(`${key}${story.title || `Story #${id}`}`);
  textApi.replaceSelection(`[${label}](story:${id})`);
  execute?.();
  close?.();
}

function insertDocMarkdown(projectId, doc, textApi, close, execute) {
  if (!doc || !textApi || projectId == null) return;
  const label = mdLinkLabel(doc.title || doc.slug || "Document");
  const slug = String(doc.slug || "").trim();
  if (!slug) return;
  const safeWikiSlug = /^[a-zA-Z0-9_-]+$/.test(slug);
  const href = safeWikiSlug ? `wiki:${slug}` : `/p/${projectId}/wiki/${encodeURIComponent(slug)}`;
  textApi.replaceSelection(`[${label}](${href})`);
  execute?.();
  close?.();
}

function MarkdownInsertPopover({ close, execute, textApi, projectId }) {
  const [tab, setTab] = useState("story");
  const [query, setQuery] = useState("");
  const [stories, setStories] = useState([]);
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (projectId == null) return;
    let cancelled = false;
    setLoading(true);
    setErr(null);
    (async () => {
      try {
        const [stRes, docRes] = await Promise.all([
          apiGet(`/projects/${projectId}/stories`),
          apiGet(`/projects/${projectId}/docs?limit=120`),
        ]);
        if (cancelled) return;
        setStories(Array.isArray(stRes) ? stRes : []);
        setDocs(Array.isArray(docRes) ? docRes : []);
      } catch (e) {
        if (!cancelled) setErr(e?.message || String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const q = query.trim().toLowerCase();

  const filteredStories = useMemo(() => {
    if (!q) return stories;
    return stories.filter((s) => {
      const title = (s.title || "").toLowerCase();
      const sk = (s.story_key || "").toLowerCase();
      const id = String(s.id || "");
      return title.includes(q) || sk.includes(q) || id.includes(q);
    });
  }, [stories, q]);

  const filteredDocs = useMemo(() => {
    if (!q) return docs;
    return docs.filter((d) => {
      const title = (d.title || "").toLowerCase();
      const slug = (d.slug || "").toLowerCase();
      return title.includes(q) || slug.includes(q);
    });
  }, [docs, q]);

  const onPickStory = useCallback(
    (s) => insertStoryMarkdown(s, textApi, close, execute),
    [textApi, close, execute]
  );

  const onPickDoc = useCallback(
    (d) => insertDocMarkdown(projectId, d, textApi, close, execute),
    [projectId, textApi, close, execute]
  );

  if (projectId == null) {
    return (
      <div className="as-md-insert-popover as-md-insert-popover--panel">
        <p className="as-md-insert-popover-empty mb-0">Select a project to insert Story or Wiki links.</p>
      </div>
    );
  }

  if (!textApi) {
    return (
      <div className="as-md-insert-popover as-md-insert-popover--panel">
        <p className="as-md-insert-popover-empty mb-0">Markdown editor area is not available.</p>
      </div>
    );
  }

  return (
    <div className="as-md-insert-popover as-md-insert-popover--panel" role="dialog" aria-label="Insert Story or Wiki link">
      <div className="as-md-insert-popover-hd">
        <span className="as-md-insert-popover-hd-title">
          <i className="bi bi-link-45deg me-1" aria-hidden />
          Insert link
        </span>
        <span className="as-md-insert-popover-hd-hint text-muted small">Stories & wiki docs</span>
      </div>
      <div className="as-md-insert-popover-body">
        <div className="as-md-insert-search-wrap">
          <i className="bi bi-search as-md-insert-search-ico" aria-hidden />
          <input
            type="search"
            className="form-control form-control-sm as-md-insert-search"
            placeholder="Search by title, key, slug…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Filter stories and documents"
          />
        </div>
        <div className="as-md-insert-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "story"}
            className={`as-md-insert-tab ${tab === "story" ? "active" : ""}`}
            onClick={() => setTab("story")}
          >
            <i className="bi bi-kanban me-1" aria-hidden />
            Stories
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "document"}
            className={`as-md-insert-tab ${tab === "document" ? "active" : ""}`}
            onClick={() => setTab("document")}
          >
            <i className="bi bi-file-earmark-text me-1" aria-hidden />
            Wiki
          </button>
        </div>
        <div className="as-md-insert-list">
          {loading ? (
            <div className="as-md-insert-state">
              <span className="spinner-border spinner-border-sm text-primary me-2" role="status" />
              Loading…
            </div>
          ) : err ? (
            <div className="as-md-insert-state text-danger">{err}</div>
          ) : tab === "story" ? (
            filteredStories.length === 0 ? (
              <div className="as-md-insert-state text-muted fst-italic">No stories found.</div>
            ) : (
              <ul className="as-md-insert-ul">
                {filteredStories.map((s) => (
                  <li key={s.id}>
                    <button
                      type="button"
                      className="as-md-insert-row as-md-insert-row--story"
                      onClick={() => onPickStory(s)}
                    >
                      <span className="as-md-insert-row-meta">{s.story_key || `#${s.id}`}</span>
                      <span className="as-md-insert-row-title">{s.title || "Untitled"}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )
          ) : filteredDocs.length === 0 ? (
            <div className="as-md-insert-state text-muted fst-italic">No wiki documents found.</div>
          ) : (
            <ul className="as-md-insert-ul">
              {filteredDocs.map((d) => (
                <li key={d.id}>
                  <button
                    type="button"
                    className="as-md-insert-row as-md-insert-row--doc"
                    onClick={() => onPickDoc(d)}
                  >
                    <span className="as-md-insert-row-title">{d.title || "Untitled"}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * MDEditor toolbar command: dropdown to insert story / wiki Markdown links.
 */
export function createMarkdownInsertCommands(projectId) {
  /**
   * MDEditor only renders commands with keyCommand; popover commands must use
   * keyCommand "group" + groupName so barPopup[groupName] opens .w-md-editor-toolbar-child.
   */
  const cmd = {
    name: "insert-agile-link",
    keyCommand: "group",
    groupName: "agile-insert",
    execute: () => {},
    icon: (
      <span className="as-md-insert-toolbar-trigger">
        <span className="as-md-insert-toolbar-trigger-icons" aria-hidden>
          <i className="bi bi-kanban" />
          <i className="bi bi-file-earmark-text" />
        </span>
        <span className="as-md-insert-toolbar-trigger-label">Story · Wiki</span>
      </span>
    ),
    buttonProps: {
      className: "as-md-insert-toolbar-btn",
      "aria-label": "Insert Story or Wiki link into Markdown",
      title: "Insert Story / Wiki link",
    },
    children: ({ close, execute, textApi }) => (
      <MarkdownInsertPopover close={close} execute={execute} textApi={textApi} projectId={projectId} />
    ),
  };
  return [cmd];
}
