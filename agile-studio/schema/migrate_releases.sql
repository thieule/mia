-- Migration: Add releases table and link to stories
-- Created at: 2026-04-22

CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'planning',
    released_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
);

-- Add release_id to stories table
-- SQLite doesn't support adding FK directly in ALTER TABLE for existing tables easily without recreating,
-- but for PoC we can just add the column.
ALTER TABLE stories ADD COLUMN release_id INTEGER REFERENCES releases (id) ON DELETE SET NULL;
