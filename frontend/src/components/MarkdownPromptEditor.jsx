import Placeholder from "@tiptap/extension-placeholder";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { marked } from "marked";
import { useEffect, useId, useReducer, useRef, useState } from "react";
import TurndownService from "turndown";

const turndown = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
});

const DEFAULT_RAG_TOP = 5;
const DEFAULT_CONV_HISTORY_LIMIT = 20;

/** Runtime-resolved placeholders — same `{{ctx …}}` style as RAG inserts. */
const BASIC_CONTEXT_PRESETS = [
  { kind: "datetime", label: "Date & time", hint: "Current timestamp when the prompt runs" },
  { kind: "timezone", label: "Timezone", hint: "User or server timezone for formatting" },
  { kind: "locale", label: "Locale", hint: "Regional settings (e.g. date/number formats)" },
  { kind: "language", label: "Language", hint: "UI or response language preference" },
  { kind: "session_id", label: "Session id", hint: "Identifier for the chat session" },
  {
    kind: "user_context",
    label: "User context",
    hint: "User identity and profile (id, name, roles, etc.) — filled at runtime",
  },
  { kind: "user_message", label: "Last user message", hint: "Most recent user input in the turn" },
  {
    kind: "conversation_history",
    label: "Conversation history",
    hint: "Most recent N messages in the session (set N when inserting)",
  },
  {
    kind: "conversation_summary",
    label: "Conversation summary",
    hint: "Rolling summary of a long thread",
  },
  { kind: "last_tool_results", label: "Last tool results", hint: "Outputs from the latest tool/agent steps" },
  { kind: "attachments", label: "Attachments", hint: "Files or documents attached to this session" },
];

function insertPlainAtCursor(editor, text) {
  if (!editor) return;
  editor.commands.focus();
  const { from } = editor.state.selection;
  editor.view.dispatch(editor.state.tr.insertText(text, from));
}

function EditorToolbar({ editor, ragDomains, onOpenRagPicker, onOpenBasicContext, showPromptInserts = true, disabled = false }) {
  if (!editor) return null;
  const showRag = showPromptInserts && Array.isArray(ragDomains) && ragDomains.length > 0;
  const btn = (active, onClick, label, iconClass) => (
    <button
      type="button"
      className={`btn btn-sm ${active ? "btn-primary" : "btn-outline-secondary"}`}
      onClick={onClick}
      aria-label={label}
      title={label}
    >
      <i className={`bi ${iconClass}`} aria-hidden={true} />
    </button>
  );

  return (
    <div
      className={`tiptap-toolbar d-flex flex-wrap align-items-center gap-1 p-2${disabled ? " opacity-50 pe-none user-select-none" : ""}`}
      aria-disabled={disabled || undefined}
    >
      {btn(editor.isActive("bold"), () => editor.chain().focus().toggleBold().run(), "Bold", "bi-type-bold")}
      {btn(editor.isActive("italic"), () => editor.chain().focus().toggleItalic().run(), "Italic", "bi-type-italic")}
      {btn(editor.isActive("strike"), () => editor.chain().focus().toggleStrike().run(), "Strikethrough", "bi-strikethrough")}
      {btn(editor.isActive("code"), () => editor.chain().focus().toggleCode().run(), "Inline code", "bi-code")}
      <span className="vr mx-1 align-self-stretch" />
      <button
        type="button"
        className={`btn btn-sm ${editor.isActive("heading", { level: 2 }) ? "btn-primary" : "btn-outline-secondary"}`}
        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
        title="Heading 2"
      >
        H2
      </button>
      <button
        type="button"
        className={`btn btn-sm ${editor.isActive("heading", { level: 3 }) ? "btn-primary" : "btn-outline-secondary"}`}
        onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
        title="Heading 3"
      >
        H3
      </button>
      <span className="vr mx-1 align-self-stretch" />
      {btn(
        editor.isActive("bulletList"),
        () => editor.chain().focus().toggleBulletList().run(),
        "Bullet list",
        "bi-list-ul"
      )}
      {btn(
        editor.isActive("orderedList"),
        () => editor.chain().focus().toggleOrderedList().run(),
        "Numbered list",
        "bi-list-ol"
      )}
      {btn(
        editor.isActive("blockquote"),
        () => editor.chain().focus().toggleBlockquote().run(),
        "Quote",
        "bi-quote"
      )}
      {btn(
        editor.isActive("codeBlock"),
        () => editor.chain().focus().toggleCodeBlock().run(),
        "Code block",
        "bi-file-earmark-code"
      )}
      {showRag && (
        <>
          <span className="vr mx-1 align-self-stretch" />
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary"
            onClick={onOpenRagPicker}
            title="Insert RAG data domain"
            aria-label="Insert RAG data domain"
          >
            <i className="bi bi-database-add" aria-hidden={true} />
          </button>
        </>
      )}
      {showPromptInserts && (
        <>
          <span className="vr mx-1 align-self-stretch" />
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary"
            onClick={onOpenBasicContext}
            title="Insert basic context (time, history, …)"
            aria-label="Insert basic context"
          >
            <i className="bi bi-clock-history" aria-hidden={true} />
          </button>
        </>
      )}
      <span className="vr mx-1 align-self-stretch" />
      <button
        type="button"
        className="btn btn-sm btn-outline-secondary"
        disabled={!editor.can().undo()}
        onClick={() => editor.chain().focus().undo().run()}
        title="Undo"
      >
        <i className="bi bi-arrow-counterclockwise" aria-hidden={true} />
      </button>
      <button
        type="button"
        className="btn btn-sm btn-outline-secondary"
        disabled={!editor.can().redo()}
        onClick={() => editor.chain().focus().redo().run()}
        title="Redo"
      >
        <i className="bi bi-arrow-clockwise" aria-hidden={true} />
      </button>
    </div>
  );
}

