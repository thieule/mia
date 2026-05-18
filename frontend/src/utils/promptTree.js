/**
 * Build a folder tree from mia_agent_prompts rows (label = workspace-relative path).
 */

export function buildPromptTree(prompts) {
  const root = { id: "", name: "(root)", children: {}, files: [] };
  for (const p of prompts || []) {
    const label = String(p.label || "").trim();
    if (!label) continue;
    const parts = label.split("/").filter(Boolean);
    if (parts.length === 0) continue;
    if (parts.length === 1) {
      root.files.push({ ...p, fileName: parts[0] });
      continue;
    }
    let node = root;
    for (let i = 0; i < parts.length - 1; i++) {
      const seg = parts[i];
      if (!node.children[seg]) {
        node.children[seg] = { id: `${node.id}/${seg}`.replace(/^\//, ""), name: seg, children: {}, files: [] };
      }
      node = node.children[seg];
    }
    const fileName = parts[parts.length - 1];
    node.files.push({ ...p, fileName });
  }
  const sortFiles = (a, b) => String(a.fileName).localeCompare(String(b.fileName));
  const sortNode = (node) => {
    node.files.sort(sortFiles);
    const keys = Object.keys(node.children).sort((a, b) => a.localeCompare(b));
    node.sortedChildren = keys.map((k) => {
      sortNode(node.children[k]);
      return node.children[k];
    });
  };
  sortNode(root);
  return root;
}

export function countPromptFiles(node) {
  let n = node.files?.length || 0;
  for (const c of node.sortedChildren || []) {
    n += countPromptFiles(c);
  }
  return n;
}
