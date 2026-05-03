const STORAGE_KEY = "agile-studio-notifications-v1";

export const MAX_NOTIFICATIONS = 80;

export function loadNotifications() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

export function saveNotifications(items) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  } catch {
    /* ignore quota */
  }
}

export function makeNotification({ type = "info", title, body = "", link = null }) {
  const id =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  return {
    id,
    type,
    title,
    body,
    link,
    createdAt: Date.now(),
    read: false,
  };
}

/** True if text contains @displayName as a mention (case-insensitive). */
export function textMentionsDisplayName(text, displayName) {
  if (!text || !displayName?.trim()) return false;
  const esc = displayName.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`@${esc}(?:\\s|$|[.,!?;:])`, "i");
  return re.test(text);
}

export function notificationIconClass(type) {
  switch (type) {
    case "story":
      return "bi-kanban";
    case "comment":
      return "bi-chat-dots";
    case "mention":
      return "bi-at";
    case "project":
      return "bi-folder2";
    case "team":
      return "bi-people";
    default:
      return "bi-info-circle";
  }
}
