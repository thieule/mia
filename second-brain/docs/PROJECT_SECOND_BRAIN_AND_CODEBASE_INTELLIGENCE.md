# Project Second Brain & Codebase Intelligence

Tài liệu thiết kế mục tiêu cho hệ thống **Second Brain** và **Codebase Intelligence**, kèm **đối chiếu trạng thái triển khai** trong repo `second-brain/` và các dịch vụ liên quan.

---

## 1. Overview

Khả năng lập chỉ mục và truy vấn tri thức từ **codebase**, **tài liệu** và **thực thể Agile Studio**, nhằm hỗ trợ RAG lai (vector + đồ thị) cho AI Agent.

---

## 2. Architecture Components

### 2.1. Data Ingestion Pipeline

| Thành phần | Mục tiêu thiết kế | Ghi chú triển khai hiện tại (xem mục 7) |
|------------|-------------------|----------------------------------------|
| **Git Integration** | Webhook GitHub → đồng bộ mã, diff, commit | **Một phần:** `POST /ingest/github-webhook` (push) + PAT đọc file qua GitHub API; `:Commit`, `:CodeFile`, `(Commit)-[:MODIFIES]->(CodeFile)`, `:CodeFunction` + `DEFINES`/`CALLS`: Python (`ast`); JS/TS/TSX/JSX, Java, Go, HTML, CSS, Vue (`<script>`→TS) qua **Tree-sitter** khi cài dependency. Không clone repo local. |
| **Agile Studio Sync** | Story, Task, Comment, Wiki real-time | **Một phần:** Hub → `POST /ingest/agile-event`. Không phải toàn bộ thực thể Agile (vd. release, một số edge case). |
| **Processing Layer** | Chunking function/class/đoạn; embedding | **Một phần:** Agile/Wiki theo sự kiện; code GitHub theo **file** + symbol đa ngôn ngữ (Python AST + Tree-sitter); embedding **Gemini** (mục 10). |

### 2.2. Storage Strategy (Hybrid)

#### Vector (Elasticsearch)

- **Thiết kế:** Embeddings phục vụ semantic search (kNN).
- **Thực tế:** Index `second_brain_chunks` (hoặc `SECOND_BRAIN_ES_INDEX`); fields `text`, `embedding`, `project_id`, `ref`, `label`, scope/visibility/status/tags — `second_brain/es_store.py`.

#### Chuẩn embedding: Gemini (bắt buộc thiết kế)

- **Chính sách:** Toàn bộ vector trong ES do **Gemini Embedding API** sinh ra (`second_brain/embeddings.py`), không dùng OpenAI `text-embedding-3-small` làm chuẩn.
- **Model mặc định:** `text-embedding-004` (cấu hình `SECOND_BRAIN_GEMINI_EMBED_MODEL`).
- **Chiều vector:** `SECOND_BRAIN_EMBED_DIM` (mặc định **384**, truyền vào API qua `outputDimensionality` để khớp mapping `dense_vector` hiện có). Đổi dim → **tạo index mới** hoặc **reindex** (mapping ES cố định theo `dims`).
- **Biến môi trường:** `GEMINI_API_KEY` hoặc `GOOGLE_API_KEY`. Không có key: **`RuntimeError`** khi index/search — trừ khi bật **`SECOND_BRAIN_EMBEDDING_FALLBACK=1`** (vector deterministic, chỉ dev/CI, không thay thế chất lượng semantic).

Chi tiết vận hành: mục **10**.

#### Graph (Neo4j)

- **Thiết kế:** Knowledge graph Agile + traceability + (sau này) code tĩnh.
- **Thực tế:** Constraints trong `neo4j_store.py`. Quan hệ đang dùng: `HAS_STORY`, `HAS_DOCUMENT`, `HAS_COMMIT`, `ON`, `AUTHORED`, `DECIDED_IN`, và tool (`SUPERSEDES`, `DERIVED_FROM`, …).

**A. Agile & traceability**

| Mục tiêu thiết kế | Trạng thái |
|-------------------|------------|
| Nodes: Story, Task, Member, Decision, Commit | Có (wiki page = **`Document`**, không nhãn `Wiki`) |
| `(Story)-[:HAS_TASK]->(Task)` | **Có** khi Hub gửi `story_ids` trên task comment + ingest task comment |
| `(Task)-[:IMPLEMENTED_BY]->(Commit)` | **Một phần:** GitHub commit message khớp regex task id (`SECOND_BRAIN_COMMIT_TASK_PATTERN`) |
| `(Commit)-[:MODIFIES]->(File/Function)` | **Một phần:** `(Commit)-[:MODIFIES]->(:CodeFile)`; function là nút riêng `:CodeFunction` |
| `(Decision)-[:DECIDED_IN]->(Story)` | **Có** khi `brain_remember_decision` có `story_ref` |

