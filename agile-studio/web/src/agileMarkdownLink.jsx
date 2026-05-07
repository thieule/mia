import { createContext, useContext } from "react";
import { defaultUrlTransform } from "react-markdown";
import { Link } from "react-router-dom";

/** Current project id for short links (`agile:wiki/…`, `wiki:…`, `story:…`). */
export const AgileMarkdownProjectContext = createContext(null);

/**
 * react-markdown v10 `defaultUrlTransform` chỉ giữ http(s), mailto, … — `story:` / `wiki:` / `agile:`
 * bị thành href rỗng → không click được. Giữ các scheme nội bộ rồi fallback an toàn.
 */
export function agileMarkdownUrlTransform(url) {
  const s = String(url ?? "").trim();
  const protoMatch = /^([a-z][a-z0-9+.-]*):/i.exec(s);
  if (protoMatch) {
    const p = protoMatch[1].toLowerCase();
    if (p === "story" || p === "wiki" || p === "agile") return s;
  }
  return defaultUrlTransform(url);
}

/**
 * Short link đứng một mình trong prose (không nằm trong đích markdown `(…)` sau `[…](`)
 * thành `[token](token)` để react-markdown tạo thẻ `<a>` + AgileMarkdownAnchor (chip, điều hướng).
 * Bỏ qua fenced ``` … ``` và inline `…`.
 */
export function linkifyAgileStandaloneShortLinks(raw) {
  const s = String(raw ?? "");
  const chunks = s.split(/(```[\s\S]*?```)/g);
  return chunks
    .map((chunk, ci) => {
      if (ci % 2 === 1) return chunk;
      const inlineParts = chunk.split(/(`[^`]*`)/g);
      return inlineParts
        .map((seg, si) => {
          if (si % 2 === 1) return seg;
          let t = seg;
          const rules = [
            /(^|[\s>])(agile:(?:\/\/)?wiki\/[a-zA-Z0-9_.-]+(?:\/[a-zA-Z0-9_.-]+)*)\b/g,
            /(^|[\s>])(agile:(?:\/\/)?story\/\d+)\b/g,
            /(^|[\s>])(story:\d+)\b/g,
            /(^|[\s>])(wiki:[a-zA-Z0-9_.-]+)\b/g,
          ];
          for (const re of rules) {
            t = t.replace(re, (_m, pre, tok) => `${pre}[${tok}](${tok})`);
          }
          return t;
        })
        .join("");
    })
    .join("");
}

/**
 * Resolve markdown link href to an in-app route.
 * Supported:
 * - `/p/:projectId/story/:storyId` — SPA navigation
 * - `/p/:projectId/wiki/:slug`
 * - `agile:story/123` / `agile://story/123` — story in current project
 * - `agile:wiki/my-slug` / `agile://wiki/my-slug`
 * - `story:123` — shorthand (current project)
 * - `wiki:my-slug` — shorthand (current project)
 */
export function resolveAgileMarkdownHref(href, defaultProjectId) {
  if (href == null) return null;
  const raw = String(href).trim();
  if (!raw) return null;

  let m = /^\/p\/(\d+)\/story\/(\d+)(?:\/|[?#]|$)/i.exec(raw);
  if (m) {
    return { to: `/p/${m[1]}/story/${m[2]}`, kind: "story-path" };
  }

  m = /^\/p\/(\d+)\/wiki\/([^?#]+?)(?:\/|[?#]|$)/i.exec(raw);
  if (m) {
    const slug = decodeURIComponent(m[2].replace(/\/+$/, ""));
    if (slug) return { to: `/p/${m[1]}/wiki/${encodeURIComponent(slug)}`, kind: "wiki-path" };
  }

  m = /^agile:(?:\/\/)?story\/(\d+)(?:\/|[?#]|$)/i.exec(raw);
  if (m) {
    const pid = defaultProjectId;
    if (pid == null || Number.isNaN(Number(pid))) return { kind: "needs-project", raw };
    return { to: `/p/${pid}/story/${m[1]}`, kind: "agile-story" };
  }

  m = /^agile:(?:\/\/)?wiki\/([^?#]+?)(?:\/|[?#]|$)/i.exec(raw);
  if (m) {
    const pid = defaultProjectId;
    if (pid == null || Number.isNaN(Number(pid))) return { kind: "needs-project", raw };
    const slug = decodeURIComponent(m[1].replace(/\/+$/, ""));
    if (!slug) return null;
    return { to: `/p/${pid}/wiki/${encodeURIComponent(slug)}`, kind: "agile-wiki" };
  }

  m = /^story:(\d+)$/i.exec(raw);
  if (m) {
    const pid = defaultProjectId;
    if (pid == null || Number.isNaN(Number(pid))) return { kind: "needs-project", raw };
    return { to: `/p/${pid}/story/${m[1]}`, kind: "story-shorthand" };
  }

  m = /^wiki:([^?#]+)$/i.exec(raw);
  if (m) {
    const pid = defaultProjectId;
    if (pid == null || Number.isNaN(Number(pid))) return { kind: "needs-project", raw };
    const slug = decodeURIComponent(String(m[1]).trim().replace(/\/+$/, ""));
    if (!slug) return null;
    return { to: `/p/${pid}/wiki/${encodeURIComponent(slug)}`, kind: "wiki-shorthand" };
  }

  return null;
}

/** story | wiki — để style + icon khác nhau */
export function internalMarkdownLinkVariant(kind) {
  if (!kind || typeof kind !== "string") return "story";
  if (kind.includes("wiki")) return "wiki";
  if (kind.includes("story")) return "story";
  return "story";
}

/** react-markdown / MDEditor preview: in-app links use Router; external keep target blank. */
export function AgileMarkdownAnchor({ node: _node, href, children, className, title: linkTitle, ...rest }) {
  const defaultProjectId = useContext(AgileMarkdownProjectContext);
  const resolved = resolveAgileMarkdownHref(href, defaultProjectId);
  const mergeCls = (...parts) => parts.filter(Boolean).join(" ");

  if (resolved?.to) {
    const variant = internalMarkdownLinkVariant(resolved.kind);
    const iconClass = variant === "wiki" ? "bi-file-earmark-text" : "bi-kanban";
    const variantClass = variant === "wiki" ? "as-md-internal-link--wiki" : "as-md-internal-link--story";
    const defaultTitle = variant === "wiki" ? "Mở tài liệu wiki" : "Mở story";
    return (
      <Link
        to={resolved.to}
        className={mergeCls("as-md-internal-link", variantClass, className)}
        {...rest}
        title={linkTitle ?? defaultTitle}
      >
        <span className="as-md-internal-link-icon" aria-hidden>
          <i className={`bi ${iconClass}`} />
        </span>
        <span className="as-md-internal-link-label">{children}</span>
      </Link>
    );
  }

  if (resolved?.kind === "needs-project") {
    return (
      <span
        className={mergeCls("as-md-link-needs-project text-secondary", className)}
        title="Short link needs an open project. Use a full URL like /p/PROJECT_ID/story/… or open a project first."
      >
        {children}
      </span>
    );
  }

  const r = String(href || "").trim();
  if (!r) {
    return (
      <span className={className} {...rest}>
        {children}
      </span>
    );
  }

  if (r.startsWith("#") || r.startsWith("mailto:") || r.startsWith("tel:")) {
    return (
      <a href={r} className={className} {...rest}>
        {children}
      </a>
    );
  }

  if (/^https?:\/\//i.test(r) || r.startsWith("//")) {
    return (
      <a href={r} className={className} {...rest} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  }

  return (
    <a href={r} className={className} {...rest} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}
