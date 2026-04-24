# Mia QC — setup: API, UI, tools

## Mục tiêu dòng này

- **Test API:** pytest / httpx / OpenAPI, mã trạng thái, schema, lỗi biên, auth (theo môi trường cho phép).
- **Test giao diện (UI):** E2E (Playwright, Cypress qua `npx` + **`exec`** nếu đã cài trên host), smoke, luồng chính; gợi ý a11y smoke (cần công cụ/role phù hợp trên máy chạy gateway).
- **Chất lượng:** kế hoạch kiểm thử, case, bước tái hiện, liên kết issue / PR (GitHub MCP).

## Cổng & biến

| | Mia tech | Mia BA | Mia DevOps | **Mia QC** |
|---|----|----|----|----|
| Port | 18792 | 18793 | 18794 | **18795** |
| Folder | `ai-tech` | `ai-ba` | `ai-devops` | **`ai-qc`** |
| Discord | `MIA_TECH` | `MIA_BA` | `MIA_DEVOPS` | **`MIA_QC`** |

`start.py` đặt `TEST_RUNS_PATH_MIA_QC` → `workspace/agent/test-runs/` nếu trống (báo cáo JSON từ pytest MCP).

## Công cụ mặc định trong `config.json`

- **`mcpServers.pytest_runner`** — chạy bộ test Python/pytest, đọc kết quả JSON.
- **`github`** — Actions, file workflow, issues (dùng cho xác minh pipeline).
- **`registry`** — tìm MCP đã cắm thêm.
- **`exec`** — 300s: `pytest`, `npx playwright test`, `npm test`, v.v. **chỉ khi** lệnh tồn tại trên `PATH` và theo `admin/`.
- **`web_search` / `web_fetch`** — tài liệu công cụ, release notes trình duyệt / runner.

**Không** có sẵn trình duyệt thật trong gateway — E2E thường chạy trên cùng máy dev/CI; agent chỉ tạo/kèm lệnh và phân tích kết quả bạn cung cấp hoặc từ `exec`.

## API: gợi ý thực hành

1. Cố định **base URL** staging/test (trong `USER.md` hoặc env, không commit secret).
2. Viết hoặc chạy **pytest** với marker phù hợp; dùng `mcp_pytest_runner_*` theo chính sách Mia tech/BA về “done” nếu có code.
3. Kiểm tra **schema** (Pydantic / jsonschema) khi hợp đồng API có file định nghĩa.
4. Không in **token thật** trong log; dùng env hoặc file local gitignored.

## UI / E2E: gợi ý thực hành

1. Cài **Node +** Playwright/Cypress trên host chạy gateway nếu muốn agent gọi `npx` qua `exec`.
2. Lưu cấu hình baseURL trong repo test theo chuẩn team; agent đọc file, không tự tạo credential.
3. **Screenshot / trace:** đường dẫn nên nằm dưới `workspace/agent/` hoặc repo test — không trộn bí mật màn hình sản xuất.

## Thêm MCP (tuỳ chọn)

Cùng pattern `tools.mcpServers` như [../ai-devops/docs/DEVOPS_SETUP.md](../ai-devops/docs/DEVOPS_SETUP.md): cấu hình, secret qua env, restart gateway, kiểm qua `mcp_registry_list_all_tools`.

## Bảo mật

- `restrictToWorkspace: false` giúp đọc cây mã ngoài `ai-qc` — cân nhắc **`true`** + mở path cho gateway mạo hiểm (Discord, IP công cộng).
- Dữ liệu cá nhân / PII trong bài test: xử lý theo chính sách công ty; không dùng dữ liệu sản xuất thật mà chưa được phép.