**B. Codebase tĩnh (static analysis)**

- **Đã có:** nhãn `CodeFile`, `CodeFunction`; quan hệ `DEFINES`, `CALLS` (heuristic trong file / Tree-sitter), `MODIFIES` từ commit GitHub; Python (`ast`) + các đuôi phổ biến (React/Angular stack: `.ts`/`.tsx`/`.jsx`, v.v.) qua Tree-sitter khi cài package.
- **Chưa có:** `Module`/`Service` tự động, `IMPORTS` đồ thị, call-graph đầy đủ liên file.

#### Relational Database (MySQL)

- **Thiết kế tổng thể hệ sinh thái:** metadata trong MySQL (Agile Studio).
- **Second Brain service:** **không** host MySQL; SB chỉ Neo4j + ES. Bảng **sync state / job queue** cho SB là **mở rộng tương lai**.

---

### 2.3. Hybrid RAG

| Thành phần | Mục tiêu | Hiện tại |
|------------|----------|----------|
| Vector | Semantic | `brain_search_knowledge` → kNN ES + filter |
| Graph | Mở rộng ngữ cảnh | `brain_get_neighborhood`, `brain_query_graph` |
| Hybrid BM25 + vector | Kết hợp điểm | **Có** — `brain_search_knowledge(..., search_mode="hybrid")` |
| Orchestrator (tự chọn tool) | Một call “trả lời đủ” | **Chưa** — agent tự gọi tool |

---

### 2.4. Codebase Sync & Incremental Analysis Flow

**Đã có:** webhook push → danh sách file added/modified/removed per commit → API lấy nội dung → cập nhật Neo4j + ES (chunk/file), regex task trong message → `IMPLEMENTED_BY`.

**Chưa có:** diff cục bộ không qua API, Tree-sitter, re-embed chỉ delta theo hash nội dung (hiện ghi đè theo `ref` file), parse story key kiểu `PROJ-12` đầy đủ.

---

### 2.5. Các phần còn thiếu so với tầm nhìn sản phẩm (bổ sung)

Ngoài các mục đã nêu, các hạng mục sau **chưa có** trong hoặc ngoài repo SB nhưng cần cho “Codebase Intelligence” trọn vẹn:

| Hạng mục | Mô tả ngắn |
|----------|------------|
| **NFR / Requirement có cấu trúc** | Trích NFR từ spec (latency, volume) → lưu thực thể có kiểm chứng; hiện chỉ có text/wiki/ADR tự do. |
| **PR / CI compliance** | Quét diff so với `Decision` trong pipeline PR — **chưa**; chỉ hướng dẫn agent thủ công. |
| **Đa repo / đa branch** | Mapping project_id ↔ repo + branch mặc định; **chưa**. |
| **Observability** | Metrics ingest latency, lỗi Gemini/ES/Neo4j, rate limit; **chưa** chuẩn hoá trong service. |
| **Quota & chi phí embedding** | Budget Gemini call, batch embed, cache content-hash; **chưa**. |
| **Idempotency ingest** | Tránh double-index cùng sự kiện; **một phần** (overwrite theo `ref` ES). |
| **Phân quyền theo member** | JWT/project role trên MCP; **chưa** trong SB standalone. |
| **DR / backup đồ thị** | Neo4j backup policy; tài liệu vận hành ngoài repo SB. |

---

## 3. Codebase Intelligence Features

| Tính năng | Mục tiêu | Trạng thái |
|-----------|----------|------------|
| **Code Understanding** | Giải thích cấu trúc từ chỉ mục | Gián tiếp qua agent + repo; SB **chưa** graph symbol |
| **Impact Analysis** | Story → CALLS ngược | **Chưa** |
| **Automated Implementation** | Sinh mã theo ADR | **Chưa** tự động |
| **Architecture Visualization** | CONTAINS / IMPORTS | **Chưa** (thiếu static analysis) |

---

## 4. ADR & Traceability

- **Mục tiêu:** MADR v2.1.0; trace story/task ↔ code.
- **Thực tế:** `brain_remember_decision` đủ trường ADR; enum status **chưa** enforce trong tool. **`brain_extract_adr_from_text`** trích JSON ADR (LLM tuỳ chọn `SECOND_BRAIN_ADR_LLM_*` hoặc `SECOND_BRAIN_EXTRACT_LLM_*`).
- **Trace code ↔ Story:** **chưa** Implemented-by / MODIFIES.

