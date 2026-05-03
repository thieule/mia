USE agile_studio;

CREATE TABLE IF NOT EXISTS api_center_connections (
  id               INT UNSIGNED NOT NULL COMMENT 'singleton row id=1',
  endpoint         VARCHAR(2048) NOT NULL,
  connect_secret   VARCHAR(1024) NOT NULL,
  session_key      VARCHAR(2048) NULL,
  mcp_api_key      VARCHAR(2048) NULL,
  api_endpoints_json JSON NULL,
  created_at       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE api_center_connections
  ADD COLUMN IF NOT EXISTS api_endpoints_json JSON NULL AFTER mcp_api_key;
