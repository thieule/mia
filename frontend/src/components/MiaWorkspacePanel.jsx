import { useCallback, useEffect, useState } from "react";
import { apiCenter, isApiCenterConfigured } from "../apiCenter";
import MarkdownPromptEditor from "./MarkdownPromptEditor";
import WorkspacePromptTree from "./WorkspacePromptTree";

const DEFAULT_MIA_AGENT = {
  id: "mia-",
  display_name: "",
  workspace_folder: "",
  template: "ai-tech",
  gateway_port: "",
  description: "",
};

export default function MiaWorkspacePanel() {
  const configured = isApiCenterConfigured();
  const [miaAgents, setMiaAgents] = useState([]);
  const [selectedMiaId, setSelectedMiaId] = useState(null);
  const [prompts, setPrompts] = useState([]);
  const [selectedPrompt, setSelectedPrompt] = useState(null);
  const [editorContent, setEditorContent] = useState("");
  const [editorDirty, setEditorDirty] = useState(false);
  const [loadingAgents, setLoadingAgents] = useState(false);
  const [loadingPrompts, setLoadingPrompts] = useState(false);
  const [loadingContent, setLoadingContent] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [newMia, setNewMia] = useState(DEFAULT_MIA_AGENT);
  const [createBusy, setCreateBusy] = useState(false);

  const loadMiaAgents = useCallback(async () => {
    if (!configured) return;
    setLoadingAgents(true);
    setError("");
    try {
      const res = await apiCenter.listMiaAgents();
      const rows = Array.isArray(res.db_agents) ? res.db_agents : [];
      setMiaAgents(rows);
      setSelectedMiaId((cur) => cur || rows[0]?.id || null);
    } catch (err) {
      setError(err?.message || "Không tải được danh sách Mia agents.");
    } finally {
      setLoadingAgents(false);
    }
  }, [configured]);

  const loadPrompts = useCallback(async (agentId) => {
    if (!configured || !agentId) return;
    setLoadingPrompts(true);
    setError("");
    try {
      const res = await apiCenter.listPrompts(agentId);
      setPrompts(res.prompts || []);
    } catch (err) {
      setError(err?.message || "Không tải được prompts.");
      setPrompts([]);
    } finally {
      setLoadingPrompts(false);
    }
  }, [configured]);

  useEffect(() => {
    loadMiaAgents();
  }, [loadMiaAgents]);

  useEffect(() => {
    if (!selectedMiaId) {
      setPrompts([]);
      setSelectedPrompt(null);
      setEditorContent("");
      return;
    }
    setSelectedPrompt(null);
    setEditorContent("");
    setEditorDirty(false);
    loadPrompts(selectedMiaId);
  }, [selectedMiaId, loadPrompts]);

  async function handleSelectFile(row) {
    if (!selectedMiaId || !row) return;
    if (editorDirty && !window.confirm("Bỏ thay đổi chưa lưu?")) return;
    setSelectedPrompt({ kind: row.kind, label: row.label });
    setLoadingContent(true);
    setMessage("");
    setError("");
    try {
      const res = await apiCenter.getPrompt(selectedMiaId, row.kind, row.label);
      const content = res.prompt?.content ?? "";
      setEditorContent(content);
      setEditorDirty(false);
    } catch (err) {
      setError(err?.message || "Không đọc được nội dung file.");
      setEditorContent("");
    } finally {
      setLoadingContent(false);
    }
  }

  async function handleSavePrompt() {
    if (!selectedMiaId || !selectedPrompt) return;
    setSaving(true);
    setMessage("");
    setError("");
    try {
      await apiCenter.savePrompt(selectedMiaId, {
        kind: selectedPrompt.kind,
        label: selectedPrompt.label,
        content: editorContent,
      });
      setEditorDirty(false);
      setMessage("Đã lưu prompt.");
      await loadPrompts(selectedMiaId);
    } catch (err) {
      setError(err?.message || "Lưu thất bại.");
    } finally {
      setSaving(false);
    }
  }

  async function handleCreateMia(e) {
    e.preventDefault();
    const id = newMia.id.trim().toLowerCase();
    const display_name = (newMia.display_name || id).trim();
    const workspace_folder = (newMia.workspace_folder || id.replace(/^mia-/, "")).trim();
    const gateway_port = Number(newMia.gateway_port);
    if (!id.startsWith("mia-")) {
      setError("Agent id phải bắt đầu bằng mia-");
      return;
    }
    if (!Number.isFinite(gateway_port) || gateway_port < 1024) {
      setError("gateway_port không hợp lệ.");
      return;
    }
    setCreateBusy(true);
    setError("");
    try {
      await apiCenter.createMiaAgent({
        id,
        display_name,
        workspace_folder,
        template: newMia.template || "ai-tech",
        gateway_port,
        description: newMia.description?.trim() || undefined,
      });
      setCreateOpen(false);
      setNewMia(DEFAULT_MIA_AGENT);
      setSelectedMiaId(id);
      await loadMiaAgents();
      setMessage(`Đã tạo agent ${id}. Chạy sync script để import prompt từ workspace nếu cần.`);
    } catch (err) {
      setError(err?.message || "Tạo agent thất bại.");
    } finally {
      setCreateBusy(false);
    }
  }

  if (!configured) {
    return (
      <div className="alert alert-warning border-0 shadow-sm">
        <strong>API Center chưa cấu hình.</strong> Đặt{" "}
        <code>VITE_API_CENTER_ADMIN_SECRET</code> và tuỳ chọn <code>VITE_API_CENTER_BASE</code> (mặc định{" "}
        <code>http://127.0.0.1:18881</code>) trong <code>frontend/.env.local</code>.
      </div>
    );
  }

  const selectedAgent = miaAgents.find((a) => a.id === selectedMiaId);

  return (
    <div className="mia-workspace-panel">
      {(error || message) && (
        <div className={`alert ${error ? "alert-danger" : "alert-success"} py-2 small mb-3`}>
          {error || message}
          <button
            type="button"
            className="btn-close btn-close-sm float-end"
            aria-label="Đóng"
            onClick={() => {
              setError("");
              setMessage("");
            }}
          />
        </div>
      )}

      <div className="row g-3 mia-workspace-layout">
        <div className="col-12 col-lg-2">
          <div className="card shadow-sm border-0 h-100">
            <div className="card-body p-3">
              <div className="d-flex justify-content-between align-items-center mb-2">
                <h2 className="h6 mb-0">Mia agents</h2>
                <button type="button" className="btn btn-primary btn-sm" onClick={() => setCreateOpen(true)}>
                  <i className="bi bi-plus-lg" aria-hidden />
                </button>
              </div>
              {loadingAgents && <p className="text-muted small">Đang tải…</p>}
              <div className="list-group list-group-flush agent-scroll">
                {miaAgents.length === 0 && !loadingAgents && (
                  <p className="text-muted small mb-0">Chưa có agent trong DB.</p>
                )}
                {miaAgents.map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    className={`list-group-item list-group-item-action py-2 ${selectedMiaId === a.id ? "active" : ""}`}
                    onClick={() => setSelectedMiaId(a.id)}
                  >
                    <div className="fw-semibold small">{a.display_name || a.id}</div>
                    <div className="text-muted" style={{ fontSize: "0.72rem" }}>
                      {a.id}
                      {a.gateway_port ? ` · :${a.gateway_port}` : ""}
                    </div>
                  </button>
                ))}
              </div>
              {selectedMiaId && (
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm w-100 mt-2"
                  disabled={loadingPrompts}
                  onClick={() => loadPrompts(selectedMiaId)}
                >
                  <i className="bi bi-arrow-clockwise me-1" aria-hidden />
                  Tải lại prompts
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="col-12 col-lg-3">
          <div className="card shadow-sm border-0 h-100">
            <div className="card-body p-3 d-flex flex-column" style={{ minHeight: 420 }}>
              <h2 className="h6 mb-2">Workspace prompts</h2>
              {selectedAgent && (
                <p className="text-muted small mb-2">{selectedAgent.workspace_root || selectedAgent.id}</p>
              )}
              {loadingPrompts ? (
                <p className="text-muted small">Đang tải cây file…</p>
              ) : (
                <div className="prompt-tree-scroll flex-grow-1 overflow-auto">
                  <WorkspacePromptTree prompts={prompts} selected={selectedPrompt} onSelect={handleSelectFile} />
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="col-12 col-lg-7">
          <div className="card shadow-sm border-0 h-100">
            <div className="card-body p-3 d-flex flex-column" style={{ minHeight: 420 }}>
              {selectedPrompt ? (
                <>
                  <div className="d-flex flex-wrap justify-content-between align-items-start gap-2 mb-2">
                    <div>
                      <h2 className="h6 mb-1">{selectedPrompt.label}</h2>
                      <span className="badge text-bg-light border">{selectedPrompt.kind}</span>
                      {editorDirty && <span className="badge text-bg-warning ms-1">Chưa lưu</span>}
                    </div>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={saving || loadingContent || !editorDirty}
                      onClick={handleSavePrompt}
                    >
                      {saving ? "Đang lưu…" : "Lưu"}
                    </button>
                  </div>
                  {loadingContent ? (
                    <p className="text-muted small">Đang tải nội dung…</p>
                  ) : (
                    <MarkdownPromptEditor
                      key={`${selectedPrompt.kind}::${selectedPrompt.label}`}
                      value={editorContent}
                      onChange={(v) => {
                        setEditorContent(v);
                        setEditorDirty(true);
                      }}
                      height={360}
                      placeholder="Nội dung markdown…"
                      showPromptInserts={false}
                      readOnly={saving}
                    />
                  )}
                </>
              ) : (
                <p className="text-muted small mb-0 mt-4 text-center">
                  Chọn một file trong cây thư mục để xem và chỉnh sửa.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>

      {createOpen && (
        <div className="modal-backdrop-custom" onClick={() => !createBusy && setCreateOpen(false)}>
          <div className="modal-dialog-custom modal-dialog-custom--wide" onClick={(e) => e.stopPropagation()}>
            <div className="card shadow border-0">
              <div className="card-body">
                <h2 className="h5 mb-3">Tạo Mia agent</h2>
                <form onSubmit={handleCreateMia} className="row g-3">
                  <div className="col-md-6">
                    <label className="form-label">Agent ID</label>
                    <input
                      className="form-control font-monospace"
                      placeholder="mia-demo"
                      value={newMia.id}
                      onChange={(e) => setNewMia({ ...newMia, id: e.target.value })}
                      required
                    />
                  </div>
                  <div className="col-md-6">
                    <label className="form-label">Tên hiển thị</label>
                    <input
                      className="form-control"
                      value={newMia.display_name}
                      onChange={(e) => setNewMia({ ...newMia, display_name: e.target.value })}
                    />
                  </div>
                  <div className="col-md-6">
                    <label className="form-label">Thư mục workspace</label>
                    <input
                      className="form-control font-monospace"
                      placeholder="demo"
                      value={newMia.workspace_folder}
                      onChange={(e) => setNewMia({ ...newMia, workspace_folder: e.target.value })}
                    />
                  </div>
                  <div className="col-md-6">
                    <label className="form-label">Template</label>
                    <select
                      className="form-select"
                      value={newMia.template}
                      onChange={(e) => setNewMia({ ...newMia, template: e.target.value })}
                    >
                      <option value="ai-tech">ai-tech</option>
                      <option value="ai-ba">ai-ba</option>
                    </select>
                  </div>
                  <div className="col-md-6">
                    <label className="form-label">Gateway port</label>
                    <input
                      type="number"
                      className="form-control"
                      min={1024}
                      max={65535}
                      value={newMia.gateway_port}
                      onChange={(e) => setNewMia({ ...newMia, gateway_port: e.target.value })}
                      required
                    />
                  </div>
                  <div className="col-12">
                    <label className="form-label">Mô tả (tuỳ chọn)</label>
                    <input
                      className="form-control"
                      value={newMia.description}
                      onChange={(e) => setNewMia({ ...newMia, description: e.target.value })}
                    />
                  </div>
                  <p className="col-12 small text-muted mb-0">
                    Sau khi tạo, chạy{" "}
                    <code>api-center/scripts/sync_agent_prompts_skills_from_workspace.py</code> để đồng bộ prompt từ
                    thư mục agent.
                  </p>
                  <div className="col-12 d-flex justify-content-end gap-2">
                    <button
                      type="button"
                      className="btn btn-outline-secondary"
                      disabled={createBusy}
                      onClick={() => setCreateOpen(false)}
                    >
                      Huỷ
                    </button>
                    <button type="submit" className="btn btn-primary" disabled={createBusy}>
                      {createBusy ? "Đang tạo…" : "Tạo agent"}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
