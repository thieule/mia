import { useMemo, useState } from "react";
import { buildPromptTree, countPromptFiles } from "../utils/promptTree";

function TreeFolder({ node, depth, expanded, onToggle, selectedKey, onSelectFile }) {
  const folderKey = node.id || node.name;
  const isOpen = expanded[folderKey] !== false;

  return (
    <li className="prompt-tree-folder">
      <button
        type="button"
        className="prompt-tree-row prompt-tree-folder-btn"
        style={{ paddingLeft: `${8 + depth * 14}px` }}
        onClick={() => onToggle(folderKey)}
        aria-expanded={isOpen}
      >
        <i className={`bi ${isOpen ? "bi-chevron-down" : "bi-chevron-right"} prompt-tree-chevron`} aria-hidden />
        <i className="bi bi-folder2-open text-warning" aria-hidden />
        <span className="prompt-tree-label">{node.name}</span>
      </button>
      {isOpen && (
        <ul className="list-unstyled mb-0">
          {(node.sortedChildren || []).map((child) => (
            <TreeFolder
              key={child.id || child.name}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              onToggle={onToggle}
              selectedKey={selectedKey}
              onSelectFile={onSelectFile}
            />
          ))}
          {node.files.map((f) => {
            const key = `${f.kind}::${f.label}`;
            const active = selectedKey === key;
            return (
              <li key={key}>
                <button
                  type="button"
                  className={`prompt-tree-row prompt-tree-file-btn ${active ? "active" : ""}`}
                  style={{ paddingLeft: `${8 + (depth + 1) * 14}px` }}
                  onClick={() => onSelectFile(f)}
                >
                  <i className="bi bi-file-earmark-text text-primary" aria-hidden />
                  <span className="prompt-tree-label">{f.fileName}</span>
                  <span className="prompt-tree-meta text-muted">{f.kind}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}

/**
 * @param {Array<{ kind: string, label: string, content_chars?: number }>} prompts
 * @param {{ kind: string, label: string } | null} selected
 * @param {(row: object) => void} onSelect
 */
export default function WorkspacePromptTree({ prompts, selected, onSelect }) {
  const tree = useMemo(() => buildPromptTree(prompts), [prompts]);
  const total = useMemo(() => countPromptFiles(tree), [tree]);
  const [expanded, setExpanded] = useState({});

  const selectedKey = selected ? `${selected.kind}::${selected.label}` : null;

  function toggleFolder(key) {
    setExpanded((prev) => ({ ...prev, [key]: prev[key] === false }));
  }

  if (!prompts?.length) {
    return <p className="text-muted small mb-0">Chưa có prompt trong DB. Chạy script sync từ workspace.</p>;
  }

  return (
    <div className="prompt-tree">
      <div className="prompt-tree-header small text-muted mb-2">{total} file</div>
      <ul className="list-unstyled mb-0">
        {(tree.sortedChildren || []).map((child) => (
          <TreeFolder
            key={child.id || child.name}
            node={child}
            depth={0}
            expanded={expanded}
            onToggle={toggleFolder}
            selectedKey={selectedKey}
            onSelectFile={onSelect}
          />
        ))}
        {tree.files.map((f) => {
          const key = `${f.kind}::${f.label}`;
          return (
            <li key={key}>
              <button
                type="button"
                className={`prompt-tree-row prompt-tree-file-btn ${selectedKey === key ? "active" : ""}`}
                style={{ paddingLeft: "8px" }}
                onClick={() => onSelect(f)}
              >
                <i className="bi bi-file-earmark-text text-primary" aria-hidden />
                <span className="prompt-tree-label">{f.fileName}</span>
                <span className="prompt-tree-meta text-muted">{f.kind}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
