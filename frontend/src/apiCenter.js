/**
 * API Center admin — Mia agents & workspace prompts (database `agent`).
 */

const API_CENTER_BASE = import.meta.env.VITE_API_CENTER_BASE || "http://127.0.0.1:18881";
const ADMIN_SECRET = import.meta.env.VITE_API_CENTER_ADMIN_SECRET || "";

async function adminRequest(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (ADMIN_SECRET) {
    headers["X-Api-Center-Admin-Secret"] = ADMIN_SECRET;
  }
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`${API_CENTER_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const j = JSON.parse(text);
      detail = j.detail || j.message || text;
    } catch {
      /* keep text */
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const apiCenter = {
  listMiaAgents: () => adminRequest("/v1/admin/agents"),
  createMiaAgent: (payload) =>
    adminRequest("/v1/admin/agents", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listPrompts: (agentId) => adminRequest(`/v1/admin/agents/${encodeURIComponent(agentId)}/prompts`),
  getPrompt: (agentId, kind, label) => {
    const q = new URLSearchParams({ kind, label });
    return adminRequest(`/v1/admin/agents/${encodeURIComponent(agentId)}/prompts/item?${q}`);
  },
  savePrompt: (agentId, payload) =>
    adminRequest(`/v1/admin/agents/${encodeURIComponent(agentId)}/prompts`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export function isApiCenterConfigured() {
  return Boolean(ADMIN_SECRET?.trim());
}
