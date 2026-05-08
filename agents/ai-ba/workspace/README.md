# Mia BA workspace (orientation)

This folder is the **runtime workspace** for the Mia BA gateway (policies, drafts, memory). It is **not** the same thing as a **BA deliverable document pack** handed to engineering or other agents.

## BA deliverable outputs — README as index (mandatory)

For every **coherent set of BA outputs** you produce for others to consume (e.g. `projects/<slug>/`, `projects/<slug>/docs/`, a client engagement folder under `agent/`, or a path given by Agile `documents_storage_path`):

1. Put a **`README.md` at the root of that pack** (the folder that is the “unit of handoff”).
2. In that README, keep a **table of contents**: table of relative paths + one-line summary for each spec / BRD / diagram / annex.
3. Other Mia agents (tech, PM, …) should **open that pack’s `README.md` first**, then follow links—do not rely on them guessing filenames.

See **`AGENTS.md`** in this directory for the full rule. **Policy (rules):** [`policy/README.md`](./policy/README.md). **Layout / audit how-to (not policy):** [`docs/README.md`](./docs/README.md). Deployment overview: [../README.md](../README.md) · [../docs/README.md](../docs/README.md)