/**
 * WYSIWYG rich-text editor; value/onChange use Markdown (HTML ↔ MD via marked + turndown).
 * @param {Array<{ id: number, name: string }>} [ragDomains] — when set, toolbar shows RAG insert (Main Prompt).
 * @param {boolean} [showPromptInserts=true] — when false, hides RAG + basic-context insert (e.g. domain articles).
 * @param {boolean} [readOnly=false] — disable editing (e.g. while saving).
 */
export default function MarkdownPromptEditor({
  value,
  onChange,
  height = 240,
  placeholder,
  ragDomains,
  showPromptInserts = true,
  readOnly = false,
}) {
  /** Must not init to `value`, or first useEffect skips setContent while TipTap still shows empty default. */
  const lastEmitted = useRef(null);
  const [, bumpToolbar] = useReducer((n) => n + 1, 0);
  const [ragModalOpen, setRagModalOpen] = useState(false);
  const [ragPickId, setRagPickId] = useState("");
  const [ragTop, setRagTop] = useState(DEFAULT_RAG_TOP);
  const ragModalTitleId = useId();
  const ragSelectId = useId();
  const ragTopInputId = useId();
  const [basicCtxModalOpen, setBasicCtxModalOpen] = useState(false);
  const [basicCtxKind, setBasicCtxKind] = useState(BASIC_CONTEXT_PRESETS[0].kind);
  const [basicCtxHistoryLimit, setBasicCtxHistoryLimit] = useState(DEFAULT_CONV_HISTORY_LIMIT);
  const basicCtxModalTitleId = useId();
  const basicCtxSelectId = useId();
  const basicCtxHistoryLimitId = useId();

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3] },
      }),
      Placeholder.configure({
        placeholder: placeholder ?? "",
      }),
    ],
    content: "<p></p>",
    editorProps: {
      attributes: {
        class: "tiptap-prose",
        // Inline so padding wins over any TipTap/ProseMirror defaults (DOM may omit .tiptap wrapper).
        style:
          "min-height: var(--editor-area-min-height, 240px); padding: 16px 22px 22px; box-sizing: border-box;",
      },
    },
    editable: !readOnly,
    onUpdate: ({ editor: ed }) => {
      const md = turndown.turndown(ed.getHTML()).trim();
      lastEmitted.current = md;
      onChange(md);
    },
  });

  useEffect(() => {
    if (!editor) return;
    editor.setEditable(!readOnly);
  }, [editor, readOnly]);

  useEffect(() => {
    if (!editor) return;
    const v = value ?? "";
    if (v === lastEmitted.current) return;
    const html = v.trim() ? String(marked.parse(v)) : "<p></p>";
    editor.commands.setContent(html, false);
    lastEmitted.current = v;
  }, [value, editor]);

  useEffect(() => {
    if (!editor) return;
    const refresh = () => bumpToolbar();
    editor.on("transaction", refresh);
    editor.on("selectionUpdate", refresh);
    return () => {
      editor.off("transaction", refresh);
      editor.off("selectionUpdate", refresh);
    };
  }, [editor]);

  useEffect(() => {
    if (ragModalOpen && Array.isArray(ragDomains) && ragDomains.length > 0) {
      setRagPickId(String(ragDomains[0].id));
      setRagTop(DEFAULT_RAG_TOP);
    }
  }, [ragModalOpen, ragDomains]);

  useEffect(() => {
    if (basicCtxModalOpen && BASIC_CONTEXT_PRESETS.length > 0) {
      setBasicCtxKind(BASIC_CONTEXT_PRESETS[0].kind);
      setBasicCtxHistoryLimit(DEFAULT_CONV_HISTORY_LIMIT);
    }
  }, [basicCtxModalOpen]);

  function handleInsertRag() {
    if (!editor) return;
    const id = Number(ragPickId);
    const top = Math.min(100, Math.max(1, Math.floor(Number(ragTop))));
    if (!Number.isFinite(id)) return;
    if (!Number.isFinite(top)) return;
    const token = `{{rag data-id="${id}" data-top="${top}"}}`;
    insertPlainAtCursor(editor, token);
    setRagModalOpen(false);
  }

  function handleInsertBasicContext() {
    if (!editor) return;
    const kind = String(basicCtxKind || "").trim();
    if (!kind) return;
    const limit = Math.min(500, Math.max(1, Math.floor(Number(basicCtxHistoryLimit))));
    const token =
      kind === "conversation_history"
        ? `{{ctx data-kind="conversation_history" data-limit="${Number.isFinite(limit) ? limit : DEFAULT_CONV_HISTORY_LIMIT}"}}`
        : `{{ctx data-kind="${kind}"}}`;
    insertPlainAtCursor(editor, token);
    setBasicCtxModalOpen(false);
  }

  const minH = typeof height === "number" ? `${height}px` : height;
  const bodyStyle = {
    // Drives fixed editor viewport + scroll (see .tiptap-editor-body in styles.css).
    "--editor-area-min-height": minH,
  };

  return (
    <div className="markdown-prompt-editor-wrap tiptap-editor-shell" data-color-mode="light">
      <EditorToolbar
        editor={editor}
        ragDomains={ragDomains}
        onOpenRagPicker={() => setRagModalOpen(true)}
        onOpenBasicContext={() => setBasicCtxModalOpen(true)}
        showPromptInserts={showPromptInserts}
        disabled={readOnly}
      />
      <div className="tiptap-editor-body" style={bodyStyle}>
        <EditorContent editor={editor} />
      </div>
      {showPromptInserts && ragModalOpen && Array.isArray(ragDomains) && ragDomains.length > 0 && (
        <div
          className="markdown-prompt-rag-modal modal fade show d-block"
          tabIndex={-1}
          role="dialog"
          aria-modal="true"
          aria-labelledby={ragModalTitleId}
          style={{ backgroundColor: "rgba(15, 23, 42, 0.45)" }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setRagModalOpen(false);
          }}
        >
          <div className="modal-dialog modal-dialog-centered" onMouseDown={(e) => e.stopPropagation()}>
            <div className="modal-content">
              <div className="modal-header">
                <h5 className="modal-title" id={ragModalTitleId}>
                  Insert RAG data domain
                </h5>
                <button
                  type="button"
                  className="btn-close"
                  aria-label="Close"
                  onClick={() => setRagModalOpen(false)}
                />
              </div>
              <div className="modal-body">
                <label className="form-label" htmlFor={ragSelectId}>
                  Data domain
                </label>
                <select
                  id={ragSelectId}
                  className="form-select"
                  value={ragPickId}
                  onChange={(e) => setRagPickId(e.target.value)}
                >
                  {ragDomains.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name} (#{d.id})
                    </option>
                  ))}
                </select>
                <label className="form-label mt-3" htmlFor={ragTopInputId}>
                  Top K (nearest articles by meaning)
                </label>
                <input
                  id={ragTopInputId}
                  type="number"
                  className="form-control"
                  min={1}
                  max={100}
                  step={1}
                  value={ragTop}
                  onChange={(e) => {
                    const n = parseInt(e.target.value, 10);
                    setRagTop(Number.isFinite(n) ? n : DEFAULT_RAG_TOP);
                  }}
                />
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-outline-secondary" onClick={() => setRagModalOpen(false)}>
                  Cancel
                </button>
                <button type="button" className="btn btn-primary" onClick={handleInsertRag}>
                  Insert
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {showPromptInserts && basicCtxModalOpen && (
        <div
          className="markdown-prompt-rag-modal modal fade show d-block"
          tabIndex={-1}
          role="dialog"
          aria-modal="true"
          aria-labelledby={basicCtxModalTitleId}
          style={{ backgroundColor: "rgba(15, 23, 42, 0.45)" }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setBasicCtxModalOpen(false);
          }}
        >
          <div className="modal-dialog modal-dialog-centered" onMouseDown={(e) => e.stopPropagation()}>
            <div className="modal-content">
              <div className="modal-header">
                <h5 className="modal-title" id={basicCtxModalTitleId}>
                  Insert basic context
                </h5>
                <button
                  type="button"
                  className="btn-close"
                  aria-label="Close"
                  onClick={() => setBasicCtxModalOpen(false)}
                />
              </div>
              <div className="modal-body">
                <label className="form-label" htmlFor={basicCtxSelectId}>
                  Placeholder
                </label>
                <select
                  id={basicCtxSelectId}
                  className="form-select"
                  value={basicCtxKind}
                  onChange={(e) => setBasicCtxKind(e.target.value)}
                >
                  {BASIC_CONTEXT_PRESETS.map((p) => (
                    <option key={p.kind} value={p.kind}>
                      {p.label}
                    </option>
                  ))}
                </select>
                <p className="text-muted small mt-2 mb-0">
                  {BASIC_CONTEXT_PRESETS.find((p) => p.kind === basicCtxKind)?.hint ?? ""}
                </p>
                {basicCtxKind === "conversation_history" && (
                  <>
                    <label className="form-label mt-3" htmlFor={basicCtxHistoryLimitId}>
                      Recent messages count
                    </label>
                    <input
                      id={basicCtxHistoryLimitId}
                      type="number"
                      className="form-control"
                      min={1}
                      max={500}
                      step={1}
                      value={basicCtxHistoryLimit}
                      onChange={(e) => {
                        const n = parseInt(e.target.value, 10);
                        setBasicCtxHistoryLimit(Number.isFinite(n) ? n : DEFAULT_CONV_HISTORY_LIMIT);
                      }}
                    />
                  </>
                )}
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-outline-secondary" onClick={() => setBasicCtxModalOpen(false)}>
                  Cancel
                </button>
                <button type="button" className="btn btn-primary" onClick={handleInsertBasicContext}>
                  Insert
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
