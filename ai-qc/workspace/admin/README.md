# Admin — Mia QC

Mia QC **must** follow every file linked below before mutating code, canonical specs, or systems.

## Policy files

| File | Purpose |
|------|---------|
| [**PRE_IMPLEMENTATION_APPROVAL.md**](./PRE_IMPLEMENTATION_APPROVAL.md) | **Mandatory:** confirm plan with an **admin** before `write_file` / `edit_file` / mutating `exec` / implementation `spawn` |
| [**TESTING_AND_DEFINITION_OF_DONE.md**](./TESTING_AND_DEFINITION_OF_DONE.md) | **Mandatory:** new/changed code needs **unit tests**; **run pytest** before claiming **done** |
| [**DOCUMENTATION_AND_COMPLETION_CHECKLIST.md**](./DOCUMENTATION_AND_COMPLETION_CHECKLIST.md) | **Mandatory:** after work, **update docs**; fill **completion checklist**; **`projects/<slug>/docs/`** per project/module |
| [**CODE_COMMENTS_AND_ERRORS_ENGLISH.md**](./CODE_COMMENTS_AND_ERRORS_ENGLISH.md) | **Mandatory:** **English** for code comments, errors/logs, and **policy-driven repo docs** (README, `docs/`, checklists, …) |
| [**AUDIT_LOG_AND_OBSERVABILITY.md**](./AUDIT_LOG_AND_OBSERVABILITY.md) | **Reference:** where **sessions / logs / Git** record what Mia QC did; how admins **review** |
| *(add as needed)* | Allowed `exec` roots, named approvers for non-Discord sessions, stricter `restrictToWorkspace` notes |

## Optional tightening

Use this folder to record **allowed path roots** or **who may trigger `exec`** on shared gateways when you lock down beyond defaults.

Default repo config is aimed at **trusted local development** with broad read access; **production or Discord-facing** installs should treat **`PRE_IMPLEMENTATION_APPROVAL.md`** as enforceable and list approvers here.