---

## 5. Security & Privacy

**Thiết kế:** mã hóa truyền/tại chỗ; RBAC theo member.

**Thực tế SB:** secret ingest HTTP; MCP không JWT Agile. RBAC **mục tiêu**, chưa enforce trong process SB đơn lẻ.

---

## 6. Use Cases

| # | Kịch bản | Đích | Hiện tại |
|---|----------|------|----------|
| 6.1 | Onboarding module | Graph CONTAINS / IMPORTS | **Chưa** graph code; có wiki + search SB |
| 6.2 | Impact analysis | CALLS ngược | **Chưa** |
| 6.3 | RCA Wiki | Commit MODIFIES + Task | **Một phần** graph wiki; không Git thật |
| 6.4 | PR vs ADR | So khớp tự động | **Chưa** |
| 6.5 | Domain “vì sao Neo4j?” | Search wiki + Decision | **Có** nếu đã ingest / remember |

---

## 7. Trạng thái triển khai trong codebase (`second-brain/`)

| Hạng mục | File / vị trí | Trạng thái |
|----------|----------------|------------|
| MCP + ingest HTTP | `app.py` | Hoạt động |
| Ingest Agile | `ingest_agile.py` | Subset events |
| Neo4j | `neo4j_store.py` | Hoạt động |
| ES + kNN | `es_store.py` | Hoạt động |
| **Embedding** | **`embeddings.py`** | **Gemini Embedding API** (mặc định); fallback deterministic chỉ khi `SECOND_BRAIN_EMBEDDING_FALLBACK=1` |
| Lesson / ADR extract (LLM tuỳ chọn) | `lesson_extract.py`, `adr_extract.py` | Hoạt động |
| GitHub webhook ingest | `ingest_github.py`, `/ingest/github-webhook` | Push + PAT + map repo→project |
| Static đa ngôn ngữ | `code_static_multilang.py` → `code_static_python.py` (.py) | Trong ingest GitHub |
| Hybrid ES search | `es_store.search_hybrid` | MCP `search_mode=hybrid` |
| IMPORT graph liên file | — | **Chưa** |
| MySQL trong SB | — | **Không có** |

---

## 8. Khoảng trống & lộ trình kỹ thuật

1. **IMPORTS** / call-graph liên file đầy đủ (Tree-sitter hiện chỉ symbol + CALLS heuristic trong file).
2. Parse story key / issue link đầy đủ trong commit message (ngoài regex task id).
3. Job queue / sync state (MySQL hoặc Redis) nếu cần scale ingest.
4. ADR: validate enum trong MCP `brain_remember_decision`; workflow PR compliance tự động.
5. Auth MCP (JWT / project scope) khi expose internet.
6. **Embedding:** giám sát quota Gemini, retry/backoff, batch re-embed sau đổi model/dim.

---

## 9. Liên kết nội bộ

- Vận hành: [`../README.md`](../README.md).

---

## 10. Chuẩn Embedding — Gemini (thiết kế & vận hành)

| Mục | Giá trị / ghi chú |
|-----|-------------------|
| **API** | Google AI Gemini `embedContent` (REST), `second_brain/embeddings.py` |
| **Model mặc định** | `text-embedding-004` (`SECOND_BRAIN_GEMINI_EMBED_MODEL`) |
| **Task type** | `RETRIEVAL_DOCUMENT` (index tài liệu / chunk ingest) |
| **Chiều vector** | `SECOND_BRAIN_EMBED_DIM` (mặc định **384**) — truyền `outputDimensionality`; **phải khớp** `dense_vector.dims` trong Elasticsearch |
| **API key** | `GEMINI_API_KEY` hoặc `GOOGLE_API_KEY` |
| **Production** | **Luôn** cấu hình key Gemini — không dựa vào fallback deterministic |
| **Dev / CI không key** | `SECOND_BRAIN_EMBEDDING_FALLBACK=1` — chỉ để chạy được pipeline, **không** tương đương chất lượng tìm kiếm ngữ nghĩa |
| **Đổi dim hoặc model** | Tạo index ES mới (hoặc xóa index cũ) + **reindex** toàn bộ chunk — vector cũ không tương thích dim |

*Tài liệu này phản ánh chính sách embedding Gemini và các phần còn thiếu so với tầm nhìn Codebase Intelligence; phần implementation chi tiết nằm trong repo.*
