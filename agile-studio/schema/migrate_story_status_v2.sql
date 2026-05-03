-- Migrate old story statuses to the new Kanban flow.
-- Old: icebox | backlog | ready | in_progress | review | done | cancelled
-- New: icebox_* | backlog_unstart | current_* | done

USE agile_studio;

UPDATE stories SET status = 'icebox_in_progress' WHERE status = 'icebox';
UPDATE stories SET status = 'backlog_unstart' WHERE status = 'backlog';
UPDATE stories SET status = 'current_unstart' WHERE status = 'ready';
UPDATE stories SET status = 'current_started' WHERE status = 'in_progress';
UPDATE stories SET status = 'current_review' WHERE status = 'review';
UPDATE stories SET status = 'icebox_rejected' WHERE status = 'cancelled';
