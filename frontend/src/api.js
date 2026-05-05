const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

/** Dịch vụ runtime (điều phối workflow, stream chat) — mặc định port 8001 */
export const RUNTIME_BASE =
  import.meta.env.VITE_RUNTIME_BASE || import.meta.env.VITE_AGENT_BASE || "http://localhost:8001";
/** @deprecated dùng RUNTIME_BASE; giữ tương thích .env cũ */
export const AGENT_BASE = RUNTIME_BASE;

/**
 * SSE từ POST /runtime/agents/:id/chat/stream — yield từng object JSON sau `data: `.
 */
export async function* agentChatStream(agentId, body) {
  const res = await fetch(`${RUNTIME_BASE}/runtime/agents/${agentId}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || `HTTP ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6));
        } catch {
          /* ignore malformed chunk */
        }
      }
    }
  }
  const tail = buffer.trim();
  if (tail) {
    for (const line of tail.split(/\r?\n/)) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6));
        } catch {
          /* ignore */
        }
      }
    }
  }
}

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "API error");
  }
  return res.json();
}

export const api = {
  listAgents: () => request("/agents"),
  createAgent: (payload) =>
    request("/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateAgent: (agentId, payload) =>
    request(`/agents/${agentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  listPromptVersions: (agentId) => request(`/agents/${agentId}/prompt-versions`),
  createPromptVersion: (agentId, payload) =>
    request(`/agents/${agentId}/prompt-versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updatePromptVersion: (id, payload) =>
    request(`/prompt-versions/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  clonePromptVersion: (id, payload) =>
    request(`/prompt-versions/${id}/clone`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  /** Một agent chỉ có một version active; các version khác tự gỡ active. */
  activatePromptVersion: (id) =>
    request(`/prompt-versions/${id}/activate`, {
      method: "POST",
    }),
  checkPrompt: (id, payload) =>
    request(`/prompt-versions/${id}/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  runtimeTestPromptVersion: (id, payload) =>
    request(`/prompt-versions/${id}/runtime-test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  /** Một lần gọi agent runtime (không stream) — cùng pipeline với chat, trả full text */
  agentRuntimeComplete: (promptVersionId, payload) =>
    request(`/prompt-versions/${promptVersionId}/agent-runtime-complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload ?? {}),
    }),
  listTestRuns: (id) => request(`/prompt-versions/${id}/test-runs`),
  checkPromptDataset: (versionId, payload) =>
    request(`/prompt-versions/${versionId}/check-dataset`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  listEvalDatasets: () => request("/eval-datasets"),
  createEvalDataset: (payload) =>
    request("/eval-datasets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateEvalDataset: (id, payload) =>
    request(`/eval-datasets/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteEvalDataset: async (id) => {
    const res = await fetch(`${API_BASE}/eval-datasets/${id}`, { method: "DELETE" });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || "API error");
    }
  },
  importEvalDatasetCsv: (datasetId, file) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/eval-datasets/${datasetId}/import-csv`, {
      method: "POST",
      body: form,
    });
  },
  /** GET /domains */
  listDomains: () => request("/domains"),
  /** POST /domains — create domain */
  createDomain: (payload) =>
    request("/domains", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  /** GET /domains/:id */
  getDomain: (domainId) => request(`/domains/${domainId}`),
  /** DELETE /domains/:id — xóa domain và toàn bộ dữ liệu index ES */
  deleteDomain: async (domainId) => {
    const res = await fetch(`${API_BASE}/domains/${domainId}`, { method: "DELETE" });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || "API error");
    }
  },
  /** PATCH /domains/:id — cross-domain reference disabled on server unless ALLOW_CROSS_DOMAIN_ARTICLE_REFERENCE is set */
  updateDomain: (domainId, payload) =>
    request(`/domains/${domainId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  listDomainArticles: (domainId) => request(`/domains/${domainId}/articles`),
  createManualDomainArticle: (domainId, payload) =>
    request(`/domains/${domainId}/articles/manual`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateDomainArticle: (domainId, articleId, payload) =>
    request(`/domains/${domainId}/articles/${encodeURIComponent(articleId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  uploadDomainFile: async (domainId, file) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/domains/${domainId}/articles/upload`, {
      method: "POST",
      body: form,
    });
  },
  /** POST — tải nội dung từ URL công khai vào domain */
  ingestWebUrls: (domainId, payload) =>
    request(`/domains/${domainId}/articles/ingest/llamaindex-web`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteDomainArticle: async (domainId, articleId) => {
    const res = await fetch(
      `${API_BASE}/domains/${domainId}/articles/${encodeURIComponent(articleId)}`,
      { method: "DELETE" },
    );
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || "API error");
    }
  },
  analytics: () => request("/analytics/prompt-improvement"),

  listTools: () => request("/settings/tools"),
  /** Catalog công cụ nội bộ (XML trong backend); imported = đã copy vào bảng tools */
  listInternalTools: () => request("/settings/internal-tools"),
  importInternalTools: (payload) =>
    request("/settings/tools/import-internal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  createTool: (payload) =>
    request("/settings/tools", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateTool: (toolId, payload) =>
    request(`/settings/tools/${toolId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteTool: async (toolId) => {
    const res = await fetch(`${API_BASE}/settings/tools/${toolId}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || "API error");
    }
  },

  /** Định nghĩa workflow (MySQL) — designer */
  listWorkflowDefinitions: () => request("/workflow-designer/definitions"),
  getWorkflowDefinition: (workflowKey, versionTag = "v1") =>
    request(
      `/workflow-designer/definitions/${encodeURIComponent(workflowKey)}?version_tag=${encodeURIComponent(versionTag)}`,
    ),
  putWorkflowDefinition: (workflowKey, body, versionTag = "v1") =>
    request(
      `/workflow-designer/definitions/${encodeURIComponent(workflowKey)}?version_tag=${encodeURIComponent(versionTag)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
};
