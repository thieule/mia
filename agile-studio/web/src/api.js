const custom = (import.meta.env.VITE_AGILE_API_BASE || "").trim();
const origin = custom
  ? custom.replace(/\/$/, "")
  : import.meta.env.DEV
    ? "/agile-api"
    : "http://127.0.0.1:9120";

export const API_BASE = `${origin}/api/v1`;

const TOKEN_KEY = "agile_auth_token";
const USER_KEY = "agile_auth_user";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser() {
  try {
    const s = localStorage.getItem(USER_KEY);
    return s ? JSON.parse(s) : null;
  } catch {
    return null;
  }
}

export function setAuth(token, user) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  else localStorage.removeItem(USER_KEY);
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

function authHeaders() {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

function jsonHeaders() {
  return { "Content-Type": "application/json", ...authHeaders() };
}

async function parseJson(res) {
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(text.slice(0, 300) || `HTTP ${res.status}`);
  }
}

function isPublicAuthPath(path) {
  return path === "/auth/login" || path === "/auth/register";
}

async function handleResponse(res, path, data) {
  if (res.status === 401 && !isPublicAuthPath(path)) {
    clearAuth();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.assign("/login");
    }
  }
  if (!res.ok) throw new Error(data?.detail || data?.error || JSON.stringify(data));
  return data;
}

export async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`, { headers: { ...authHeaders() } });
  const data = await parseJson(res);
  return handleResponse(res, path, data);
}

export async function apiPost(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
  });
  const data = await parseJson(res);
  return handleResponse(res, path, data);
}

export async function apiPatch(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
  });
  const data = await parseJson(res);
  return handleResponse(res, path, data);
}

export async function apiPut(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
  });
  const data = await parseJson(res);
  return handleResponse(res, path, data);
}

export async function apiDelete(path) {
  const res = await fetch(`${API_BASE}${path}`, { method: "DELETE", headers: { ...authHeaders() } });
  if (res.status === 204) return null;
  const data = await parseJson(res);
  return handleResponse(res, path, data);
}
