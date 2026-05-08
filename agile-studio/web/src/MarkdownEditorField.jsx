import { useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import MDEditor, { getCommands, getExtraCommands } from "@uiw/react-md-editor";
import "@uiw/react-md-editor/markdown-editor.css";
import "@uiw/react-markdown-preview/markdown.css";
import {
  AgileMarkdownAnchor,
  AgileMarkdownProjectContext,
  agileMarkdownUrlTransform,
} from "./agileMarkdownLink.jsx";
import { createMarkdownInsertCommands } from "./markdownInsertToolbar.jsx";
import { markdownMermaidPreviewComponents } from "./markdownMermaidPreview.jsx";

export default function MarkdownEditorField({
  value,
  onChange,
  height = 200,
  placeholder,
  className = "",
  textareaProps,
  /** "edit" | "live" | "preview" — preview = full-page render (review); live = split */
  previewMode = "edit",
  previewOptions,
  /** Show Markdown help toggle above the editor */
  markdownHelp = true,
  /** Override project for story/doc insert toolbar (defaults to AgileMarkdownProjectContext) */
  projectId: projectIdProp,
  /** MDEditor toolbar: story/doc insert buttons — enable only where needed (off by default, e.g. Settings) */
  insertToolbar = false,
  /** When set, focus textarea and select `{ start, end }` (e.g. wiki comment navigation). */
  selectionFocus = null,
  onSelectionFocusDone,
}) {
  const coreRef = useRef(null);
  const ctxProjectId = useContext(AgileMarkdownProjectContext);
  const effectiveProjectId = projectIdProp ?? ctxProjectId ?? null;
  const helpPanelId = useId();
  const [helpOpen, setHelpOpen] = useState(false);
  const mergedPreviewOptions = useMemo(
    () => ({
      ...previewOptions,
      urlTransform: previewOptions?.urlTransform ?? agileMarkdownUrlTransform,
      components: {
        a: AgileMarkdownAnchor,
        ...markdownMermaidPreviewComponents,
        ...(previewOptions?.components || {}),
      },
    }),
    [previewOptions]
  );

  /**
   * @uiw/react-md-editor renders `commands` and `extraCommands` as two separate toolbar <ul>s;
   * the container uses `justify-content: space-between` → extraCommands align to the right.
   * Merge Story/Wiki into `commands` after Help so they stay grouped with the primary icons.
   */
  const toolbarCommandProps = useMemo(() => {
    if (!insertToolbar || effectiveProjectId == null || previewMode === "preview") {
      return {};
    }
    const base = getCommands();
    const insertCmds = createMarkdownInsertCommands(Number(effectiveProjectId));
    const helpIdx = base.findIndex((c) => c?.name === "help");
    const merged =
      helpIdx >= 0
        ? [...base.slice(0, helpIdx + 1), ...insertCmds, ...base.slice(helpIdx + 1)]
        : [...base, ...insertCmds];
    return { commands: merged, extraCommands: getExtraCommands() };
  }, [insertToolbar, effectiveProjectId, previewMode]);

  useEffect(() => {
    if (!selectionFocus || typeof selectionFocus.start !== "number" || typeof selectionFocus.end !== "number") {
      return;
    }
    const ta = coreRef.current?.querySelector?.("textarea");
    if (!ta || typeof ta.setSelectionRange !== "function") {
      return;
    }
    const len = ta.value?.length ?? 0;
    const a = Math.max(0, Math.min(selectionFocus.start, len));
    const b = Math.max(a, Math.min(selectionFocus.end, len));
    ta.focus({ preventScroll: false });
    requestAnimationFrame(() => {
      try {
        ta.setSelectionRange(a, b);
        const blo = ta.closest?.(".as-md-editor-core") ?? ta.parentElement ?? ta;
        blo?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
      } catch {
        /* ignore */
      }
      onSelectionFocusDone?.();
    });
  }, [selectionFocus, onSelectionFocusDone]);

  const mergedTextareaProps = useMemo(() => {
    const base = textareaProps || {};
    return { ...base };
  }, [textareaProps]);

  return (
    <div className={`as-md-editor ${className}`.trim()}>
      {markdownHelp ? (
        <>
          <div className="as-md-editor-help-bar">
            <button
              type="button"
              className="btn btn-sm btn-outline-secondary as-md-editor-help-btn"
              aria-expanded={helpOpen}
              aria-controls={helpPanelId}
              title="Hướng dẫn Markdown và liên kết"
              onClick={() => setHelpOpen((v) => !v)}
            >
              <i className="bi bi-question-circle" aria-hidden />
              <span className="ms-1 d-none d-sm-inline">Markdown</span>
            </button>
          </div>
          {helpOpen ? (
            <div id={helpPanelId} className="as-md-editor-help-panel small" role="region" aria-label="Markdown help">
              <ul className="mb-0 ps-3">
                <li>
                  <strong>Bold</strong>, <em>italic</em>, lists, headings — standard Markdown / GFM.
                </li>
                <li>
                  Links: <code>[label](https://…)</code> · in this app:{" "}
                  <code>[story](/p/PROJECT_ID/story/STORY_ID)</code>, <code>[doc](/p/PROJECT_ID/wiki/slug)</code>
                </li>
                <li>
                  Shortcuts (with a project open): <code>story:123</code>, <code>wiki:slug</code>, or{" "}
                  <code>agile:story/123</code>, <code>agile:wiki/slug</code>
                </li>
                <li>
                  Fenced code blocks (triple backticks + language); diagrams: fenced block with{" "}
                  <code>mermaid</code>.
                </li>
              </ul>
            </div>
          ) : null}
        </>
      ) : null}
      <div ref={coreRef} data-color-mode="light" className="as-md-editor-core">
        <MDEditor
          value={value || ""}
          onChange={(next) => onChange?.(next ?? "")}
          height={height}
          preview={previewMode}
          previewOptions={mergedPreviewOptions}
          visibleDragbar={previewMode === "live"}
          {...toolbarCommandProps}
          textareaProps={{
            placeholder,
            ...mergedTextareaProps,
          }}
        />
      </div>
    </div>
  );
}
