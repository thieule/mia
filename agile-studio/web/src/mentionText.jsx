/**
 * Shared mention helpers (wiki feedback; can extend beyond App.jsx).
 * Matches backend tokens @[A-Za-z0-9._-]+ against mentionKey(display_name) allow-list.
 */
export function mentionKeyFromName(name) {
  return String(name || "")
    .trim()
    .replace(/\s+/g, "")
    .toLowerCase();
}

const TRAILING_MENTION_RE = /(?:^|\s)@([^\s@]*)$/;

/**
 * Thay token @… chưa hoàn chỉnh ở cuối chuỗi bằng `@mentionKey(displayName) `.
 * Trả về nội dung mới và vị trí caret (sau dấu cách).
 */
export function replaceTrailingMention(prev, displayName) {
  const prevStr = prev == null ? "" : String(prev);
  const match = prevStr.match(TRAILING_MENTION_RE);
  if (!match) return { next: prevStr, caret: prevStr.length };
  const mentionToken = `@${mentionKeyFromName(displayName)}`;
  const fullMatch = match[0];
  const replacedTail = fullMatch.replace(/@([^\s@]*)$/, `${mentionToken} `);
  const start = prevStr.length - fullMatch.length;
  const next = prevStr.slice(0, start) + replacedTail;
  const caret = start + replacedTail.length;
  return { next, caret };
}

/** Plain text with optional highlight class for project-matched @mentions (Map mentionKey → optional display label). */
export function renderPlainWithMentions(text, mentionIndex) {
  const idxMap = mentionIndex instanceof Map ? mentionIndex : new Map();
  const s = text == null ? "" : String(text);
  const parts = s.split(/(@[A-Za-z0-9._-]+)/g);
  return parts.map((p, i) => {
    if (!p.startsWith("@")) {
      if (!p) return null;
      return <span key={i}>{p}</span>;
    }
    const key = p.slice(1).toLowerCase();
    const matched = idxMap.has(key);
    return (
      <span key={i} className={matched ? "as-chat-mention" : ""}>
        {p}
      </span>
    );
  });
}
