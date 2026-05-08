import { MermaidBlock } from "./MermaidBlock.jsx";

/** Plain text from react-markdown `code` children (fenced block). */
export function markdownCodeChildrenToString(node) {
  if (node == null) return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(markdownCodeChildrenToString).join("");
  if (typeof node === "object" && node.props != null && node.props.children != null) {
    return markdownCodeChildrenToString(node.props.children);
  }
  return String(node);
}

/** Use as react-markdown `components.pre` — renders ```mermaid blocks via MermaidBlock. */
export function MarkdownPreviewPre({ children, ...props }) {
  const child = Array.isArray(children) ? children[0] : children;
  const cls =
    child && typeof child === "object" && child.props != null
      ? String(child.props.className || "")
      : "";
  if (cls.includes("language-mermaid")) {
    const chart = markdownCodeChildrenToString(child.props.children).replace(/\n$/, "");
    return <MermaidBlock chart={chart} />;
  }
  return <pre {...props}>{children}</pre>;
}

export const markdownMermaidPreviewComponents = {
  pre: MarkdownPreviewPre,
};
