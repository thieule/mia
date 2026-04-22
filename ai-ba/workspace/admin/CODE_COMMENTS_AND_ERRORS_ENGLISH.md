# Code, errors, and repository documentation in English (Mia BA)

**Status:** Human-maintained policy under `admin/`. Mia BA **must read and follow** this file when writing or editing **code** or **repository documentation** covered below. It **must not** edit files in `admin/` without an approved workflow.

---

## 1. Purpose

Keep the repository **consistent for international collaborators and tooling**:

- Anything in **source** that explains behaviour or surfaces **errors** to developers or operators must be in **English**.
- Any **markdown (or equivalent) documentation** that Mia BA **creates or updates** because **policy or task requirements** call for docs (e.g. **`DOCUMENTATION_AND_COMPLETION_CHECKLIST.md`**, **`docs/AI_PROJECT_WORKSPACE_SPEC.md`**, README updates, `projects/<slug>/docs/`, completion checklists) must be written in **English** as well.

This policy does **not** restrict the **language of chat** with end users (e.g. Discord) unless the team extends it elsewhere.

---

## 2. In scope — source code (English required)

| Artefact | Rule |
|----------|------|
| **Inline comments** (`#`, `//`, `/* */`, etc.) that explain logic, caveats, or usage | **English** |
| **Block comments** above functions/classes/modules | **English** |
| **Docstrings** (Python, JSDoc, etc.) that document behaviour | **English** |
| **Exception messages** (`raise`, `throw`, `panic!`, …) | **English** |
| **User/developer-facing error strings** returned from APIs, CLI stderr/stdout, structured error payloads | **English** |
| **Log messages** intended for operators (logger, `console.error`, …) added or changed by Mia BA | **English** |
| **`assert` / invariant messages** shown on failure | **English** |

---

## 3. In scope — repository documentation (English required)

Applies whenever Mia BA **writes or materially edits** these as part of a task or **mandatory policy** (not casual notes in chat):

| Artefact | Rule |
|----------|------|
| **`README.md`** (root, module, or `projects/<slug>/`) | **English** |
| **`docs/**/*.md`** under the repo or `projects/<slug>/docs/` (ADRs, runbooks, design notes, API guides) | **English** |
| **`COMPLETION_CHECKLIST.md`** and similar closure files | **English** |
| **OpenAPI / Swagger descriptions**, schema `description` fields, config templates with explanatory prose | **English** |
| **Diagram captions and section titles** inside the above docs | **English** |

If the **user explicitly requests** a specific document in another language **in writing** and an **admin documents an exception** in §5, follow that exception for that file only.

---

## 4. Out of scope (not overridden by this file)

- **Third-party** code, generated code, or vendored snapshots — do not rewrite solely for language unless the task is to localise or the team requests it.
- **Quoted literals** reproducing external specs, protocol constants, or legal text in another language — keep as-is; add an English comment or sidebar if clarification helps.
- **Existing** comments or docs in another language — when touching that region, **prefer** translating to English in the same change (or leave unchanged if out of scope for the approved patch; note in checklist if left intentionally).
- **Ephemeral chat** or Discord-only explanations — not required to be English in the repo unless you paste them into a committed file (then §2–§3 apply).

---

## 5. Exceptions (admin-maintained)

- *(None by default.)*

---

## 6. Relation to other policy

- **`DOCUMENTATION_AND_COMPLETION_CHECKLIST.md`** — doc deliverables must satisfy **§3** here as well as checklist completeness.
- **`TESTING_AND_DEFINITION_OF_DONE.md`** — failing tests may surface messages; new messages must comply with **§2**.
