-- Add planning window (single day or range) for releases. Run once on existing MySQL.
-- mysql -h... -P... -uapp -p agile_studio < schema/migrate_release_starts_ends.sql

USE agile_studio;

ALTER TABLE releases
  ADD COLUMN starts_at DATETIME(3) NULL DEFAULT NULL,
  ADD COLUMN ends_at   DATETIME(3) NULL DEFAULT NULL;
