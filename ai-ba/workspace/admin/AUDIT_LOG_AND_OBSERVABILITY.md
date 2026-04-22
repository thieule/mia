# Audit trail and observability (Mia BA)

**Status:** Human-maintained policy under `admin/`. Describes **what Mia BA / nanobot already records** and **how admins can review** it. Mia BA **must not** edit files in `admin/` without an approved workflow.

---

## 1. What you can review today (no extra code)

### 1.1. Conversation + tool-use history (primary “audit log”)

| Location | Content |
|----------|---------|
| **`workspace/sessions/*.jsonl`** | One file per **session key** (typically `discord_<channel_id>` for guild channels, or DM keys). Each file is **JSONL**: first line is **metadata** (`_type`, `key`, timestamps); following lines are **messages** (`role`, `content`, `timestamp`, and—when the model used tools—**`tool_calls`** on assistant turns and **`tool`** / **`tool_call_id`** on tool results). |

**How to use it**

- Inspect the latest file for a channel: sort by `mtime` or use `SessionManager.list_sessions` behaviour (newest `updated_at`).
- Search for tool names: `grep -n "read_file\\|write_file\\|exec\\|mcp_" workspace/sessions/*.jsonl` (adapt for your shell).
- **Retention:** `sessions/` is often **gitignored** (see `ai-ba/.gitignore`); copy snapshots to secure storage if you need **long-term compliance** archives.

This is **not** a separate tamper-evident “audit database”; it is the **same store** the agent uses for context. Treat it as the **best built-in trace** of what the model did in each chat.

### 1.2. Dream / memory append-only log

| Location | Content |
|----------|---------|
| **`workspace/memory/history.jsonl`** | Append-only events for memory consolidation (when Dream runs). Useful for **memory-side** changes, not a full substitute for tool-level forensics. |

### 1.3. Gateway process logs (stdout / stderr)

Nanobot uses **loguru** (and libraries such as **httpcore**) to log to the **console** where you run `python start.py`.

- **Capture:** redirect output to a file or pipe into your log stack (e.g. `tee`, systemd journal, Docker logs, CloudWatch).
- **Discord:** lines such as “ignored (mention mode)” or “connected” help debug **delivery**, not every tool argument.

### 1.4. Cron (if enabled)

| Location | Content |
|----------|---------|
| **`workspace/cron/action.jsonl`** (when cron jobs run) | Records **cron-triggered** actions where implemented. |

### 1.5. Git + human artefacts (strongest proof of code changes)

| Source | Content |
|--------|---------|
| **`git log` / PRs** | Immutable history of **commits** (who, when, diff). |
| **`projects/<slug>/docs/COMPLETION_CHECKLIST.md`** | Human-oriented **closure record** per task (see **`DOCUMENTATION_AND_COMPLETION_CHECKLIST.md`**). |

A Tech policy already requires **checklists** and **pytest** before “done”; those files are part of your **governance pack** alongside Git.

---

## 2. What is **not** provided out of the box

- **Central SIEM** integration, **WORM** storage, or **per-field redaction** for secrets inside session JSONL (if a user pasted a key into chat, it may appear in the session file—**rotate secrets** and restrict channel access).
- **Per-tool immutable audit table** separate from the LLM session (would require a custom middleware or fork).

If you need enterprise audit, plan **log shipping**, **retention**, and **access control** on the host that runs the gateway and on backups of `sessions/`.

---

## 3. Optional Discord / gateway settings for control

- **`channels.discord.sendToolHints`** (nanobot `channels` config): when `true`, surfaces **short tool hints** in the channel during runs (more visible to humans, more noise).
- **`groupPolicy`**: `"mention"` reduces accidental invocations in busy channels (see gateway logs).

---

## 4. Suggested admin routine

1. **Weekly or per release:** sample `sessions/*.jsonl` for active channels; confirm tool patterns match policy (**`PRE_IMPLEMENTATION_APPROVAL`**, **`CODE_COMMENTS_AND_ERRORS_ENGLISH`**, etc.).
2. **After incidents:** export relevant `discord_<channel>.jsonl` + gateway log slice + Git SHAs.
3. **Secrets:** if leakage is suspected in JSONL, **revoke** credentials; consider **truncating** or archiving then deleting local session files under team policy.

---

## 5. Relation to other policy

- **`DOCUMENTATION_AND_COMPLETION_CHECKLIST.md`** — written closure artefacts.
- **`PRE_IMPLEMENTATION_APPROVAL.md`** — cross-check that writes in JSONL align with approved scope when reviewing.
