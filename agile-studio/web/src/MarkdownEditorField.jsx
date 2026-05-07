import { useContext, useId, useMemo, useState } from "react";
import MDEditor, { commands } from "@uiw/react-md-editor";
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
  /** Hiện nút icon hướng dẫn Markdown phía trên editor */
  markdownHelp = true,
  /** Ghi đè project cho toolbar chèn story/doc (mặc định lấy từ AgileMarkdownProjectContext) */
  projectId: projectIdProp,
  /** Toolbar MDEditor: chèn story/doc — chỉ bật nơi cần (mặc định tắt, vd. Settings không dùng) */
  insertToolbar = false,
}) {
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

  const insertCommands = useMemo(() => {
    if (!insertToolbar || effectiveProjectId == null || previewMode === "preview") return [];
    return createMarkdownInsertCommands(Number(effectiveProjectId));
  }, [insertToolbar, effectiveProjectId, previewMode]);

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
            <div id={helpPanelId} className="as-md-editor-help-panel small" role="region" aria-label="Hướng dẫn Markdown">
              <ul className="mb-0 ps-3">
                <li>
                  <strong>In đậm</strong>, <em>nghiêng</em>, danh sách, tiêu đề — chuẩn Markdown / GFM.
                </li>
                <li>
                  Liên kết: <code>[nhãn](https://…)</code> · trong app:{" "}
                  <code>[story](/p/PROJECT_ID/story/STORY_ID)</code>, <code>[doc](/p/PROJECT_ID/wiki/slug)</code>
                </li>
                <li>
                  Rút gọn (khi đã mở project): <code>story:123</code>, <code>wiki:ten-slug</code>, hoặc{" "}
                  <code>agile:story/123</code>, <code>agile:wiki/ten-slug</code>
                </li>
                <li>
                  Khối code fenced (ba dấu nháy ngược + tên ngôn ngữ); biểu đồ: fenced block với{" "}
                  <code>mermaid</code>.
                </li>
              </ul>
            </div>
          ) : null}
        </>
      ) : null}
      <div data-color-mode="light" className="as-md-editor-core">
        <MDEditor
          value={value || ""}
          onChange={(next) => onChange?.(next ?? "")}
          height={height}
          preview={previewMode}
          previewOptions={mergedPreviewOptions}
          visibleDragbar={previewMode === "live"}
          extraCommands={insertCommands.length > 0 ? [...insertCommands, commands.fullscreen] : undefined}
          textareaProps={{
            placeholder,
            ...textareaProps,
          }}
        />
      </div>
    </div>
  );
}
