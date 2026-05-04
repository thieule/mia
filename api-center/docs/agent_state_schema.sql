-- Agent / prompt / skill / working-queue / state — reference schema
-- Target: PostgreSQL 14+ (JSONB). For SQLite: replace JSONB with TEXT + json_valid checks in app layer.

CREATE TABLE agents (
    id                  TEXT PRIMARY KEY,
    display_name        TEXT NOT NULL,
    workspace_root      TEXT NOT NULL,
    config_path         TEXT,
    gateway_port        INTEGER,
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agent_prompts (
    id                  BIGSERIAL PRIMARY KEY,
    agent_id            TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    kind                TEXT NOT NULL,
    label               TEXT,
    source_path         TEXT NOT NULL DEFAULT '',
    content_sha256      CHAR(64) NOT NULL,
    content             TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (agent_id, kind, source_path)
);

CREATE TABLE workspace_skills (
    agent_id            TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    skill_name          TEXT NOT NULL,
    source              TEXT NOT NULL CHECK (source IN ('workspace', 'builtin')),
    skill_path          TEXT NOT NULL,
    body_sha256         CHAR(64) NOT NULL,
    last_scanned_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, skill_name, source)
);

CREATE TABLE working_queue_tasks (
    id                  TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    project_id          TEXT NOT NULL,
    item_kind           TEXT NOT NULL DEFAULT 'task',
    status              TEXT NOT NULL,
    location            TEXT NOT NULL,
    message               TEXT,
    source_role         TEXT,
    service             TEXT,
    enqueued_by         TEXT,
    context             JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL,
    completed_at        TIMESTAMPTZ,
    error               TEXT,
    result_excerpt      TEXT,
    storage_path        TEXT
);

CREATE INDEX wq_tasks_agent_location ON working_queue_tasks (agent_id, location);
CREATE INDEX wq_tasks_agent_project ON working_queue_tasks (agent_id, project_id);

CREATE TABLE working_queue_events (
    id                  BIGSERIAL PRIMARY KEY,
    task_id             TEXT NOT NULL REFERENCES working_queue_tasks(id) ON DELETE CASCADE,
    event               TEXT NOT NULL,
    detail              JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX wq_events_task ON working_queue_events (task_id);

CREATE TABLE agent_state_kv (
    agent_id            TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    namespace           TEXT NOT NULL,
    key                 TEXT NOT NULL,
    value               JSONB NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, namespace, key)
);

CREATE TABLE session_index (
    agent_id            TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    session_key         TEXT NOT NULL,
    storage_path        TEXT NOT NULL,
    message_count       INTEGER NOT NULL DEFAULT 0,
    content_sha256      CHAR(64),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, session_key)
);
