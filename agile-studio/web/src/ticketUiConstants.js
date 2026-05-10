/** Shared labels for ticket priority / kind / workflow (mirror API enums). */

/** Values for task_status on story tasks (tickets). */
export const TICKET_STATUS_OPTIONS = [
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In progress" },
  { value: "blocked", label: "Blocked" },
  { value: "done", label: "Done" },
];

export const TICKET_PRIORITY_OPTIONS = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "urgent", label: "Urgent" },
];

export const TICKET_TYPE_OPTIONS = [
  { value: "task", label: "Task" },
  { value: "bug", label: "Bug" },
  { value: "feature", label: "Feature" },
  { value: "chore", label: "Chore" },
  { value: "technical_debt", label: "Technical debt" },
  { value: "docs", label: "Documentation" },
  { value: "support", label: "Support" },
  { value: "other", label: "Other" },
];

export function ticketPriorityLabel(v) {
  if (!v) return "—";
  return TICKET_PRIORITY_OPTIONS.find((o) => o.value === v)?.label ?? v;
}

export function ticketTypeLabel(v) {
  if (!v) return "—";
  return TICKET_TYPE_OPTIONS.find((o) => o.value === v)?.label ?? v.replace(/_/g, " ");
}

export function isoToDatetimeLocal(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** null = clear deadline */
export function datetimeLocalToDueIso(local) {
  if (local == null || !String(local).trim()) return null;
  const d = new Date(local);
  if (Number.isNaN(d.getTime())) return undefined;
  return d.toISOString();
}
