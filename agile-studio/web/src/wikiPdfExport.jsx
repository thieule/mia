import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import {
  AgileMarkdownAnchor,
  AgileMarkdownProjectContext,
  agileMarkdownUrlTransform,
  linkifyAgileStandaloneShortLinks,
} from "./agileMarkdownLink.jsx";
import { MarkdownPreviewPre } from "./markdownMermaidPreview.jsx";
import { ChatMarkdownErrorBoundary, normalizeChatMarkdownSource } from "./markdownWithMentions.jsx";

const PDF_MARKDOWN_COMPONENTS = {
  a: AgileMarkdownAnchor,
  pre: MarkdownPreviewPre,
};

function wikiPdfSafeFileBase(title) {
  let s = String(title || "").trim() || "wiki-document";
  s = s.replace(/[\\/:*?"<>|]+/g, "_").replace(/\s+/g, "_");
  if (s.length > 120) s = s.slice(0, 120);
  return s || "wiki-document";
}

/** html2pdf nhân bản node vào `document.body` — Bootstrap CDN áp CSS oklab lên clone; html2canvas không parse được. */
function sanitizePdfHtml2CanvasClone(clonedDoc, rootEl) {
  const win = clonedDoc.defaultView;
  if (!win || !rootEl || rootEl.nodeType !== 1) return;

  try {
    clonedDoc.querySelectorAll('link[rel="stylesheet"]').forEach((n) => n.remove());
    clonedDoc.querySelectorAll("style").forEach((node) => {
      const t = node.textContent || "";
      if (/(oklab|oklch)/i.test(t)) node.remove();
    });
  } catch {
    /* ignore */
  }

  const canvas = clonedDoc.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const risky = (s) => typeof s === "string" && /(oklab|oklch|lab\(|lch\(|color\()/i.test(s);

  function normalizeCssColor(val) {
    if (val == null) return val;
    const s = String(val).trim();
    if (!s || s === "transparent") return s;
    if (!risky(s)) return s;
    try {
      ctx.fillStyle = "#ffffff";
      ctx.fillStyle = s;
      return ctx.fillStyle;
    } catch {
      return "#222222";
    }
  }

  function scrubDangerousInlineStyle(el) {
    const st = el.getAttribute("style");
    if (!st || !risky(st)) return;
    const kept = st
      .split(";")
      .map((x) => x.trim())
      .filter(Boolean)
      .filter((decl) => !risky(decl));
    if (kept.length) el.setAttribute("style", kept.join("; "));
    else el.removeAttribute("style");
  }

  const camelPaint = [
    "color",
    "backgroundColor",
    "borderTopColor",
    "borderRightColor",
    "borderBottomColor",
    "borderLeftColor",
    "borderColor",
    "outlineColor",
    "textDecorationColor",
    "caretColor",
    "columnRuleColor",
    "fill",
    "stroke",
  ];

  const nodes = [rootEl, ...rootEl.querySelectorAll("*")];
  for (const el of nodes) {
    if (el.nodeType !== 1) continue;
    const tag = el.tagName;
    if (tag === "STYLE" || tag === "SCRIPT") continue;

    scrubDangerousInlineStyle(el);

    let cs;
    try {
      cs = win.getComputedStyle(el);
    } catch {
      continue;
    }

    const inSvg = !!el.closest?.("svg");

    for (const prop of camelPaint) {
      if ((prop === "fill" || prop === "stroke") && !inSvg) continue;
      let raw;
      try {
        raw = cs[prop];
      } catch {
        continue;
      }
      if (!risky(raw)) continue;
      const fixed = normalizeCssColor(raw);
      try {
        el.style[prop] = fixed;
      } catch {
        /* ignore */
      }
    }

    for (const extra of ["boxShadow", "textShadow", "filter", "backgroundImage"]) {
      let raw;
      try {
        raw = cs[extra];
      } catch {
        continue;
      }
      if (!risky(raw)) continue;
      try {
        if (extra === "filter") el.style.filter = "none";
        else if (extra === "backgroundImage") el.style.backgroundImage = "none";
        else el.style[extra] = "none";
      } catch {
        /* ignore */
      }
    }

    if (el.namespaceURI === "http://www.w3.org/2000/svg" || inSvg) {
      for (const attr of ["fill", "stroke", "stop-color"]) {
        const av = el.getAttribute(attr);
        if (av && risky(av)) {
          const fixed = normalizeCssColor(av);
          if (fixed) el.setAttribute(attr, fixed);
        }
      }
    }
  }
}

function waitForMermaidInContainer(container, timeoutMs) {
  return new Promise((resolve) => {
    const start = Date.now();
    const step = () => {
      const charts = container.querySelectorAll(".as-mermaid-chart");
      if (charts.length === 0) {
        resolve();
        return;
      }
      const ready = [...charts].every((el) => el.querySelector("svg"));
      if (ready) {
        resolve();
        return;
      }
      if (Date.now() - start >= timeoutMs) {
        resolve();
        return;
      }
      requestAnimationFrame(step);
    };
    step();
  });
}

function WikiPdfExportBody({ title, markdown, exportedAtLabel }) {
  const processed = linkifyAgileStandaloneShortLinks(normalizeChatMarkdownSource(markdown));
  return (
    <div className="as-wiki-pdf-root">
      <style>
        {`
        .as-wiki-pdf-root { box-sizing: border-box; color: #1a1a1a; background: #fff; }
        .as-wiki-pdf-root * { box-sizing: border-box; }
        .as-wiki-pdf-meta { font-size: 9pt; margin-bottom: 1rem; color: #555; }
        .as-wiki-pdf-root > h1 { font-size: 20pt; font-weight: 700; margin: 0 0 1rem; padding-bottom: 0.35em; border-bottom: 1px solid #ccc; }
        .as-wiki-pdf-md { font-size: 10.5pt; line-height: 1.5; }
        .as-wiki-pdf-md h1 { font-size: 16pt; margin: 1.1em 0 0.4em; }
        .as-wiki-pdf-md h2 { font-size: 14pt; margin: 1em 0 0.35em; }
        .as-wiki-pdf-md h3 { font-size: 12pt; margin: 0.9em 0 0.3em; }
        .as-wiki-pdf-md p { margin: 0.5em 0; }
        .as-wiki-pdf-md ul, .as-wiki-pdf-md ol { margin: 0.5em 0; padding-left: 1.4em; }
        .as-wiki-pdf-md pre { white-space: pre-wrap; word-break: break-word; font-size: 9pt; padding: 0.6em; background: #f5f5f5; border: 1px solid #e0e0e0; border-radius: 4px; }
        .as-wiki-pdf-md code { font-size: 0.9em; background: #f0f0f0; padding: 0.1em 0.25em; border-radius: 3px; }
        .as-wiki-pdf-md table { border-collapse: collapse; width: 100%; margin: 0.75em 0; font-size: 9.5pt; }
        .as-wiki-pdf-md th, .as-wiki-pdf-md td { border: 1px solid #bbb; padding: 0.35em 0.5em; vertical-align: top; }
        .as-wiki-pdf-md blockquote { margin: 0.6em 0; padding-left: 0.85em; border-left: 3px solid #ccc; color: #444; }
        .as-wiki-pdf-md .as-md-internal-link { text-decoration: none; color: #0d47a1; }
        .as-wiki-pdf-md .as-mermaid-chart { max-width: 100%; margin: 0.5em 0; }
        .as-wiki-pdf-md .as-mermaid-chart svg { max-width: 100%; height: auto !important; }
      `}
      </style>
      <div className="as-wiki-pdf-meta">{exportedAtLabel}</div>
      <h1>{title.trim() || "Untitled"}</h1>
      <div className="as-wiki-pdf-md as-md-prose-view">
        <ChatMarkdownErrorBoundary source={processed}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkBreaks]}
            components={PDF_MARKDOWN_COMPONENTS}
            urlTransform={agileMarkdownUrlTransform}
          >
            {processed}
          </ReactMarkdown>
        </ChatMarkdownErrorBoundary>
      </div>
    </div>
  );
}

/**
 * html2pdf **clone** nội dung vào `document.body` chính → Bootstrap CDN vẫn áp CSS (oklab).
 * Iframe chỉ giữ bản gốc sạch; bắt buộc `html2canvas.onclone` để ép màu về rgb/#hex.
 */
export async function exportWikiDocumentToPdf({ title, body, projectId }) {
  const iframe = document.createElement("iframe");
  iframe.setAttribute("data-as-wiki-pdf-frame", "1");
  iframe.setAttribute("title", "Wiki PDF export");
  iframe.style.cssText =
    "position:fixed;left:-12000px;top:0;width:794px;min-height:400px;border:0;visibility:visible;opacity:1;";
  iframe.setAttribute("sandbox", "allow-same-origin");
  document.body.appendChild(iframe);

  const idoc = iframe.contentDocument;
  if (!idoc) {
    iframe.remove();
    throw new Error("PDF: cannot access iframe document");
  }
  idoc.open();
  idoc.write(
    "<!DOCTYPE html><html><head><meta charset=\"utf-8\"/><style>html,body{margin:0;background:#fff;}</style></head><body><div id=\"as-wiki-pdf-mount\"></div></body></html>",
  );
  idoc.close();

  const mount = idoc.getElementById("as-wiki-pdf-mount");
  if (!mount) {
    iframe.remove();
    throw new Error("PDF: mount node missing");
  }
  mount.style.cssText = "width:100%;padding:32px 40px;background:#fff;box-sizing:border-box;";

  const exportedAtLabel = `Exported: ${new Date().toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  })}`;

  const root = createRoot(mount);
  root.render(
    <MemoryRouter initialEntries={["/"]}>
      <AgileMarkdownProjectContext.Provider value={projectId ?? null}>
        <WikiPdfExportBody title={title || ""} markdown={body || ""} exportedAtLabel={exportedAtLabel} />
      </AgileMarkdownProjectContext.Provider>
    </MemoryRouter>,
  );

  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  await waitForMermaidInContainer(mount, 12000);
  await new Promise((r) => setTimeout(r, 200));

  const target = mount.querySelector(".as-wiki-pdf-root");
  if (!target) {
    root.unmount();
    iframe.remove();
    throw new Error("PDF: failed to render content");
  }

  const html2pdf = (await import("html2pdf.js")).default;
  const base = wikiPdfSafeFileBase(title);
  await html2pdf()
    .set({
      margin: [12, 12, 14, 12],
      filename: `${base}.pdf`,
      image: { type: "jpeg", quality: 0.93 },
      html2canvas: {
        scale: 2,
        useCORS: true,
        logging: false,
        letterRendering: true,
        backgroundColor: "#ffffff",
        onclone(clonedDoc, element) {
          sanitizePdfHtml2CanvasClone(clonedDoc, element);
        },
      },
      jsPDF: { unit: "mm", format: "a4", orientation: "portrait" },
      pagebreak: { mode: ["css", "legacy"], avoid: [".as-mermaid-chart", "img"] },
    })
    .from(target)
    .save();

  root.unmount();
  iframe.remove();
}
