-- Chạy một lần khi volume MySQL trống (docker compose up lần đầu).
-- Service agile-studio / agile-studio-mcp dùng database `agile_studio` (khác MYSQL_DATABASE mặc định).
CREATE DATABASE IF NOT EXISTS agile_studio CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON agile_studio.* TO 'app'@'%';
FLUSH PRIVILEGES;
