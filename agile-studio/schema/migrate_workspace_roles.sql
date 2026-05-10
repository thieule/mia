-- Thêm master data workspace_roles cho Agile Studio (DB đã tồn tại trước init_mysql bản mới).
-- Chạy tay: mysql -h127.0.0.1 -P3307 -uroot -p agile_studio < schema/migrate_workspace_roles.sql

USE agile_studio;

CREATE TABLE IF NOT EXISTS workspace_roles (
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  slug          VARCHAR(64)     NOT NULL COMMENT 'khóa lưu trong project_members.role / invites',
  name          VARCHAR(255)    NOT NULL COMMENT 'nhãn hiển thị',
  description   TEXT            NULL,
  sort_order    INT             NOT NULL DEFAULT 0,
  is_system     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '1 = role seed hệ thống',
  created_at    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uq_workspace_roles_slug (slug),
  KEY idx_workspace_roles_sort (sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO workspace_roles (slug, name, description, sort_order, is_system, created_at, updated_at) VALUES
('owner', 'Owner', 'Toàn quyền dự án.', 10, 1, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3)),
('admin', 'Admin', 'Quản trị thành viên, cấu hình và backlog.', 20, 1, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3)),
('member', 'Member', 'Người đóng góp tiêu chuẩn.', 30, 1, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3)),
('viewer', 'Viewer', 'Chỉ đọc.', 40, 1, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3)),
('product_owner', 'Product Owner', 'Ưu tiên backlog và chấp nhận deliverable.', 50, 1, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3)),
('scrum_master', 'Scrum Master', 'Điều phối quy trình, gỡ vướng.', 60, 1, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3)),
('developer', 'Developer', 'Phát triển và giao increment.', 70, 1, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3)),
('tester', 'Tester / QA', 'Kiểm thử và tiêu chí nghiệm thu.', 80, 1, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3)),
('stakeholder', 'Stakeholder', 'Tham vấn; thường phạm vi ghi hạn chế.', 90, 1, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3)),
('ux_designer', 'UX Designer', 'Thiết kế trải nghiệm và giao diện.', 100, 1, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3));

INSERT IGNORE INTO workspace_roles (slug, name, sort_order, is_system, created_at, updated_at)
SELECT x.role, x.role, 200, 0, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3)
FROM (
  SELECT DISTINCT role FROM project_members WHERE role IS NOT NULL AND TRIM(role) != ''
  UNION
  SELECT DISTINCT role FROM project_invites WHERE role IS NOT NULL AND TRIM(role) != ''
) AS x
WHERE NOT EXISTS (SELECT 1 FROM workspace_roles wr WHERE wr.slug = x.role);

-- Sửa dòng đã insert trước đó với zero-datetime (một số cấu hình MySQL).
UPDATE workspace_roles
SET created_at = CURRENT_TIMESTAMP(3), updated_at = CURRENT_TIMESTAMP(3)
WHERE created_at = '0000-00-00 00:00:00' OR updated_at = '0000-00-00 00:00:00';
