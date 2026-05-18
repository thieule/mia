-- Mia agent registry, prompts, skills, working-queue mirror (database `agent`).
-- Tách khỏi agile_studio — API Center / gateway dùng MIA_AGENT_DATABASE_URL.
CREATE DATABASE IF NOT EXISTS agent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON agent.* TO 'app'@'%';
FLUSH PRIVILEGES;
