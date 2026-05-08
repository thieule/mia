import { Component } from "react";
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import {
  AgileMarkdownAnchor,
  agileMarkdownUrlTransform,
  linkifyAgileStandaloneShortLinks,
} from "./agileMarkdownLink.jsx";
import { MarkdownPreviewPre } from "./markdownMermaidPreview.jsx";

/** LLM đôi khi dùng ¶ thay cho xuống dòng — đưa về newline để remark không lỗi cấu trúc. */
export function normalizeChatMarkdownSource(raw) {
  let s = String(raw || "")
    .replace(/\u00b6/g, "\n")
    .replace(/\r\n/g, "\n");
  if (s.includes("\\n") || s.includes("\\r")) {
    s = s.replace(/\\r\\n/g, "\n").replace(/\\r/g, "\n").replace(/\\n/g, "\n").replace(/\\t/g, "\t");
  }
  return s;
}

/**
 * react-markdown có thể throw với một số chuỗi (bảng/list lỗi, ký tự lạ) — fallback plain text.
 */
export class ChatMarkdownErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidUpdate(prevProps) {
    if (prevProps.source !== this.props.source) {
      this.setState({ hasError: false });
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <pre className="mb-0 small as-chat-md-fallback" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {this.props.source}
        </pre>
      );
    }
    return this.props.children;
  }
}

const CHAT_MARKDOWN_COMPONENTS = {
  a: AgileMarkdownAnchor,
  pre: MarkdownPreviewPre,
};

/**
 * Markdown (GFM) + highlight @mention — tách tại token @ để không làm hỏng parser.
 * mentionIndex: Map từ mentionKey (lowercase) → display name.
 */
export function renderMarkdownWithMentions(content, mentionIndex) {
  const idxMap = mentionIndex instanceof Map ? mentionIndex : new Map();
  const normalized = normalizeChatMarkdownSource(content);
  const parts = normalized.split(/(@[^\s@]+)/g);
  return parts.map((p, idx) => {
    if (!p.startsWith("@")) {
      if (!p) return null;
      const md = linkifyAgileStandaloneShortLinks(normalizeChatMarkdownSource(p));
      return (
        <div key={idx} className="as-chat-md as-md-prose-view">
          <ChatMarkdownErrorBoundary source={md}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkBreaks]}
              components={CHAT_MARKDOWN_COMPONENTS}
              urlTransform={agileMarkdownUrlTransform}
            >
              {md}
            </ReactMarkdown>
          </ChatMarkdownErrorBoundary>
        </div>
      );
    }
    const key = p.slice(1).toLowerCase();
    const matched = idxMap.has(key);
    return (
      <span key={idx} className={matched ? "as-chat-mention" : ""}>
        {p}
      </span>
    );
  });
}
