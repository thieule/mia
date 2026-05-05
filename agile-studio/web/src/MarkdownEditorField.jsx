import MDEditor from "@uiw/react-md-editor";
import "@uiw/react-md-editor/markdown-editor.css";
import "@uiw/react-markdown-preview/markdown.css";

export default function MarkdownEditorField({
  value,
  onChange,
  height = 200,
  placeholder,
  className = "",
  textareaProps,
  /** "edit" | "live" | "preview" — live = edit + preview side by side */
  previewMode = "edit",
  previewOptions,
}) {
  return (
    <div data-color-mode="light" className={`as-md-editor ${className}`.trim()}>
      <MDEditor
        value={value || ""}
        onChange={(next) => onChange?.(next ?? "")}
        height={height}
        preview={previewMode}
        previewOptions={previewOptions}
        visibleDragbar={previewMode === "live"}
        textareaProps={{
          placeholder,
          ...textareaProps,
        }}
      />
    </div>
  );
}
