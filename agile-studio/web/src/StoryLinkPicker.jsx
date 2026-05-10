import { useMemo, useState } from "react";

function storyLabel(s) {
  const key = s.story_key ? `${s.story_key}` : "";
  const title = s.title || `Story ${s.id}`;
  return key ? `${key} · ${title}` : title;
}

/** Search stories by key/title/id and add as chips (no full list select). */
export default function StoryLinkPicker({
  stories = [],
  value,
  onChange,
  disabled = false,
  id = "as-story-link-search",
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const linkedSet = useMemo(() => new Set(value.map(Number)), [value]);

  const linkedStories = useMemo(() => {
    const map = new Map((stories || []).map((s) => [Number(s.id), s]));
    return value.map((sid) => {
      const n = Number(sid);
      const s = map.get(n);
      if (s) return s;
      return { id: n, story_key: null, title: `Story #${n} (not in list)` };
    });
  }, [stories, value]);

  const suggestions = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const digitOnly = /^\d+$/.test(q.trim());
    return (stories || [])
      .filter((s) => {
        const sid = Number(s.id);
        if (linkedSet.has(sid)) return false;
        if (digitOnly && String(sid) === q.trim()) return true;
        const key = (s.story_key || "").toLowerCase();
        const title = (s.title || "").toLowerCase();
        return key.includes(q) || title.includes(q);
      })
      .slice(0, 12);
  }, [stories, query, linkedSet]);

  const addStory = (s) => {
    const sid = Number(s.id);
    if (!Number.isFinite(sid) || linkedSet.has(sid)) return;
    onChange([...value, sid]);
    setQuery("");
    setOpen(false);
  };

  const removeStory = (sid) => {
    onChange(value.filter((x) => Number(x) !== Number(sid)));
  };

  return (
    <div className="as-story-link-picker">
      <label className="as-ticket-label" htmlFor={id}>
        Linked stories
      </label>
      <p className="as-ticket-sublabel mb-2">Search by story key, title, or ID — add one at a time.</p>

      <div className="d-flex flex-wrap gap-2 mb-3">
        {linkedStories.length === 0 ? (
          <span className="small text-secondary fst-italic">None linked · ticket stays at project level.</span>
        ) : (
          linkedStories.map((s) => (
            <span key={s.id} className="badge rounded-pill bg-light text-dark border d-inline-flex align-items-center gap-2 py-2 px-3">
              <span className="text-truncate" style={{ maxWidth: 280 }} title={storyLabel(s)}>
                <span className="font-monospace small text-secondary me-1">{s.story_key || `#${s.id}`}</span>
                <span>{s.title || `Story ${s.id}`}</span>
              </span>
              {!disabled ? (
                <button
                  type="button"
                  className="btn btn-sm btn-link p-0 lh-1 text-danger"
                  aria-label={`Remove ${s.story_key || s.id}`}
                  onClick={() => removeStory(s.id)}
                >
                  <i className="bi bi-x-lg" />
                </button>
              ) : null}
            </span>
          ))
        )}
      </div>

      {!disabled ? (
        <div className="position-relative">
          <div className="input-group">
            <span className="input-group-text bg-white border-end-0">
              <i className="bi bi-search text-secondary" aria-hidden />
            </span>
            <input
              id={id}
              type="search"
              className="form-control border-start-0"
              placeholder="Type to search stories…"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setOpen(true);
              }}
              onFocus={() => setOpen(true)}
              onBlur={() => window.setTimeout(() => setOpen(false), 180)}
              autoComplete="off"
              aria-autocomplete="list"
              aria-expanded={open && suggestions.length > 0}
            />
          </div>
          {open && query.trim() && suggestions.length > 0 ? (
            <ul
              className="list-group position-absolute w-100 shadow-sm mt-1 as-story-link-picker-dropdown"
              role="listbox"
              style={{ zIndex: 20, maxHeight: 280, overflowY: "auto" }}
            >
              {suggestions.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    className="list-group-item list-group-item-action py-2 px-3 text-start border-0 rounded-0"
                    role="option"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => addStory(s)}
                  >
                    <span className="font-monospace small text-secondary">{s.story_key || `#${s.id}`}</span>
                    <span className="d-block small">{s.title || `Story ${s.id}`}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : open && query.trim() ? (
            <div className="small text-secondary mt-2 px-1">No matching stories.</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
