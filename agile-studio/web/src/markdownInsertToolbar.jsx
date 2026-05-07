import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet } from "./api.js";

function mdLinkLabel(raw) {
  const s = String(raw ?? "").trim() || "Không tên";
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
  const label = mdLinkLabel(doc.title || doc.slug || "Tài liệu");
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
      <div className="as-md-insert-popover small text-secondary border rounded shadow-sm bg-white">
        Chọn project để chèn story hoặc tài liệu.
      </div>
    );
  }

  if (!textApi) {
    return (
      <div className="as-md-insert-popover small text-secondary border rounded shadow-sm bg-white p-2">
        Không có vùng soạn thảo — chỉ dùng khi đang chỉnh sửa Markdown.
      </div>
    );
  }

  return (
    <div className="as-md-insert-popover border rounded shadow-sm bg-white">
      <div className="as-md-insert-popover-hd small fw-semibold text-secondary px-2 pt-2 pb-1">Chèn liên kết</div>
      <input
        type="search"
        className="form-control form-control-sm mx-2 mb-2"
        placeholder="Tìm theo tiêu đề, key, slug…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Lọc story hoặc tài liệu"
      />
      <div className="btn-group btn-group-sm px-2 mb-2 w-100" role="group">
        <button
          type="button"
          className={`btn btn-outline-secondary flex-grow-1 ${tab === "story" ? "active" : ""}`}
          onClick={() => setTab("story")}
        >
          Story
        </button>
        <button
          type="button"
          className={`btn btn-outline-secondary flex-grow-1 ${tab === "document" ? "active" : ""}`}
          onClick={() => setTab("document")}
        >
          Tài liệu
        </button>
      </div>
      <div className="as-md-insert-list px-2 pb-2">
        {loading ? (
          <div className="small text-secondary py-2 text-center">
            <span className="spinner-border spinner-border-sm me-2" role="status" />
            Đang tải…
          </div>
        ) : err ? (
          <div className="small text-danger py-1">{err}</div>
        ) : tab === "story" ? (
          filteredStories.length === 0 ? (
            <div className="small text-secondary fst-italic py-1">Không có story.</div>
          ) : (
            <ul className="list-unstyled mb-0 small">
              {filteredStories.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    className="btn btn-link btn-sm text-start text-body text-decoration-none p-1 w-100 as-md-insert-row"
                    onClick={() => onPickStory(s)}
                  >
                    <span className="font-monospace text-secondary me-1">{s.story_key || `#${s.id}`}</span>
                    <span className="text-truncate d-inline-block align-bottom" style={{ maxWidth: "100%" }}>
                      {s.title || "Untitled"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : filteredDocs.length === 0 ? (
          <div className="small text-secondary fst-italic py-1">Không có tài liệu.</div>
        ) : (
          <ul className="list-unstyled mb-0 small">
            {filteredDocs.map((d) => (
              <li key={d.id}>
                <button
                  type="button"
                  className="btn btn-link btn-sm text-start text-body text-decoration-none p-1 w-100 as-md-insert-row"
                  onClick={() => onPickDoc(d)}
                >
                  <span className="text-truncate d-inline-block align-bottom" style={{ maxWidth: "55%" }}>
                    {d.title || "Untitled"}
                  </span>
                  <span className="font-monospace text-secondary ms-1 small text-truncate d-inline-block align-bottom">
                    {d.slug ? `· ${d.slug}` : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/**
 * Lệnh toolbar MDEditor: dropdown chèn markdown link story / wiki (chuẩn universal link).
 */
export function createMarkdownInsertCommands(projectId) {
  /**
   * MDEditor chỉ render lệnh có keyCommand; lệnh có children (popover) bắt buộc dùng
   * keyCommand "group" + groupName để barPopup[groupName] mở .w-md-editor-toolbar-child.
   */
  const cmd = {
    name: "insert-agile-link",
    keyCommand: "group",
    groupName: "agile-insert",
    execute: () => {},
    icon: (
      <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden>
        <path
          fill="currentColor"
          d="M8 4a.5.5 0 0 1 .5.5v3h3a.5.5 0 0 1 0 1h-3v3a.5.5 0 0 1-1 0v-3h-3a.5.5 0 0 1 0-1h3v-3A.5.5 0 0 1 8 4z"
        />
      </svg>
    ),
    buttonProps: {
      "aria-label": "Chèn liên kết story hoặc tài liệu",
      title: "Chèn story / tài liệu",
    },
    children: ({ close, execute, textApi }) => (
      <MarkdownInsertPopover close={close} execute={execute} textApi={textApi} projectId={projectId} />
    ),
  };
  return [cmd];
}
