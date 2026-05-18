import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { agentChatStream, api } from "./api";
import MarkdownPromptEditor from "./components/MarkdownPromptEditor";
import MiaWorkspacePanel from "./components/MiaWorkspacePanel";
import WorkflowPage from "./components/WorkflowPage";

/** Single allowed model until multi-provider UI returns. */
const MODEL_OPTIONS = [{ value: "gemini-2.5-flash-lite", label: "Gemini 2.5 Flash Lite" }];
const ALLOWED_MODEL_VALUES = new Set(MODEL_OPTIONS.map((o) => o.value));

function normalizeModelName(name) {
  const n = typeof name === "string" ? name : "";
  return ALLOWED_MODEL_VALUES.has(n) ? n : MODEL_OPTIONS[0].value;
}

const DEFAULT_TEMPERATURE = 0.7;

const MENU_PATHS = ["/agents", "/data", "/workflow", "/setting"];

const PAGE_HEADER_BY_MENU = {
  agents: {
    title: "Agents",
    subtitle: "Manage agents and prompt versions.",
  },
  data: {
    title: "Data",
    subtitle: "Domains and indexed content.",
  },
  setting: {
    title: "Setting",
    subtitle: "Application configuration.",
  },
  workflow: {
    title: "Workflow",
    subtitle: "Thiết kế bước thực thi, AI, phê duyệt và nhánh từ chối.",
  },
};

function formatDataSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function isValidDomainUploadFile(file) {
  const name = (file?.name || "").toLowerCase();
  return name.endsWith(".pdf") || name.endsWith(".docx") || name.endsWith(".txt");
}

function formatArticleSourceType(raw) {
  const s = String(raw || "");
  if (s === "llamaindex_web") return "Web";
  if (s === "upload") return "Upload";
  if (s === "manual") return "Manual";
  return s;
}

function normalizePromptVersion(v) {
  if (!v) return null;
  return {
    ...v,
    temperature: v.temperature ?? DEFAULT_TEMPERATURE,
    model_name: normalizeModelName(v.model_name),
    is_active: Boolean(v.is_active),
    enabled_tool_ids: Array.isArray(v.enabled_tool_ids)
      ? v.enabled_tool_ids.map((x) => Number(x)).filter((n) => !Number.isNaN(n))
      : [],
  };
}

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();

  const path = location.pathname.replace(/\/$/, "") || "/";
  const activeMenu =
    path === "/data"
      ? "data"
      : path === "/setting"
        ? "setting"
        : path === "/workflow"
          ? "workflow"
          : "agents";
  const pageHeader = PAGE_HEADER_BY_MENU[activeMenu] ?? PAGE_HEADER_BY_MENU.agents;
  const [agents, setAgents] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState(null);
  const [versions, setVersions] = useState([]);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [analytics, setAnalytics] = useState([]);
  const [testRuns, setTestRuns] = useState([]);
  const [newAgent, setNewAgent] = useState({ name: "", description: "" });
  const [isAgentModalOpen, setIsAgentModalOpen] = useState(false);
  /** "lab" = prompt versions (port 8000); "mia" = workspace prompts via API Center */
  const [agentsViewTab, setAgentsViewTab] = useState("lab");
  const [editAgentModal, setEditAgentModal] = useState(null);
  const [isNewVersionOpen, setIsNewVersionOpen] = useState(false);
  const [expandedVersionId, setExpandedVersionId] = useState(null);
  const [domains, setDomains] = useState([]);
  const [selectedDomainId, setSelectedDomainId] = useState(null);
  const [domainArticles, setDomainArticles] = useState([]);
  const [newDomainName, setNewDomainName] = useState("");
  const [manualArticle, setManualArticle] = useState({ title: "", content: "" });
  const [dataMessage, setDataMessage] = useState("");
  const [dataAddPanelOpen, setDataAddPanelOpen] = useState(false);
  const [dataAddMode, setDataAddMode] = useState("upload");
  const [webIngestUrls, setWebIngestUrls] = useState("");
  const [pendingUploadFile, setPendingUploadFile] = useState(null);
  const [uploadSubmitting, setUploadSubmitting] = useState(false);
  const [manualArticleSubmitting, setManualArticleSubmitting] = useState(false);
  const [webIngestSubmitting, setWebIngestSubmitting] = useState(false);
  const [uploadDragOver, setUploadDragOver] = useState(false);
  const uploadFileInputRef = useRef(null);
  const [articleDetailView, setArticleDetailView] = useState(null);
  const [articleEdit, setArticleEdit] = useState(null);
  const [versionChatOpen, setVersionChatOpen] = useState(false);
  /** true = cửa sổ popup mở; false = chỉ hiện nút launcher góc dưới (kiểu Facebook) */
  const [versionChatExpanded, setVersionChatExpanded] = useState(true);
  const [versionChatMessages, setVersionChatMessages] = useState([]);
  const [versionChatInput, setVersionChatInput] = useState("");
  const [versionChatBusy, setVersionChatBusy] = useState(false);
  const [versionChatRunMeta, setVersionChatRunMeta] = useState(null);
  const versionChatEndRef = useRef(null);
  const [newVersion, setNewVersion] = useState({
    version_name: "v1",
    model_name: MODEL_OPTIONS[0].value,
    temperature: DEFAULT_TEMPERATURE,
    system_prompt: "",
    main_prompt: "",
    base_version_id: null,
    enabled_tool_ids: [],
  });

  const [settingsTools, setSettingsTools] = useState([]);
  const [internalCatalog, setInternalCatalog] = useState([]);
  const [settingsToolMessage, setSettingsToolMessage] = useState("");
  /** Setting: tools (MCP/API) | eval — Test Dataset (CSV) */
  const [settingsTab, setSettingsTab] = useState("tools");
  const [evalDatasets, setEvalDatasets] = useState([]);
  const [newEvalDataset, setNewEvalDataset] = useState({ name: "", description: "" });
  const [evalSettingsMessage, setEvalSettingsMessage] = useState("");
  const [evalFormModal, setEvalFormModal] = useState(null);
  const evalCsvInputRefs = useRef({});
  const [selectedPromptEvalDatasetId, setSelectedPromptEvalDatasetId] = useState("");
  const [checkDatasetBusy, setCheckDatasetBusy] = useState(false);
  const [checkPromptModalOpen, setCheckPromptModalOpen] = useState(false);
  const [checkPromptForm, setCheckPromptForm] = useState({ test_input: "", expected_output: "" });
  const [checkPromptBusy, setCheckPromptBusy] = useState(false);
  const [checkPromptResult, setCheckPromptResult] = useState(null);
  const [activatingVersionId, setActivatingVersionId] = useState(null);
  const [newMcpTool, setNewMcpTool] = useState({
    name: "",
    description: "",
    transport: "stdio",
    command: "",
    argsLine: "",
    url: "",
  });
  const [newApiTool, setNewApiTool] = useState({
    name: "",
    description: "",
    base_url: "",
    method: "GET",
  });

  const selectedDomain = domains.find((d) => d.id === selectedDomainId);

  const domainContentStats = useMemo(() => {
    const enc = new TextEncoder();
    let bytes = 0;
    for (const a of domainArticles) {
      bytes += enc.encode(a.title ?? "").length;
      bytes += enc.encode(a.content ?? "").length;
    }
    return { count: domainArticles.length, bytes };
  }, [domainArticles]);

  const versionChatAgentDisplayName = useMemo(() => {
    const n = agents.find((a) => a.id === selectedAgentId)?.name?.trim();
    return n || `Agent #${selectedAgentId ?? "?"}`;
  }, [agents, selectedAgentId]);

  useEffect(() => {
    if (!articleDetailView && !articleEdit) return;
    const onKey = (e) => {
      if (e.key === "Escape") {
        setArticleEdit(null);
        setArticleDetailView(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [articleDetailView, articleEdit]);

  useEffect(() => {
    const p = location.pathname.replace(/\/$/, "") || "/";
    if (p === "/") {
      navigate("/agents", { replace: true });
      return;
    }
    if (!MENU_PATHS.includes(p)) {
      navigate("/agents", { replace: true });
    }
  }, [location.pathname, navigate]);

  useEffect(() => {
    loadAgents();
    loadAnalytics();
    loadDomains();
    loadSettingsTools();
    loadEvalDatasets();
  }, []);

  async function loadEvalDatasets() {
    try {
      const data = await api.listEvalDatasets();
      setEvalDatasets(data);
    } catch {
      setEvalDatasets([]);
    }
  }

  async function loadSettingsTools() {
    try {
      const data = await api.listTools();
      setSettingsTools(data);
    } catch {
      setSettingsTools([]);
    }
  }

  async function loadInternalCatalog() {
    try {
      const data = await api.listInternalTools();
      setInternalCatalog(data);
    } catch {
      setInternalCatalog([]);
    }
  }

  useEffect(() => {
    if (activeMenu !== "setting") return;
    loadInternalCatalog();
  }, [activeMenu]);

  useEffect(() => {
    if (selectedAgentId) {
      loadVersions(selectedAgentId);
    }
  }, [selectedAgentId]);

  useEffect(() => {
    versionChatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [versionChatMessages]);

  useEffect(() => {
    if (!selectedAgentId) {
      setVersionChatOpen(false);
      setVersionChatExpanded(true);
      setVersionChatMessages([]);
      setVersionChatRunMeta(null);
    }
    setCheckPromptModalOpen(false);
  }, [selectedAgentId]);

  useEffect(() => {
    if (!versionChatOpen) return;
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (versionChatExpanded) setVersionChatExpanded(false);
      else setVersionChatOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [versionChatOpen, versionChatExpanded]);

  async function loadAgents() {
    const data = await api.listAgents();
    setAgents(data);
    if (!selectedAgentId && data.length > 0) setSelectedAgentId(data[0].id);
  }

  /**
   * @param {number} agentId
   * @param {{ selectVersionId?: number }} [opts] — sau kích hoạt, giữ mở đúng version đó
   */
  async function loadVersions(agentId, opts = {}) {
    const data = await api.listPromptVersions(agentId);
    const sorted = [...data].sort((a, b) => b.id - a.id);
    setVersions(sorted);
    const pick =
      opts.selectVersionId != null
        ? sorted.find((x) => x.id === opts.selectVersionId)
        : sorted[0];
    setSelectedVersion(pick ? normalizePromptVersion(pick) : null);
    setExpandedVersionId(pick?.id ?? null);
    if (pick) loadTestRuns(pick.id);
    else setTestRuns([]);
  }

  async function loadAnalytics() {
    const data = await api.analytics();
    setAnalytics(data);
  }

  async function loadTestRuns(versionId) {
    const data = await api.listTestRuns(versionId);
    setTestRuns(data);
  }

  async function loadDomains() {
    const data = await api.listDomains();
    setDomains(data);
    if (!selectedDomainId && data.length > 0) {
      setSelectedDomainId(data[0].id);
      await loadDomainArticles(data[0].id);
    }
  }

  async function loadDomainArticles(domainId) {
    const data = await api.listDomainArticles(domainId);
    setDomainArticles(data);
  }

  async function handleCreateDomain(e) {
    e.preventDefault();
    if (!newDomainName.trim()) return;
    await api.createDomain({
      name: newDomainName.trim(),
      create_index: true,
    });
    setNewDomainName("");
    await loadDomains();
    setDataMessage("Domain created successfully.");
  }

  async function handleDeleteDomain(domainId, domainName) {
    const ok = window.confirm(
      `Delete domain "${domainName}" and all indexed data in Elasticsearch? This cannot be undone.`,
    );
    if (!ok) return;
    try {
      await api.deleteDomain(domainId);
      const data = await api.listDomains();
      setDomains(data);
      setDataMessage(`Domain "${domainName}" and its data were removed.`);
      setArticleDetailView(null);
      setArticleEdit(null);
      if (selectedDomainId === domainId) {
        setSelectedDomainId(null);
        setDomainArticles([]);
        setDataAddPanelOpen(false);
        if (data.length > 0) {
          await handleSelectDomain(data[0].id);
        }
      }
    } catch (err) {
      setDataMessage(err?.message || "Cannot delete domain.");
    }
  }

  async function handleSelectDomain(domainId) {
    setSelectedDomainId(domainId);
    setDataAddPanelOpen(false);
    setDataAddMode("upload");
    setPendingUploadFile(null);
    setUploadDragOver(false);
    if (uploadFileInputRef.current) uploadFileInputRef.current.value = "";
    setArticleDetailView(null);
    setArticleEdit(null);
    await loadDomainArticles(domainId);
  }

  async function handleCreateManualArticle(e) {
    e.preventDefault();
    if (!selectedDomainId) return;
    const content = (manualArticle.content ?? "").trim();
    if (!content) {
      setDataMessage("Content cannot be empty.");
      return;
    }
    setManualArticleSubmitting(true);
    try {
      await api.createManualDomainArticle(selectedDomainId, { ...manualArticle, content });
      setManualArticle({ title: "", content: "" });
      await loadDomainArticles(selectedDomainId);
      setDataMessage("Manual article saved.");
      setDataAddPanelOpen(false);
    } catch (err) {
      setDataMessage(err?.message || "Cannot save article.");
    } finally {
      setManualArticleSubmitting(false);
    }
  }

  function handleUploadDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
    if (uploadSubmitting) return;
    e.dataTransfer.dropEffect = "copy";
  }

  function handleUploadDragEnter(e) {
    e.preventDefault();
    e.stopPropagation();
    if (uploadSubmitting) return;
    setUploadDragOver(true);
  }

  function handleUploadDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    const next = e.relatedTarget;
    if (next && e.currentTarget.contains(next)) return;
    setUploadDragOver(false);
  }

  function handleUploadDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    setUploadDragOver(false);
    if (uploadSubmitting) return;
    const f = e.dataTransfer.files?.[0];
    if (!f) return;
    if (!isValidDomainUploadFile(f)) {
      setDataMessage("Only PDF, DOCX, or TXT files are accepted.");
      return;
    }
    setPendingUploadFile(f);
  }

  async function handleUploadDomainFileSubmit() {
    if (!selectedDomainId || !pendingUploadFile) {
      setDataMessage("Select file (PDF / DOCX / TXT) and click Upload.");
      return;
    }
    setUploadSubmitting(true);
    try {
      const res = await api.uploadDomainFile(selectedDomainId, pendingUploadFile);
      await loadDomainArticles(selectedDomainId);
      setDataMessage(`Upload completed. Generated ${res.chunks} article chunk(s).`);
      setPendingUploadFile(null);
      if (uploadFileInputRef.current) uploadFileInputRef.current.value = "";
      setDataAddPanelOpen(false);
    } catch (err) {
      setDataMessage(err?.message || "Upload failed.");
    } finally {
      setUploadSubmitting(false);
    }
  }

  async function handleIngestWebUrls(e) {
    e.preventDefault();
    if (!selectedDomainId) return;
    const urls = webIngestUrls
      .split(/\n/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!urls.length) {
      setDataMessage("Enter at least one URL (http or https).");
      return;
    }
    setWebIngestSubmitting(true);
    try {
      const res = await api.ingestWebUrls(selectedDomainId, { urls });
      await loadDomainArticles(selectedDomainId);
      const errN = res.errors?.length ?? 0;
      const errPart = errN ? ` Warning: ${errN} error URL(s) (see API response).` : "";
      setDataMessage(
        `Created ${res.chunks} chunk(s) from ${res.urls_loaded} loaded page(s).${errPart}`,
      );
      setWebIngestUrls("");
      setDataAddPanelOpen(false);
    } catch (err) {
      setDataMessage(err?.message || "Cannot load content from URLs.");
    } finally {
      setWebIngestSubmitting(false);
    }
  }

  async function handleDeleteArticle(a) {
    if (!selectedDomainId || !a?.id) return;
    if (!window.confirm("Remove this article from Elasticsearch? This action cannot be undone.")) return;
    try {
      await api.deleteDomainArticle(selectedDomainId, a.id);
      if (articleDetailView?.id === a.id) setArticleDetailView(null);
      if (articleEdit?.id === a.id) setArticleEdit(null);
      await loadDomainArticles(selectedDomainId);
      setDataMessage("Removed article from index.");
    } catch (err) {
      setDataMessage(err?.message || "Cannot remove article.");
    }
  }

  function openArticleEdit(a) {
    if (!a?.id) return;
    setArticleDetailView(null);
    setArticleEdit({
      id: a.id,
      title: a.title ?? "",
      content: a.content ?? "",
      source_type: a.source_type ?? "",
      source_url: a.source_url ?? "",
    });
  }

  async function handleSaveArticleEdit(e) {
    e.preventDefault();
    if (!selectedDomainId || !articleEdit?.id) return;
    const content = (articleEdit.content ?? "").trim();
    if (!content) {
      setDataMessage("Content cannot be empty.");
      return;
    }
    try {
      await api.updateDomainArticle(selectedDomainId, articleEdit.id, {
        title: articleEdit.title?.trim() || "(Untitled)",
        content: articleEdit.content,
      });
      setArticleEdit(null);
      await loadDomainArticles(selectedDomainId);
      setDataMessage("Article updated.");
    } catch (err) {
      setDataMessage(err?.message || "Cannot update article.");
    }
  }

  async function handleCreateAgent(e) {
    e.preventDefault();
    await api.createAgent(newAgent);
    setNewAgent({ name: "", description: "" });
    setIsAgentModalOpen(false);
    await loadAgents();
  }

  async function handleUpdateAgent(e) {
    e.preventDefault();
    if (!editAgentModal) return;
    const name = (editAgentModal.name ?? "").trim();
    if (name.length < 2) return;
    try {
      await api.updateAgent(editAgentModal.id, {
        name,
        description: editAgentModal.description ?? "",
      });
      setEditAgentModal(null);
      await loadAgents();
    } catch (err) {
      window.alert(err?.message || "Cannot update agent.");
    }
  }

  async function handleCreateVersion(e) {
    e.preventDefault();
    if (!selectedAgentId) return;
    const payload = {
      ...newVersion,
      prompt_template: "",
    };
    await api.createPromptVersion(selectedAgentId, payload);
    setNewVersion({
      ...newVersion,
      version_name: `${newVersion.version_name}-next`,
      base_version_id: null,
      enabled_tool_ids: [],
    });
    setIsNewVersionOpen(false);
    await loadVersions(selectedAgentId);
    await loadAnalytics();
  }

  async function handleSaveVersion() {
    if (!selectedVersion) return;
    await api.updatePromptVersion(selectedVersion.id, {
      version_name: selectedVersion.version_name,
      model_name: selectedVersion.model_name,
      temperature: Number(selectedVersion.temperature ?? DEFAULT_TEMPERATURE),
      system_prompt: selectedVersion.system_prompt,
      main_prompt: selectedVersion.main_prompt,
      prompt_template: "",
      latest_score: selectedVersion.latest_score || 0,
      enabled_tool_ids: selectedVersion.enabled_tool_ids || [],
    });
    await loadVersions(selectedAgentId);
  }

  async function handleCloneVersion() {
    if (!selectedVersion) return;
    const name = prompt("New version name:", `${selectedVersion.version_name}-next`);
    if (!name) return;
    await api.clonePromptVersion(selectedVersion.id, { new_version_name: name });
    await loadVersions(selectedAgentId);
    await loadAnalytics();
  }

  async function handleActivatePromptVersion(versionId) {
    if (!selectedAgentId || activatingVersionId != null) return;
    setActivatingVersionId(versionId);
    try {
      await api.activatePromptVersion(versionId);
      await loadVersions(selectedAgentId, { selectVersionId: versionId });
    } catch (err) {
      window.alert(err?.message || "Không kích hoạt được phiên bản này.");
    } finally {
      setActivatingVersionId(null);
    }
  }

  async function handleVersionChatSubmit(e) {
    e.preventDefault();
    if (!selectedAgentId || versionChatBusy) return;
    const text = versionChatInput.trim();
    if (!text) return;
    setVersionChatInput("");
    const assistantId = `a-${Date.now()}`;
    setVersionChatMessages((m) => [
      ...m,
      { id: `u-${Date.now()}`, role: "user", text },
      { id: assistantId, role: "assistant", text: "" },
    ]);
    setVersionChatBusy(true);
    setVersionChatRunMeta(null);
    try {
      for await (const ev of agentChatStream(selectedAgentId, {
        message: text,
        input_json: {},
        workflow_key: "wf01",
      })) {
        if (ev.text) {
          setVersionChatMessages((prev) =>
            prev.map((x) => (x.id === assistantId ? { ...x, text: x.text + ev.text } : x)),
          );
        }
        if (ev.run_id != null && ev.state != null && ev.done !== true && !ev.text) {
          setVersionChatRunMeta({ runId: ev.run_id, state: ev.state });
        }
        if (ev.done) {
          setVersionChatRunMeta({ runId: ev.run_id, state: ev.state });
        }
        if (ev.error) {
          setVersionChatMessages((prev) =>
            prev.map((x) =>
              x.id === assistantId ? { ...x, text: (x.text || "") + `\n\n[Error] ${ev.error}` } : x,
            ),
          );
        }
      }
    } catch (err) {
      setVersionChatMessages((prev) =>
        prev.map((x) =>
          x.id === assistantId ? { ...x, text: `[Error] ${err?.message || String(err)}` } : x,
        ),
      );
    } finally {
      setVersionChatBusy(false);
    }
  }

  function handleSelectVersion(version) {
    if (expandedVersionId === version.id) {
      setExpandedVersionId(null);
      setSelectedVersion(null);
      setTestRuns([]);
      return;
    }
    setExpandedVersionId(version.id);
    setSelectedVersion(normalizePromptVersion(version));
    loadTestRuns(version.id);
  }

  function toggleNewVersionTool(toolId) {
    setNewVersion((prev) => {
      const cur = prev.enabled_tool_ids || [];
      const s = new Set(cur);
      if (s.has(toolId)) s.delete(toolId);
      else s.add(toolId);
      return { ...prev, enabled_tool_ids: [...s] };
    });
  }

  function toggleSelectedVersionTool(toolId) {
    setSelectedVersion((prev) => {
      if (!prev) return prev;
      const cur = prev.enabled_tool_ids || [];
      const s = new Set(cur);
      if (s.has(toolId)) s.delete(toolId);
      else s.add(toolId);
      return { ...prev, enabled_tool_ids: [...s] };
    });
  }

  async function handleAddMcpTool(e) {
    e.preventDefault();
    setSettingsToolMessage("");
    const name = newMcpTool.name.trim();
    if (!name) {
      setSettingsToolMessage("Enter MCP tool name.");
      return;
    }
    let config;
    if (newMcpTool.transport === "stdio") {
      if (!newMcpTool.command.trim()) {
        setSettingsToolMessage("MCP stdio: enter command.");
        return;
      }
      const args = newMcpTool.argsLine.trim()
        ? newMcpTool.argsLine.trim().split(/\s+/)
        : [];
      config = { transport: "stdio", command: newMcpTool.command.trim(), args };
    } else if (!newMcpTool.url.trim()) {
      setSettingsToolMessage("MCP SSE: enter URL.");
      return;
    } else {
      config = { transport: "sse", url: newMcpTool.url.trim() };
    }
    try {
      await api.createTool({
        kind: "mcp",
        name,
        description: newMcpTool.description.trim(),
        config,
        enabled: true,
      });
      setNewMcpTool({
        name: "",
        description: "",
        transport: "stdio",
        command: "",
        argsLine: "",
        url: "",
      });
      await loadSettingsTools();
      setSettingsToolMessage("Added MCP tool.");
    } catch (err) {
      setSettingsToolMessage(err?.message || "Cannot add MCP tool.");
    }
  }

  async function handleAddApiTool(e) {
    e.preventDefault();
    setSettingsToolMessage("");
    const name = newApiTool.name.trim();
    if (!name || !newApiTool.base_url.trim()) {
      setSettingsToolMessage("API: enter name and base URL.");
      return;
    }
    try {
      await api.createTool({
        kind: "api_endpoint",
        name,
        description: newApiTool.description.trim(),
        config: {
          base_url: newApiTool.base_url.trim(),
          method: newApiTool.method || "GET",
          headers: {},
        },
        enabled: true,
      });
      setNewApiTool({ name: "", description: "", base_url: "", method: "GET" });
      await loadSettingsTools();
      setSettingsToolMessage("Added API endpoint.");
    } catch (err) {
      setSettingsToolMessage(err?.message || "Cannot add API endpoint.");
    }
  }

  async function handleDeleteTool(toolId) {
    if (!window.confirm("Delete this tool? Prompt version can still keep old id — check again.")) return;
    setSettingsToolMessage("");
    try {
      await api.deleteTool(toolId);
      await loadSettingsTools();
      await loadInternalCatalog();
      setSettingsToolMessage("Deleted.");
    } catch (err) {
      setSettingsToolMessage(err?.message || "Cannot delete tool.");
    }
  }

  async function handleImportInternalTool(internalId) {
    setSettingsToolMessage("");
    try {
      await api.importInternalTools({ ids: [internalId] });
      await loadSettingsTools();
      await loadInternalCatalog();
      setSettingsToolMessage("Imported internal tool into the registry.");
    } catch (err) {
      setSettingsToolMessage(err?.message || "Import failed.");
    }
  }

  async function handleCreateEvalDataset(e) {
    e.preventDefault();
    const name = newEvalDataset.name.trim();
    if (name.length < 2) return;
    setEvalSettingsMessage("");
    try {
      await api.createEvalDataset({
        name,
        description: (newEvalDataset.description || "").trim(),
      });
      setNewEvalDataset({ name: "", description: "" });
      await loadEvalDatasets();
      setEvalSettingsMessage("Created category (dataset).");
    } catch (err) {
      setEvalSettingsMessage(err?.message || "Cannot create dataset.");
    }
  }

  async function handleUpdateEvalDatasetModal(e) {
    e.preventDefault();
    if (!evalFormModal?.id) return;
    setEvalSettingsMessage("");
    try {
      await api.updateEvalDataset(evalFormModal.id, {
        name: evalFormModal.name.trim(),
        description: (evalFormModal.description || "").trim(),
      });
      setEvalFormModal(null);
      await loadEvalDatasets();
      setEvalSettingsMessage("Updated name/description.");
    } catch (err) {
      setEvalSettingsMessage(err?.message || "Cannot update dataset.");
    }
  }

  async function handleDeleteEvalDataset(datasetId) {
    if (!window.confirm("Delete this dataset and all test rows imported?")) return;
    setEvalSettingsMessage("");
    try {
      await api.deleteEvalDataset(datasetId);
      await loadEvalDatasets();
      if (String(selectedPromptEvalDatasetId) === String(datasetId)) {
        setSelectedPromptEvalDatasetId("");
      }
      setEvalSettingsMessage("Deleted dataset.");
    } catch (err) {
      setEvalSettingsMessage(err?.message || "Cannot delete dataset.");
    }
  }

  function triggerEvalCsvImport(datasetId) {
    const el = evalCsvInputRefs.current[datasetId];
    if (el) el.click();
  }

  async function handleEvalCsvFile(datasetId, e) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setEvalSettingsMessage("");
    try {
      const res = await api.importEvalDatasetCsv(datasetId, f);
      await loadEvalDatasets();
      setEvalSettingsMessage(`Imported ${res.rows_imported} rows (CSV replaces all old rows in category).`);
    } catch (err) {
      setEvalSettingsMessage(err?.message || "Import CSV failed.");
    }
  }

  async function handleRunDatasetDeepEval() {
    if (!selectedVersion || !selectedPromptEvalDatasetId) return;
    const id = Number(selectedPromptEvalDatasetId);
    if (!Number.isFinite(id)) return;
    setCheckDatasetBusy(true);
    try {
      const res = await api.checkPromptDataset(selectedVersion.id, { eval_dataset_id: id });
      await loadVersions(selectedAgentId);
      await loadTestRuns(selectedVersion.id);
      await loadAnalytics();
      window.alert(
        `DeepEval: ${res.cases_run} case · average score ${res.average_score} · ${res.eval_dataset_name} (${res.evaluation_method}).`,
      );
    } catch (err) {
      window.alert(err?.message || "Run DeepEval on dataset failed.");
    } finally {
      setCheckDatasetBusy(false);
    }
  }

  async function handleCheckPromptSingle(e) {
    e.preventDefault();
    if (!selectedVersion) return;
    const test_input = checkPromptForm.test_input.trim();
    const expected_output = checkPromptForm.expected_output.trim();
    if (!test_input || !expected_output) return;
    setCheckPromptBusy(true);
    setCheckPromptResult(null);
    try {
      const res = await api.checkPrompt(selectedVersion.id, { test_input, expected_output });
      setCheckPromptResult({ ok: true, ...res });
      await loadVersions(selectedAgentId);
      await loadTestRuns(selectedVersion.id);
      await loadAnalytics();
    } catch (err) {
      setCheckPromptResult({ ok: false, error: err?.message || "Check failed." });
    } finally {
      setCheckPromptBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <nav className="navbar navbar-expand-lg app-top-nav sticky-top">
        <div className="container-fluid px-3 px-md-4">
          <span className="navbar-brand fw-semibold mb-0">Agent Factory Demo</span>
          <div className="navbar-nav flex-row gap-2">
            <NavLink
              to="/agents"
              className={({ isActive }) =>
                `btn btn-sm ${isActive ? "btn-light text-primary fw-semibold" : "btn-outline-light"}`
              }
            >
              <i className="bi bi-people me-1" aria-hidden={true} />
              Agents
            </NavLink>
            <NavLink
              to="/data"
              className={({ isActive }) =>
                `btn btn-sm ${isActive ? "btn-light text-primary fw-semibold" : "btn-outline-light"}`
              }
            >
              <i className="bi bi-database me-1" aria-hidden={true} />
              Data
            </NavLink>
            <NavLink
              to="/workflow"
              className={({ isActive }) =>
                `btn btn-sm ${isActive ? "btn-light text-primary fw-semibold" : "btn-outline-light"}`
              }
            >
              <i className="bi bi-diagram-3 me-1" aria-hidden={true} />
              Workflow
            </NavLink>
            <NavLink
              to="/setting"
              className={({ isActive }) =>
                `btn btn-sm ${isActive ? "btn-light text-primary fw-semibold" : "btn-outline-light"}`
              }
            >
              <i className="bi bi-gear me-1" aria-hidden={true} />
              Setting
            </NavLink>
          </div>
        </div>
      </nav>

      <header className="app-page-header">
        <div className="container-fluid px-3 px-md-4">
          <h1 className="app-page-header-title">{pageHeader.title}</h1>
          <p className="app-page-header-subtitle">{pageHeader.subtitle}</p>
        </div>
      </header>

      <div className="container-fluid py-4 px-3 px-md-4 app-page-main">
        {activeMenu === "agents" && (
          <>
            <ul className="nav nav-pills gap-2 mb-3 agents-view-tabs">
              <li className="nav-item">
                <button
                  type="button"
                  className={`nav-link ${agentsViewTab === "lab" ? "active" : ""}`}
                  onClick={() => setAgentsViewTab("lab")}
                >
                  Prompt Lab
                </button>
              </li>
              <li className="nav-item">
                <button
                  type="button"
                  className={`nav-link ${agentsViewTab === "mia" ? "active" : ""}`}
                  onClick={() => setAgentsViewTab("mia")}
                >
                  Mia workspace
                </button>
              </li>
            </ul>
            {agentsViewTab === "mia" ? (
              <MiaWorkspacePanel />
            ) : (
        <div className="row g-4">
          <div className="col-12 col-lg-3">
            <div className="card shadow-sm border-0">
              <div className="card-body">
                <div className="d-flex justify-content-between align-items-center mb-3">
                  <h2 className="h5 mb-0">Agents</h2>
                  <button className="btn btn-primary btn-sm" onClick={() => setIsAgentModalOpen(true)}>
                    <i className="bi bi-plus-lg me-1" aria-hidden={true} />
                    New Agent
                  </button>
                </div>

                <div className="list-group agent-scroll">
                  {agents.length === 0 && (
                    <div className="text-muted small py-2">No agents yet. Create one to start.</div>
                  )}
                  {agents.map((agent) => (
                    <div
                      key={agent.id}
                      className={`list-group-item list-group-item-action d-flex align-items-center gap-2 ${
                        agent.id === selectedAgentId ? "active" : ""
                      }`}
                    >
                      <button
                        type="button"
                        className="btn btn-link flex-grow-1 text-start text-decoration-none p-0 border-0 agent-list-select"
                        onClick={() => setSelectedAgentId(agent.id)}
                      >
                        <div className="d-flex align-items-start gap-2">
                          <i className="bi bi-person-badge fs-5 opacity-75" aria-hidden={true} />
                          <div>
                            <div className="fw-semibold">{agent.name}</div>
                            <div className="small opacity-75">Agent #{agent.id}</div>
                          </div>
                        </div>
                      </button>
                      <button
                        type="button"
                        className={`btn btn-sm ${
                          agent.id === selectedAgentId ? "btn-outline-light" : "btn-outline-secondary"
                        }`}
                        title="Edit name and description"
                        aria-label={`Edit agent ${agent.name}`}
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          setEditAgentModal({
                            id: agent.id,
                            name: agent.name,
                            description: agent.description ?? "",
                          });
                        }}
                      >
                        <i className="bi bi-pencil" aria-hidden={true} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="col-12 col-lg-9">
            <div className="card shadow-sm border-0 mb-4">
              <div className="card-body">
                <div className="d-flex justify-content-between align-items-center mb-3">
                  <h2 className="h5 mb-0">Create Prompt Version</h2>
                  <button
                    className="btn btn-success btn-sm"
                    type="button"
                    disabled={!selectedAgentId}
                    onClick={() => setIsNewVersionOpen((prev) => !prev)}
                  >
                    {isNewVersionOpen ? (
                      <>
                        <i className="bi bi-x-lg me-1" aria-hidden={true} />
                        Close
                      </>
                    ) : (
                      <>
                        <i className="bi bi-file-earmark-plus me-1" aria-hidden={true} />
                        New Version
                      </>
                    )}
                  </button>
                </div>

                {isNewVersionOpen && (
                  <form onSubmit={handleCreateVersion} className="row g-3">
                    <div className="col-md-3">
                      <label className="form-label">Version Name</label>
                      <input
                        className="form-control"
                        placeholder="v1"
                        value={newVersion.version_name}
                        onChange={(e) => setNewVersion({ ...newVersion, version_name: e.target.value })}
                      />
                    </div>
                    <div className="col-md-3">
                      <label className="form-label">AI Model</label>
                      <select
                        className="form-select"
                        value={newVersion.model_name}
                        onChange={(e) => setNewVersion({ ...newVersion, model_name: e.target.value })}
                      >
                        {MODEL_OPTIONS.map((m) => (
                          <option key={m.value} value={m.value}>
                            {m.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="col-md-3">
                      <label className="form-label d-flex justify-content-between align-items-baseline gap-2 mb-1">
                        <span>Temperature</span>
                        <span className="text-muted small font-monospace">
                          {Math.min(1, Number(newVersion.temperature) || 0).toFixed(2)}
                        </span>
                      </label>
                      <input
                        type="range"
                        className="form-range"
                        min={0}
                        max={1}
                        step={0.05}
                        value={Math.min(1, Number(newVersion.temperature) || 0)}
                        onChange={(e) =>
                          setNewVersion({ ...newVersion, temperature: parseFloat(e.target.value) })
                        }
                      />
                      <div className="d-flex justify-content-between text-muted small">
                        <span>0</span>
                        <span>1</span>
                      </div>
                    </div>
                    <div className="col-md-3">
                      <label className="form-label">Base Version (Optional)</label>
                      <select
                        className="form-select"
                        value={newVersion.base_version_id ?? ""}
                        onChange={(e) =>
                          setNewVersion({
                            ...newVersion,
                            base_version_id: e.target.value ? Number(e.target.value) : null,
                          })
                        }
                      >
                        <option value="">None (new root)</option>
                        {versions.map((v) => (
                          <option key={v.id} value={v.id}>
                            {v.version_name} (#{v.id})
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="col-12">
                      <label className="form-label">System Prompt</label>
                      <MarkdownPromptEditor
                        height={200}
                        placeholder="Define behavior and constraints..."
                        value={newVersion.system_prompt}
                        onChange={(v) => setNewVersion({ ...newVersion, system_prompt: v })}
                      />
                    </div>
                    <div className="col-12">
                      <label className="form-label">Main Prompt</label>
                      <MarkdownPromptEditor
                        height={280}
                        placeholder="Write main task prompt..."
                        value={newVersion.main_prompt}
                        onChange={(v) => setNewVersion({ ...newVersion, main_prompt: v })}
                        ragDomains={domains}
                      />
                    </div>
                    <div className="col-12">
                      <label className="form-label">Tools</label>
                      <p className="small text-muted mb-2">
                        Optional. Define tools under Setting, then select which ones this version may use.
                      </p>
                      {settingsTools.filter((t) => t.enabled).length === 0 ? (
                        <p className="small text-muted mb-0">No tools yet. Add MCP or API entries on the Setting page.</p>
                      ) : (
                        <div className="d-flex flex-wrap gap-3">
                          {settingsTools
                            .filter((t) => t.enabled)
                            .map((t) => (
                              <div key={t.id} className="form-check">
                                <input
                                  className="form-check-input"
                                  type="checkbox"
                                  id={`nv-tool-${t.id}`}
                                  checked={(newVersion.enabled_tool_ids || []).includes(t.id)}
                                  onChange={() => toggleNewVersionTool(t.id)}
                                />
                                <label className="form-check-label small" htmlFor={`nv-tool-${t.id}`}>
                                  <span className="fw-medium">{t.name}</span>
                                  <span className="text-muted ms-1">
                                    ({t.kind === "mcp" ? "MCP" : "API"})
                                  </span>
                                </label>
                              </div>
                            ))}
                        </div>
                      )}
                    </div>
                    <div className="col-12">
                      <button className="btn btn-success" type="submit" disabled={!selectedAgentId}>
                        <i className="bi bi-check2-circle me-1" aria-hidden={true} />
                        Create Version
                      </button>
                    </div>
                  </form>
                )}
              </div>
            </div>

            <div className="card shadow-sm border-0 mb-4">
              <div className="card-body">
                <div className="d-flex flex-wrap gap-2 justify-content-between align-items-center mb-3">
                  <h2 className="h5 mb-0">Prompt Editor & Testing</h2>
                </div>

                <>
                  <div className="accordion mb-3">
                    {versions.map((v) => {
                      const isOpen = expandedVersionId === v.id;
                      return (
                        <div className="accordion-item" key={v.id}>
                          <h2 className="accordion-header">
                            <button
                              type="button"
                              className={`accordion-button version-accordion-btn ${isOpen ? "version-selected" : "collapsed"}`}
                              onClick={() => handleSelectVersion(v)}
                            >
                              <div className="d-flex align-items-start gap-2 w-100">
                                <i className="bi bi-tag-fill text-primary mt-1" aria-hidden={true} />
                                <div className="d-flex flex-column flex-grow-1 min-w-0">
                                  <span className="fw-semibold">{v.version_name}</span>
                                  <small className="text-muted">
                                    Score {v.latest_score}
                                    {v.parent_version_id ? ` | from #${v.parent_version_id}` : " | root"}
                                  </small>
                                </div>
                                <div
                                  className="d-flex align-items-center gap-2 flex-shrink-0 ms-1"
                                  onClick={(e) => e.stopPropagation()}
                                  onKeyDown={(e) => e.stopPropagation()}
                                  role="presentation"
                                >
                                  {v.is_active ? (
                                    <span className="badge text-bg-success rounded-pill">Đang dùng</span>
                                  ) : (
                                    <button
                                      type="button"
                                      className="btn btn-sm btn-outline-primary"
                                      disabled={activatingVersionId != null}
                                      aria-busy={activatingVersionId === v.id}
                                      onClick={() => handleActivatePromptVersion(v.id)}
                                    >
                                      {activatingVersionId === v.id ? (
                                        <>
                                          <span
                                            className="spinner-border spinner-border-sm me-1"
                                            aria-hidden={true}
                                          />
                                          Đang bật…
                                        </>
                                      ) : (
                                        <>
                                          <i className="bi bi-check2-circle me-1" aria-hidden={true} />
                                          Kích hoạt
                                        </>
                                      )}
                                    </button>
                                  )}
                                </div>
                              </div>
                            </button>
                          </h2>
                          {isOpen && selectedVersion?.id === v.id && (
                            <div className="accordion-body">
                              <div className="mt-2">
                                <div className="row g-3 mb-3">
                                  <div className="col-md-4">
                                    <label className="form-label">Version Name</label>
                                    <input
                                      className="form-control"
                                      value={selectedVersion.version_name}
                                      onChange={(e) =>
                                        setSelectedVersion({
                                          ...selectedVersion,
                                          version_name: e.target.value,
                                        })
                                      }
                                    />
                                  </div>
                                  <div className="col-md-4">
                                    <label className="form-label">AI Model</label>
                                    <select
                                      className="form-select"
                                      value={selectedVersion.model_name}
                                      onChange={(e) =>
                                        setSelectedVersion({
                                          ...selectedVersion,
                                          model_name: e.target.value,
                                        })
                                      }
                                    >
                                      {MODEL_OPTIONS.map((m) => (
                                        <option key={m.value} value={m.value}>
                                          {m.label}
                                        </option>
                                      ))}
                                    </select>
                                  </div>
                                  <div className="col-md-4">
                                    <label className="form-label d-flex justify-content-between align-items-baseline gap-2 mb-1">
                                      <span>Temperature</span>
                                      <span className="text-muted small font-monospace">
                                        {Math.min(
                                          1,
                                          Number(selectedVersion.temperature ?? DEFAULT_TEMPERATURE) || 0
                                        ).toFixed(2)}
                                      </span>
                                    </label>
                                    <input
                                      type="range"
                                      className="form-range"
                                      min={0}
                                      max={1}
                                      step={0.05}
                                      value={Math.min(
                                        1,
                                        Number(selectedVersion.temperature ?? DEFAULT_TEMPERATURE) || 0
                                      )}
                                      onChange={(e) =>
                                        setSelectedVersion({
                                          ...selectedVersion,
                                          temperature: parseFloat(e.target.value),
                                        })
                                      }
                                    />
                                    <div className="d-flex justify-content-between text-muted small">
                                      <span>0</span>
                                      <span>1</span>
                                    </div>
                                  </div>
                                  <div className="col-12">
                                    <label className="form-label">System Prompt</label>
                                    <MarkdownPromptEditor
                                      height={200}
                                      value={selectedVersion.system_prompt}
                                      onChange={(v) =>
                                        setSelectedVersion({
                                          ...selectedVersion,
                                          system_prompt: v,
                                        })
                                      }
                                    />
                                  </div>
                                  <div className="col-12">
                                    <label className="form-label">Main Prompt</label>
                                    <MarkdownPromptEditor
                                      height={280}
                                      value={selectedVersion.main_prompt}
                                      onChange={(v) =>
                                        setSelectedVersion({
                                          ...selectedVersion,
                                          main_prompt: v,
                                        })
                                      }
                                      ragDomains={domains}
                                    />
                                  </div>
                                  <div className="col-12">
                                    <label className="form-label">Tools</label>
                                    <p className="small text-muted mb-2">
                                      Tools enabled for this prompt version (configured under Setting).
                                    </p>
                                    {settingsTools.filter((t) => t.enabled).length === 0 ? (
                                      <p className="small text-muted mb-0">
                                        No tools available. Add them on the Setting page.
                                      </p>
                                    ) : (
                                      <div className="d-flex flex-wrap gap-3">
                                        {settingsTools
                                          .filter((t) => t.enabled)
                                          .map((t) => (
                                            <div key={t.id} className="form-check">
                                              <input
                                                className="form-check-input"
                                                type="checkbox"
                                                id={`sv-tool-${t.id}`}
                                                checked={(selectedVersion.enabled_tool_ids || []).includes(
                                                  t.id,
                                                )}
                                                onChange={() => toggleSelectedVersionTool(t.id)}
                                              />
                                              <label
                                                className="form-check-label small"
                                                htmlFor={`sv-tool-${t.id}`}
                                              >
                                                <span className="fw-medium">{t.name}</span>
                                                <span className="text-muted ms-1">
                                                  ({t.kind === "mcp" ? "MCP" : "API"})
                                                </span>
                                              </label>
                                            </div>
                                          ))}
                                      </div>
                                    )}
                                  </div>
                                  <div className="col-12">
                                    <div className="d-flex flex-wrap gap-2 align-items-center mb-2">
                                      <button
                                        type="button"
                                        className="btn btn-dark"
                                        onClick={() => {
                                          setCheckPromptModalOpen(true);
                                          setCheckPromptResult(null);
                                        }}
                                        disabled={!selectedVersion}
                                      >
                                        <i className="bi bi-shield-check me-1" aria-hidden={true} />
                                        Check Prompt
                                      </button>
                                      <div className="d-flex flex-wrap gap-2 align-items-center">
                                        <select
                                          className="form-select form-select-sm test-dataset-select"
                                          style={{ minWidth: "10rem" }}
                                          value={selectedPromptEvalDatasetId}
                                          onChange={(e) => setSelectedPromptEvalDatasetId(e.target.value)}
                                          disabled={!selectedVersion || evalDatasets.length === 0}
                                          aria-label="Test dataset"
                                        >
                                          <option value="">Test dataset: chọn…</option>
                                          {evalDatasets.map((d) => (
                                            <option key={d.id} value={d.id}>
                                              {d.name} ({d.row_count} cases)
                                            </option>
                                          ))}
                                        </select>
                                        <button
                                          type="button"
                                          className="btn btn-outline-dark btn-sm"
                                          disabled={
                                            !selectedVersion ||
                                            !selectedPromptEvalDatasetId ||
                                            checkDatasetBusy
                                          }
                                          onClick={handleRunDatasetDeepEval}
                                        >
                                          {checkDatasetBusy ? (
                                            <>
                                              <span
                                                className="spinner-border spinner-border-sm me-1"
                                                role="status"
                                                aria-hidden={true}
                                              />
                                              Đang chạy…
                                            </>
                                          ) : (
                                            <>
                                              <i className="bi bi-collection-play me-1" aria-hidden={true} />
                                              Chạy DeepEval (dataset)
                                            </>
                                          )}
                                        </button>
                                      </div>
                                    </div>
                                    <p className="small text-muted mb-2">
                                      Dataset CSV tạo tại{" "}
                                      <NavLink to="/setting" className="link-secondary">
                                        Setting → Test Dataset
                                      </NavLink>
                                      . Cột: <code className="small">test_input</code>,{" "}
                                      <code className="small">expected_output</code> (hoặc input / expected).
                                    </p>
                                    <div className="d-flex gap-2 flex-wrap align-items-center">
                                      <button className="btn btn-primary" onClick={handleSaveVersion}>
                                        <i className="bi bi-save me-1" aria-hidden={true} />
                                        Save Version
                                      </button>
                                      <button
                                        type="button"
                                        className="btn btn-outline-primary"
                                        onClick={handleCloneVersion}
                                        disabled={!selectedVersion}
                                      >
                                        <i className="bi bi-files me-1" aria-hidden={true} />
                                        Clone Version
                                      </button>
                                      <button
                                        type="button"
                                        className="btn btn-outline-success"
                                        onClick={() => {
                                          setVersionChatOpen(true);
                                          setVersionChatExpanded(true);
                                        }}
                                        disabled={!selectedAgentId}
                                        title="Chat với AI qua agent — dùng prompt đang active (stream)"
                                      >
                                        <i className="bi bi-chat-dots me-1" aria-hidden={true} />
                                        Chat
                                      </button>
                                    </div>
                                  </div>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>

                </>
              </div>
            </div>

          </div>
        </div>
            )}
          </>
        )}

        {activeMenu === "data" && (
          <div className="row g-4">
            <div className="col-12 col-lg-3">
              <div className="card shadow-sm border-0">
                <div className="card-body">
                  <div className="d-flex justify-content-between align-items-center mb-3">
                    <h2 className="h5 mb-0">Domain Management</h2>
                    <span className="badge text-bg-light border">Total: {domains.length}</span>
                  </div>
                  <form onSubmit={handleCreateDomain} className="mb-3">
                    <div className="d-flex gap-2 mb-2">
                      <input
                        className="form-control"
                        placeholder="e.g. banking, insurance..."
                        value={newDomainName}
                        onChange={(e) => setNewDomainName(e.target.value)}
                      />
                      <button className="btn btn-primary" type="submit">
                        <i className="bi bi-folder-plus me-1" aria-hidden={true} />
                        Create
                      </button>
                    </div>
                  </form>
                  <div className="small text-muted mb-2">
                    Each domain has its own content. Select a domain to manage articles.
                  </div>
                  <div className="list-group">
                    {domains.map((d) => (
                      <div
                        key={d.id}
                        className={`list-group-item list-group-item-action d-flex align-items-center gap-2 ${selectedDomainId === d.id ? "active" : ""}`}
                      >
                        <button
                          type="button"
                          className="btn btn-link flex-grow-1 text-start text-decoration-none p-0 border-0 domain-list-select"
                          onClick={() => handleSelectDomain(d.id)}
                        >
                          <div className="d-flex align-items-start gap-2">
                            <i className="bi bi-folder2 fs-5 opacity-75" aria-hidden={true} />
                            <div className="fw-semibold">{d.name}</div>
                          </div>
                        </button>
                        <button
                          type="button"
                          className={`btn btn-sm ${selectedDomainId === d.id ? "btn-outline-light" : "btn-outline-danger"}`}
                          title="Delete domain and all its data"
                          aria-label={`Delete domain ${d.name}`}
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            handleDeleteDomain(d.id, d.name);
                          }}
                        >
                          <i className="bi bi-trash" aria-hidden={true} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
            <div className="col-12 col-lg-9">
              {!selectedDomainId || !selectedDomain ? (
                <div className="card shadow-sm border-0">
                  <div className="card-body py-5 text-center text-muted">
                    <i className="bi bi-folder2-open display-6 d-block mb-3 opacity-50" aria-hidden={true} />
                    <p className="mb-0">Select a domain on the left to view details, statistics, and articles.</p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="card shadow-sm border-0 mb-4">
                    <div className="card-body">
                      <div className="d-flex flex-wrap justify-content-between align-items-start gap-2 mb-4">
                        <div>
                          <h2 className="h4 mb-0">{selectedDomain.name}</h2>
                        </div>
                        {!dataAddPanelOpen && (
                          <button
                            type="button"
                            className="btn btn-primary"
                            onClick={() => {
                              setDataAddPanelOpen(true);
                              setDataAddMode("upload");
                            }}
                          >
                            <i className="bi bi-plus-lg me-1" aria-hidden={true} />
                            Add data
                          </button>
                        )}
                      </div>

                      <div className="row g-3 mb-2">
                        <div className="col-6 col-md-4">
                          <div className="border rounded-3 p-3 h-100 bg-light">
                            <div className="small text-muted text-uppercase fw-semibold kpi-label">Articles</div>
                            <div className="fs-3 fw-bold mt-1">{domainContentStats.count}</div>
                          </div>
                        </div>
                        <div className="col-6 col-md-4">
                          <div className="border rounded-3 p-3 h-100 bg-light">
                            <div className="small text-muted text-uppercase fw-semibold kpi-label">Total data size</div>
                            <div className="fs-3 fw-bold mt-1">{formatDataSize(domainContentStats.bytes)}</div>
                          </div>
                        </div>
                      </div>
                      <p className="small text-muted mb-0">
                        Total data size combines all article titles and body text for this domain.
                      </p>

                      {dataAddPanelOpen && (
                        <div className="border rounded-3 p-3 mt-4 bg-white">
                          <div className="d-flex justify-content-between align-items-center mb-3">
                            <span className="fw-semibold">Add data</span>
                            <button
                              type="button"
                              className="btn btn-sm btn-outline-secondary"
                              onClick={() => setDataAddPanelOpen(false)}
                              aria-label="Close add data panel"
                            >
                              <i className="bi bi-x-lg" aria-hidden={true} />
                            </button>
                          </div>
                          <div className="btn-group mb-3" role="group" aria-label="Add data mode">
                            <button
                              type="button"
                              className={`btn btn-sm ${dataAddMode === "upload" ? "btn-primary" : "btn-outline-primary"}`}
                              disabled={uploadSubmitting || manualArticleSubmitting || webIngestSubmitting}
                              onClick={() => setDataAddMode("upload")}
                            >
                              <i className="bi bi-cloud-upload me-1" aria-hidden={true} />
                              Upload file
                            </button>
                            <button
                              type="button"
                              className={`btn btn-sm ${dataAddMode === "manual" ? "btn-primary" : "btn-outline-primary"}`}
                              disabled={uploadSubmitting || manualArticleSubmitting || webIngestSubmitting}
                              onClick={() => setDataAddMode("manual")}
                            >
                              <i className="bi bi-pencil-square me-1" aria-hidden={true} />
                              Manual article
                            </button>
                            <button
                              type="button"
                              className={`btn btn-sm ${dataAddMode === "weburl" ? "btn-primary" : "btn-outline-primary"}`}
                              disabled={uploadSubmitting || manualArticleSubmitting || webIngestSubmitting}
                              onClick={() => setDataAddMode("weburl")}
                              title="Load content from public URLs"
                            >
                              <i className="bi bi-link-45deg me-1" aria-hidden={true} />
                              From URL
                            </button>
                          </div>

                          {dataAddMode === "upload" && (
                            <div className="upload-data-panel">
                              <label className="form-label mb-2" htmlFor="domain-upload-file-input">
                                File (PDF / DOCX / TXT)
                              </label>
                              <div
                                className={`upload-dropzone ${uploadDragOver ? "upload-dropzone--active" : ""} ${
                                  uploadSubmitting ? "upload-dropzone--disabled" : ""
                                }`}
                                onDragEnter={handleUploadDragEnter}
                                onDragLeave={handleUploadDragLeave}
                                onDragOver={handleUploadDragOver}
                                onDrop={handleUploadDrop}
                              >
                                <input
                                  ref={uploadFileInputRef}
                                  id="domain-upload-file-input"
                                  className="d-none"
                                  type="file"
                                  accept=".pdf,.docx,.txt"
                                  disabled={uploadSubmitting}
                                  onChange={(e) => {
                                    const f = e.target.files?.[0] ?? null;
                                    if (f && !isValidDomainUploadFile(f)) {
                                      setDataMessage("Only PDF, DOCX, and TXT files are accepted.");
                                      if (uploadFileInputRef.current) uploadFileInputRef.current.value = "";
                                      setPendingUploadFile(null);
                                      return;
                                    }
                                    setPendingUploadFile(f);
                                  }}
                                />
                                <label
                                  htmlFor="domain-upload-file-input"
                                  className="upload-dropzone-label d-block text-secondary"
                                >
                                  <span className="d-block mb-2" aria-hidden={true}>
                                    <i className="bi bi-cloud-arrow-up fs-2" />
                                  </span>
                                  <span className="d-block fw-medium text-body">
                                    Drag and drop file here
                                  </span>
                                  <span className="d-block small mt-1">
                                    or click to select from your machine · PDF, DOCX, TXT
                                  </span>
                                </label>
                              </div>

                              {pendingUploadFile ? (
                                <p className="small text-muted mt-3 mb-0">
                                  Selected:{" "}
                                  <strong className="text-body">{pendingUploadFile.name}</strong>
                                </p>
                              ) : null}

                              <div className="upload-actions d-flex flex-wrap gap-2 align-items-center">
                                <button
                                  type="button"
                                  className="btn btn-success px-4"
                                  disabled={uploadSubmitting || !pendingUploadFile || !selectedDomainId}
                                  onClick={() => handleUploadDomainFileSubmit()}
                                >
                                  {uploadSubmitting ? (
                                    <>
                                      <span
                                        className="spinner-border spinner-border-sm me-2"
                                        role="status"
                                        aria-hidden={true}
                                      />
                                      Uploading…
                                    </>
                                  ) : (
                                    <>
                                      <i className="bi bi-cloud-upload me-2" aria-hidden={true} />
                                      Upload
                                    </>
                                  )}
                                </button>
                              </div>

                              <p className="form-text mt-3 mb-0">
                                AI will split the document, generate titles, and save content for this
                                domain.
                              </p>
                            </div>
                          )}

                          {dataAddMode === "manual" && (
                            <form onSubmit={handleCreateManualArticle} className="row g-3">
                              <div className="col-12">
                                <label className="form-label">Title</label>
                                <input
                                  className="form-control"
                                  value={manualArticle.title}
                                  onChange={(e) => setManualArticle({ ...manualArticle, title: e.target.value })}
                                  required
                                  disabled={manualArticleSubmitting}
                                />
                              </div>
                              <div className="col-12">
                                <label className="form-label">Content (Markdown)</label>
                                <MarkdownPromptEditor
                                  height={280}
                                  placeholder="Viết nội dung — định dạng giống trình soạn prompt (in đậm, tiêu đề, danh sách, code…)"
                                  value={manualArticle.content}
                                  onChange={(v) => setManualArticle({ ...manualArticle, content: v })}
                                  showPromptInserts={false}
                                  readOnly={manualArticleSubmitting}
                                />
                              </div>
                              <div className="col-12">
                                <button
                                  className="btn btn-success px-4"
                                  type="submit"
                                  disabled={manualArticleSubmitting || !selectedDomainId}
                                >
                                  {manualArticleSubmitting ? (
                                    <>
                                      <span
                                        className="spinner-border spinner-border-sm me-2"
                                        role="status"
                                        aria-hidden={true}
                                      />
                                      Saving…
                                    </>
                                  ) : (
                                    <>
                                      <i className="bi bi-journal-plus me-2" aria-hidden={true} />
                                      Save article
                                    </>
                                  )}
                                </button>
                              </div>
                            </form>
                          )}

                          {dataAddMode === "weburl" && (
                            <form onSubmit={handleIngestWebUrls} className="row g-3">
                              <div className="col-12">
                                <label className="form-label">Public URLs (one per line)</label>
                                <textarea
                                  className="form-control font-monospace small"
                                  rows={5}
                                  placeholder="https://example.com/page&#10;https://..."
                                  value={webIngestUrls}
                                  onChange={(e) => setWebIngestUrls(e.target.value)}
                                  disabled={webIngestSubmitting}
                                />
                                <div className="form-text">
                                  System loads HTML, splits into chunks, and enriches like upload file.
                                </div>
                              </div>
                              <div className="col-12">
                                <button
                                  className="btn btn-success px-4"
                                  type="submit"
                                  disabled={webIngestSubmitting || !selectedDomainId}
                                >
                                  {webIngestSubmitting ? (
                                    <>
                                      <span
                                        className="spinner-border spinner-border-sm me-2"
                                        role="status"
                                        aria-hidden={true}
                                      />
                                      Processing…
                                    </>
                                  ) : (
                                    <>
                                      <i className="bi bi-cloud-download me-2" aria-hidden={true} />
                                      Add to domain
                                    </>
                                  )}
                                </button>
                              </div>
                            </form>
                          )}
                        </div>
                      )}

                      {dataMessage && <div className="alert alert-info mt-3 mb-0">{dataMessage}</div>}
                    </div>
                  </div>

                  <div className="card shadow-sm border-0">
                    <div className="card-body">
                      <div className="d-flex justify-content-between align-items-center mb-3">
                        <h2 className="h5 mb-0">Articles</h2>
                        <span className="badge text-bg-light border">{domainContentStats.count} total</span>
                      </div>
                      {domainArticles.length === 0 ? (
                        <p className="text-muted small mb-0">
                          No articles yet. Use Add data to upload a file, add from public URLs, or create one manually.
                        </p>
                      ) : (
                        <div className="table-responsive">
                          <table className="table table-sm align-middle">
                            <thead>
                              <tr>
                                <th>ID</th>
                                <th>Title</th>
                                <th>Source</th>
                                <th className="text-end">Actions</th>
                              </tr>
                            </thead>
                            <tbody>
                              {domainArticles.map((a) => (
                                <tr key={a.id}>
                                  <td className="text-muted small text-break">{a.id}</td>
                                  <td>{a.title}</td>
                                  <td>{formatArticleSourceType(a.source_type)}</td>
                                  <td className="text-end">
                                    <div className="btn-group btn-group-sm" role="group">
                                      <button
                                        type="button"
                                        className="btn btn-outline-primary"
                                        onClick={() => setArticleDetailView(a)}
                                      >
                                        <i className="bi bi-eye me-1" aria-hidden={true} />
                                        View
                                      </button>
                                      <button
                                        type="button"
                                        className="btn btn-outline-secondary"
                                        onClick={() => openArticleEdit(a)}
                                      >
                                        <i className="bi bi-pencil me-1" aria-hidden={true} />
                                        Edit
                                      </button>
                                      <button
                                        type="button"
                                        className="btn btn-outline-danger"
                                        onClick={() => handleDeleteArticle(a)}
                                      >
                                        <i className="bi bi-trash me-1" aria-hidden={true} />
                                        Delete
                                      </button>
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        {activeMenu === "setting" && (
          <div className="row g-4">
            <div className="col-12">
              <ul className="nav nav-pills gap-2 mb-2 flex-wrap setting-subnav-pills">
                <li className="nav-item">
                  <button
                    type="button"
                    className={`nav-link rounded-pill px-3 ${settingsTab === "tools" ? "active" : ""}`}
                    onClick={() => setSettingsTab("tools")}
                  >
                    Tools &amp; registry
                  </button>
                </li>
                <li className="nav-item">
                  <button
                    type="button"
                    className={`nav-link rounded-pill px-3 ${settingsTab === "eval" ? "active" : ""}`}
                    onClick={() => {
                      setSettingsTab("eval");
                      loadEvalDatasets();
                    }}
                  >
                    Test Dataset
                  </button>
                </li>
              </ul>
            </div>
            {settingsTab === "tools" && (
              <>
            <div className="col-12 col-lg-6">
              <div className="card shadow-sm border-0 h-100">
                <div className="card-body">
                  <h2 className="h6 mb-3">Add MCP tool</h2>
                  <p className="small text-muted mb-3">
                    Stdio: command + optional space-separated args. SSE: endpoint URL for remote MCP.
                  </p>
                  <form onSubmit={handleAddMcpTool} className="row g-2">
                    <div className="col-12">
                      <label className="form-label small mb-0">Name</label>
                      <input
                        className="form-control form-control-sm"
                        value={newMcpTool.name}
                        onChange={(e) => setNewMcpTool({ ...newMcpTool, name: e.target.value })}
                        required
                      />
                    </div>
                    <div className="col-12">
                      <label className="form-label small mb-0">Description</label>
                      <input
                        className="form-control form-control-sm"
                        value={newMcpTool.description}
                        onChange={(e) => setNewMcpTool({ ...newMcpTool, description: e.target.value })}
                      />
                    </div>
                    <div className="col-12">
                      <label className="form-label small mb-0">Transport</label>
                      <select
                        className="form-select form-select-sm"
                        value={newMcpTool.transport}
                        onChange={(e) => setNewMcpTool({ ...newMcpTool, transport: e.target.value })}
                      >
                        <option value="stdio">stdio (local command)</option>
                        <option value="sse">SSE (remote URL)</option>
                      </select>
                    </div>
                    {newMcpTool.transport === "stdio" ? (
                      <>
                        <div className="col-12">
                          <label className="form-label small mb-0">Command</label>
                          <input
                            className="form-control form-control-sm font-monospace"
                            placeholder="npx"
                            value={newMcpTool.command}
                            onChange={(e) => setNewMcpTool({ ...newMcpTool, command: e.target.value })}
                          />
                        </div>
                        <div className="col-12">
                          <label className="form-label small mb-0">Args (space-separated)</label>
                          <input
                            className="form-control form-control-sm font-monospace"
                            placeholder="-y @modelcontextprotocol/server-filesystem /tmp"
                            value={newMcpTool.argsLine}
                            onChange={(e) => setNewMcpTool({ ...newMcpTool, argsLine: e.target.value })}
                          />
                        </div>
                      </>
                    ) : (
                      <div className="col-12">
                        <label className="form-label small mb-0">SSE URL</label>
                        <input
                          className="form-control form-control-sm font-monospace"
                          placeholder="https://..."
                          value={newMcpTool.url}
                          onChange={(e) => setNewMcpTool({ ...newMcpTool, url: e.target.value })}
                        />
                      </div>
                    )}
                    <div className="col-12 mt-2">
                      <button className="btn btn-primary btn-sm" type="submit">
                        Add MCP tool
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            </div>
            <div className="col-12 col-lg-6">
              <div className="card shadow-sm border-0 h-100">
                <div className="card-body">
                  <h2 className="h6 mb-3">Add HTTP API endpoint</h2>
                  <p className="small text-muted mb-3">Base URL for calling your service (headers can be extended later).</p>
                  <form onSubmit={handleAddApiTool} className="row g-2">
                    <div className="col-12">
                      <label className="form-label small mb-0">Name</label>
                      <input
                        className="form-control form-control-sm"
                        value={newApiTool.name}
                        onChange={(e) => setNewApiTool({ ...newApiTool, name: e.target.value })}
                        required
                      />
                    </div>
                    <div className="col-12">
                      <label className="form-label small mb-0">Description</label>
                      <input
                        className="form-control form-control-sm"
                        value={newApiTool.description}
                        onChange={(e) => setNewApiTool({ ...newApiTool, description: e.target.value })}
                      />
                    </div>
                    <div className="col-12">
                      <label className="form-label small mb-0">Base URL</label>
                      <input
                        className="form-control form-control-sm font-monospace"
                        placeholder="https://api.example.com/v1"
                        value={newApiTool.base_url}
                        onChange={(e) => setNewApiTool({ ...newApiTool, base_url: e.target.value })}
                        required
                      />
                    </div>
                    <div className="col-12">
                      <label className="form-label small mb-0">Method</label>
                      <select
                        className="form-select form-select-sm"
                        value={newApiTool.method}
                        onChange={(e) => setNewApiTool({ ...newApiTool, method: e.target.value })}
                      >
                        {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="col-12 mt-2">
                      <button className="btn btn-primary btn-sm" type="submit">
                        Add API endpoint
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            </div>
            <div className="col-12">
              <div className="card shadow-sm border-0">
                <div className="card-body">
                  <h2 className="h6 mb-2">Internal tools (bundled)</h2>
                  <p className="small text-muted mb-3">
                    Defined in Python under{" "}
                    <code className="small">runtime/src/tools/internal/builtin/</code> (metadata +{" "}
                    <code className="small">invoke</code> logic). Agent calls these directly; backend only reads the catalog for Settings. Import to register next to your MCP/API tools —
                    they then appear in Agents → prompt version tool picker.
                  </p>
                  {internalCatalog.length === 0 ? (
                    <p className="text-muted small mb-0">No internal tools defined or catalog failed to load.</p>
                  ) : (
                    <div className="table-responsive">
                      <table className="table table-sm align-middle">
                        <thead>
                          <tr>
                            <th>ID</th>
                            <th>Name</th>
                            <th>Kind</th>
                            <th>Summary</th>
                            <th>Status</th>
                            <th className="text-end">Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {internalCatalog.map((row) => {
                            const cfg = row.config || {};
                            const summary =
                              row.kind === "mcp"
                                ? cfg.transport === "sse"
                                  ? String(cfg.url || "")
                                  : [cfg.command, ...(cfg.args || [])].filter(Boolean).join(" ")
                                : `${cfg.method || "GET"} ${cfg.base_url || ""}`;
                            return (
                              <tr key={row.id}>
                                <td className="font-monospace small">{row.id}</td>
                                <td className="fw-medium">{row.name}</td>
                                <td>
                                  <span className="badge text-bg-light border">
                                    {row.kind === "mcp" ? "MCP" : "API"}
                                  </span>
                                </td>
                                <td className="small text-muted text-break font-monospace">{summary}</td>
                                <td>
                                  {row.imported ? (
                                    <span className="badge text-bg-success">Imported #{row.tool_definition_id}</span>
                                  ) : (
                                    <span className="badge text-bg-secondary">Not imported</span>
                                  )}
                                </td>
                                <td className="text-end">
                                  <button
                                    type="button"
                                    className="btn btn-primary btn-sm"
                                    disabled={row.imported}
                                    onClick={() => handleImportInternalTool(row.id)}
                                  >
                                    Import
                                  </button>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            </div>
            <div className="col-12">
              <div className="card shadow-sm border-0">
                <div className="card-body">
                  <h2 className="h6 mb-3">Registered tools</h2>
                  {settingsToolMessage ? (
                    <div className="alert alert-info py-2 small mb-3">{settingsToolMessage}</div>
                  ) : null}
                  {settingsTools.length === 0 ? (
                    <p className="text-muted small mb-0">No tools yet. Use the forms above.</p>
                  ) : (
                    <div className="table-responsive">
                      <table className="table table-sm align-middle">
                        <thead>
                          <tr>
                            <th>Source</th>
                            <th>Kind</th>
                            <th>Name</th>
                            <th>Summary</th>
                            <th className="text-end">Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {settingsTools.map((t) => {
                            const cfg = t.config || {};
                            let summary = "";
                            if (t.kind === "mcp") {
                              summary =
                                cfg.transport === "sse"
                                  ? String(cfg.url || "")
                                  : [cfg.command, ...(cfg.args || [])].filter(Boolean).join(" ");
                            } else {
                              summary = `${cfg.method || "GET"} ${cfg.base_url || ""}`;
                            }
                            return (
                              <tr key={t.id}>
                                <td>
                                  {t.internal_ref ? (
                                    <span className="badge text-bg-info text-dark">Internal</span>
                                  ) : (
                                    <span className="badge text-bg-light border">External</span>
                                  )}
                                </td>
                                <td>
                                  <span className="badge text-bg-light border">
                                    {t.kind === "mcp" ? "MCP" : "API"}
                                  </span>
                                </td>
                                <td className="fw-medium">{t.name}</td>
                                <td className="small text-muted text-break font-monospace">{summary}</td>
                                <td className="text-end">
                                  <button
                                    type="button"
                                    className="btn btn-outline-danger btn-sm"
                                    onClick={() => handleDeleteTool(t.id)}
                                  >
                                    Delete
                                  </button>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            </div>
              </>
            )}
            {settingsTab === "eval" && (
              <div className="col-12 col-lg-6">
                <div className="card shadow-sm border-0 h-100">
                  <div className="card-body">
                    <h2 className="h6 mb-3">Test Dataset</h2>
                    {evalSettingsMessage ? (
                      <div className="alert alert-info py-2 small mb-3">{evalSettingsMessage}</div>
                    ) : null}
                    <form onSubmit={handleCreateEvalDataset} className="row g-2">
                      <div className="col-12">
                        <label className="form-label small mb-0">Name category</label>
                        <input
                          className="form-control form-control-sm"
                          placeholder="example: golden-regression-v1"
                          value={newEvalDataset.name}
                          onChange={(e) => setNewEvalDataset({ ...newEvalDataset, name: e.target.value })}
                          required
                          minLength={2}
                        />
                      </div>
                      <div className="col-12">
                        <label className="form-label small mb-0">Description (optional)</label>
                        <input
                          className="form-control form-control-sm"
                          value={newEvalDataset.description}
                          onChange={(e) => setNewEvalDataset({ ...newEvalDataset, description: e.target.value })}
                        />
                      </div>
                      <div className="col-12 mt-2">
                        <button className="btn btn-primary btn-sm" type="submit">
                          Create category
                        </button>
                      </div>
                    </form>
                    {evalDatasets.length === 0 ? (
                      <p className="text-muted small mb-0 mt-3">No dataset. Create category then click Import CSV.</p>
                    ) : (
                      <div className="table-responsive mt-3">
                        <table className="table table-sm align-middle">
                          <thead>
                            <tr>
                              <th>Category</th>
                              <th>Cases</th>
                              <th>Description</th>
                              <th className="text-end">Actions</th>
                            </tr>
                          </thead>
                          <tbody>
                            {evalDatasets.map((d) => (
                              <tr key={d.id}>
                                <td className="fw-medium">{d.name}</td>
                                <td>{d.row_count}</td>
                                <td className="small text-muted text-break">{d.description || "—"}</td>
                                <td className="text-end text-nowrap">
                                  <input
                                    type="file"
                                    accept=".csv,text/csv"
                                    className="d-none"
                                    ref={(el) => {
                                      evalCsvInputRefs.current[d.id] = el;
                                    }}
                                    onChange={(e) => handleEvalCsvFile(d.id, e)}
                                  />
                                  <button
                                    type="button"
                                    className="btn btn-outline-primary btn-sm me-1"
                                    onClick={() => triggerEvalCsvImport(d.id)}
                                  >
                                    Import CSV
                                  </button>
                                  <button
                                    type="button"
                                    className="btn btn-outline-secondary btn-sm me-1"
                                    onClick={() =>
                                      setEvalFormModal({
                                        id: d.id,
                                        name: d.name,
                                        description: d.description || "",
                                      })
                                    }
                                  >
                                    Edit
                                  </button>
                                  <button
                                    type="button"
                                    className="btn btn-outline-danger btn-sm"
                                    onClick={() => handleDeleteEvalDataset(d.id)}
                                  >
                                    Delete
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {activeMenu === "workflow" && <WorkflowPage />}
      </div>

      {evalFormModal && (
        <div className="modal-backdrop-custom" onClick={() => setEvalFormModal(null)}>
          <div className="modal-dialog-custom" onClick={(e) => e.stopPropagation()}>
            <div className="card shadow border-0">
              <div className="card-body">
                <h2 className="h5 mb-3">Edit dataset</h2>
                <form onSubmit={handleUpdateEvalDatasetModal} className="row g-3">
                  <div className="col-12">
                    <label className="form-label">Name category</label>
                    <input
                      className="form-control"
                      value={evalFormModal.name}
                      onChange={(e) => setEvalFormModal({ ...evalFormModal, name: e.target.value })}
                      required
                      minLength={2}
                    />
                  </div>
                  <div className="col-12">
                    <label className="form-label">Mô tả</label>
                    <input
                      className="form-control"
                      value={evalFormModal.description}
                      onChange={(e) => setEvalFormModal({ ...evalFormModal, description: e.target.value })}
                    />
                  </div>
                  <div className="col-12 d-flex justify-content-end gap-2">
                    <button type="button" className="btn btn-outline-secondary" onClick={() => setEvalFormModal(null)}>
                      Hủy
                    </button>
                    <button type="submit" className="btn btn-primary">
                      Lưu
                    </button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        </div>
      )}

      {checkPromptModalOpen && selectedVersion && (
        <div className="modal-backdrop-custom" onClick={() => setCheckPromptModalOpen(false)}>
          <div className="modal-dialog-custom modal-lg" onClick={(e) => e.stopPropagation()}>
            <div className="card shadow border-0">
              <div className="card-body">
                <h2 className="h5 mb-3">Check Prompt (DeepEval — một case)</h2>
                <form onSubmit={handleCheckPromptSingle} className="row g-3">
                  <div className="col-12">
                    <label className="form-label">test_input</label>
                    <textarea
                      className="form-control font-monospace small"
                      rows={4}
                      value={checkPromptForm.test_input}
                      onChange={(e) => setCheckPromptForm({ ...checkPromptForm, test_input: e.target.value })}
                      required
                    />
                  </div>
                  <div className="col-12">
                    <label className="form-label">expected_output</label>
                    <textarea
                      className="form-control font-monospace small"
                      rows={4}
                      value={checkPromptForm.expected_output}
                      onChange={(e) => setCheckPromptForm({ ...checkPromptForm, expected_output: e.target.value })}
                      required
                    />
                  </div>
                  {checkPromptResult && (
                    <div className="col-12">
                      {checkPromptResult.ok === false ? (
                        <div className="alert alert-danger small mb-0 py-2">{checkPromptResult.error}</div>
                      ) : (
                        <div className="alert alert-success small mb-0 py-2">
                          Score: <strong>{checkPromptResult.score}</strong> · {checkPromptResult.evaluation_method}
                        </div>
                      )}
                    </div>
                  )}
                  <div className="col-12 d-flex justify-content-end gap-2">
                    <button
                      type="button"
                      className="btn btn-outline-secondary"
                      onClick={() => setCheckPromptModalOpen(false)}
                    >
                      Đóng
                    </button>
                    <button type="submit" className="btn btn-dark" disabled={checkPromptBusy}>
                      {checkPromptBusy ? (
                        <>
                          <span className="spinner-border spinner-border-sm me-2" aria-hidden={true} />
                          Đang chạy…
                        </>
                      ) : (
                        "Chạy DeepEval"
                      )}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        </div>
      )}

      {articleDetailView && (
        <div className="modal-backdrop-custom" onClick={() => setArticleDetailView(null)}>
          <div
            className="modal-dialog-custom modal-dialog-article"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="article-detail-title"
          >
            <div className="card shadow border-0">
              <div className="card-body">
                <div className="d-flex justify-content-between align-items-start gap-2 mb-2">
                  <h2 className="h5 mb-0" id="article-detail-title">
                    {articleDetailView.title || "(No title)"}
                  </h2>
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-secondary"
                    onClick={() => setArticleDetailView(null)}
                    aria-label="Close"
                  >
                    <i className="bi bi-x-lg" aria-hidden={true} />
                  </button>
                </div>
                <p className="small text-muted mb-3">
                  <span className="me-2">ID: {articleDetailView.id}</span>
                  <span className="me-2">·</span>
                  <span>Source: {formatArticleSourceType(articleDetailView.source_type)}</span>
                  {articleDetailView.source_url ? (
                    <>
                      <span className="me-2">·</span>
                      <a href={articleDetailView.source_url} target="_blank" rel="noreferrer">
                        {articleDetailView.source_url}
                      </a>
                    </>
                  ) : null}
                  {articleDetailView.indexed_at && (
                    <>
                      <span className="me-2">·</span>
                      <span>Indexed: {articleDetailView.indexed_at}</span>
                    </>
                  )}
                </p>
                {(articleDetailView.enrichment_summary ||
                  articleDetailView.enrichment_questions ||
                  articleDetailView.enrichment_keywords) && (
                  <div className="small border rounded p-3 mb-3 bg-white">
                    {articleDetailView.enrichment_summary ? (
                      <p className="mb-2">
                        <strong className="text-muted">Summary</strong>
                        <br />
                        {articleDetailView.enrichment_summary}
                      </p>
                    ) : null}
                    {articleDetailView.enrichment_questions ? (
                      <p className="mb-2">
                        <strong className="text-muted">Questions</strong>
                        <br />
                        <span className="text-break" style={{ whiteSpace: "pre-wrap" }}>
                          {articleDetailView.enrichment_questions}
                        </span>
                      </p>
                    ) : null}
                    {articleDetailView.enrichment_keywords ? (
                      <p className="mb-0">
                        <strong className="text-muted">Keywords</strong>
                        <br />
                        {articleDetailView.enrichment_keywords}
                      </p>
                    ) : null}
                  </div>
                )}
                <div className="article-modal-body border rounded p-3 bg-light">{articleDetailView.content || "—"}</div>
                <div className="d-flex justify-content-end gap-2 mt-3 flex-wrap">
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-secondary"
                    onClick={() => openArticleEdit(articleDetailView)}
                  >
                    <i className="bi bi-pencil me-1" aria-hidden={true} />
                    Edit
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-danger"
                    onClick={() => handleDeleteArticle(articleDetailView)}
                  >
                    <i className="bi bi-trash me-1" aria-hidden={true} />
                    Delete from index
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {articleEdit && (
        <div className="modal-backdrop-custom" onClick={() => setArticleEdit(null)}>
          <div
            className="modal-dialog-custom modal-dialog-article"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="article-edit-title"
          >
            <div className="card shadow border-0">
              <div className="card-body">
                <div className="d-flex justify-content-between align-items-start gap-2 mb-3">
                  <h2 className="h5 mb-0" id="article-edit-title">
                    Edit article
                  </h2>
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-secondary"
                    onClick={() => setArticleEdit(null)}
                    aria-label="Close"
                  >
                    <i className="bi bi-x-lg" aria-hidden={true} />
                  </button>
                </div>
                <p className="small text-muted mb-3">
                  ID: <span className="text-break">{articleEdit.id}</span>
                  {articleEdit.source_type ? (
                    <>
                      <span className="me-2"> · </span>
                      Source: {formatArticleSourceType(articleEdit.source_type)}
                    </>
                  ) : null}
                  {articleEdit.source_url ? (
                    <>
                      <br />
                      <a href={articleEdit.source_url} target="_blank" rel="noreferrer" className="small">
                        {articleEdit.source_url}
                      </a>
                    </>
                  ) : null}
                </p>
                <form onSubmit={handleSaveArticleEdit} className="row g-3">
                  <div className="col-12">
                    <label className="form-label">Title</label>
                    <input
                      className="form-control"
                      value={articleEdit.title}
                      onChange={(e) => setArticleEdit({ ...articleEdit, title: e.target.value })}
                      minLength={2}
                      required
                    />
                  </div>
                  <div className="col-12">
                    <label className="form-label">Content (Markdown)</label>
                    <MarkdownPromptEditor
                      key={articleEdit.id}
                      height={280}
                      placeholder="Content…"
                      value={articleEdit.content}
                      onChange={(v) => setArticleEdit({ ...articleEdit, content: v })}
                      showPromptInserts={false}
                    />
                  </div>
                  <div className="col-12 d-flex justify-content-end gap-2">
                    <button type="button" className="btn btn-outline-secondary" onClick={() => setArticleEdit(null)}>
                      Cancel
                    </button>
                    <button type="submit" className="btn btn-primary">
                      <i className="bi bi-check-lg me-1" aria-hidden={true} />
                      Save
                    </button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        </div>
      )}

      {versionChatOpen && selectedAgentId && (
        <div className="version-chat-fb-root" aria-live="polite">
          {versionChatExpanded && (
            <div className="version-chat-popup">
              <div className="version-chat-popup-header">
                <div className="d-flex align-items-start justify-content-between gap-2">
                  <div className="min-w-0">
                    <div className="fw-semibold version-chat-popup-title text-truncate">
                      Chat with {versionChatAgentDisplayName}
                    </div>
                    <div className="version-chat-popup-sub text-white-50 small text-truncate mt-1">
                      {selectedVersion?.version_name
                        ? `${selectedVersion.version_name} · prompt đang active`
                        : "Prompt đang active của agent"}
                    </div>
                    {versionChatRunMeta?.run_id && (
                      <div className="text-white-50 small font-monospace mt-1">
                        {versionChatRunMeta.run_id} · {versionChatRunMeta.state}
                      </div>
                    )}
                  </div>
                  <div className="d-flex align-items-center gap-1 flex-shrink-0">
                    <button
                      type="button"
                      className="btn btn-sm text-white version-chat-header-btn"
                      onClick={() => setVersionChatExpanded(false)}
                      title="Minimize"
                      aria-label="Minimize"
                    >
                      <i className="bi bi-dash-lg" aria-hidden={true} />
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm text-white version-chat-header-btn"
                      onClick={() => setVersionChatOpen(false)}
                      title="Đóng"
                      aria-label="Đóng chat"
                    >
                      <i className="bi bi-x-lg" aria-hidden={true} />
                    </button>
                  </div>
                </div>
              </div>
              <div className="version-chat-popup-body">
                {versionChatMessages.length === 0 ? (
                  <p className="small text-muted mb-0 py-1">
                    Input message below to test prompt via agent stream.
                  </p>
                ) : (
                  versionChatMessages.map((m) => {
                    const showAssistantLoading =
                      m.role === "assistant" && !m.text && versionChatBusy;
                    return (
                      <div
                        key={m.id}
                        className={`mb-2 ${m.role === "user" ? "text-end" : "text-start"}`}
                      >
                        <div
                          className={`d-inline-block text-start rounded-4 px-3 py-2 version-chat-bubble ${
                            m.role === "user" ? "bg-primary text-white" : "bg-white border shadow-sm"
                          } ${showAssistantLoading ? "version-chat-bubble--loading" : ""}`}
                        >
                          <div className={`small mb-1 ${m.role === "user" ? "opacity-75" : "text-muted"}`}>
                            {m.role === "user" ? "You" : "Assistant"}
                          </div>
                          {showAssistantLoading ? (
                            <div
                              className="version-chat-typing d-flex align-items-center gap-2 flex-wrap"
                              aria-busy="true"
                              aria-label="Creating response"
                            >
                              <span
                                className="spinner-border spinner-border-sm text-primary"
                                role="status"
                              />
                              <span className="version-chat-typing-dots" aria-hidden="true">
                                <span>.</span>
                                <span>.</span>
                                <span>.</span>
                              </span>
                              <span className="text-muted small">Creating response</span>
                            </div>
                          ) : (
                            <div className="version-chat-text">{m.text}</div>
                          )}
                        </div>
                      </div>
                    );
                  })
                )}
                <div ref={versionChatEndRef} />
              </div>
              <div className="version-chat-popup-footer border-top bg-white p-2">
                <form className="d-flex gap-2 align-items-end" onSubmit={handleVersionChatSubmit}>
                  <textarea
                    className="form-control form-control-sm version-chat-input"
                    rows={2}
                    placeholder="Enter message… (Enter to send, Shift+Enter for new line)"
                    value={versionChatInput}
                    onChange={(e) => setVersionChatInput(e.target.value)}
                    disabled={versionChatBusy}
                    onKeyDown={(e) => {
                      if (e.key !== "Enter" || e.shiftKey) return;
                      if (e.nativeEvent.isComposing) return;
                      e.preventDefault();
                      e.currentTarget.form?.requestSubmit();
                    }}
                  />
                  <button
                    type="submit"
                    className="btn btn-primary rounded-circle version-chat-send"
                    disabled={versionChatBusy || !versionChatInput.trim()}
                    title="Send"
                  >
                    {versionChatBusy ? (
                      <span className="spinner-border spinner-border-sm" aria-hidden={true} />
                    ) : (
                      <i className="bi bi-send-fill" aria-hidden={true} />
                    )}
                  </button>
                </form>
              </div>
            </div>
          )}
          <button
            type="button"
            className={`version-chat-launcher ${versionChatExpanded ? "d-none" : ""}`}
            onClick={() => setVersionChatExpanded(true)}
            title="Open chat"
          >
            <span className="version-chat-launcher-icon">
              <i className="bi bi-chat-dots-fill" aria-hidden={true} />
            </span>
            <span className="version-chat-launcher-label">Chat</span>
            {versionChatMessages.length > 0 && (
              <span className="version-chat-launcher-badge">{versionChatMessages.length}</span>
            )}
          </button>
        </div>
      )}

      {editAgentModal && (
        <div className="modal-backdrop-custom" onClick={() => setEditAgentModal(null)}>
          <div className="modal-dialog-custom" onClick={(e) => e.stopPropagation()}>
            <div className="card shadow border-0">
              <div className="card-body">
                <h2 className="h5 mb-3">Edit Agent</h2>
                <form onSubmit={handleUpdateAgent} className="row g-3">
                  <div className="col-12">
                    <label className="form-label">Agent Name</label>
                    <input
                      className="form-control"
                      placeholder="Customer Support Agent"
                      value={editAgentModal.name}
                      onChange={(e) => setEditAgentModal({ ...editAgentModal, name: e.target.value })}
                      required
                      minLength={2}
                    />
                  </div>
                  <div className="col-12">
                    <label className="form-label">Description</label>
                    <input
                      className="form-control"
                      placeholder="Describe this agent..."
                      value={editAgentModal.description}
                      onChange={(e) => setEditAgentModal({ ...editAgentModal, description: e.target.value })}
                    />
                  </div>
                  <div className="col-12 d-flex justify-content-end gap-2">
                    <button type="button" className="btn btn-outline-secondary" onClick={() => setEditAgentModal(null)}>
                      <i className="bi bi-x-lg me-1" aria-hidden={true} />
                      Cancel
                    </button>
                    <button type="submit" className="btn btn-primary">
                      <i className="bi bi-check-lg me-1" aria-hidden={true} />
                      Save
                    </button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        </div>
      )}

      {isAgentModalOpen && (
        <div className="modal-backdrop-custom" onClick={() => setIsAgentModalOpen(false)}>
          <div className="modal-dialog-custom" onClick={(e) => e.stopPropagation()}>
            <div className="card shadow border-0">
              <div className="card-body">
                <h2 className="h5 mb-3">Create Agent</h2>
                <form onSubmit={handleCreateAgent} className="row g-3">
                  <div className="col-12">
                    <label className="form-label">Agent Name</label>
                    <input
                      className="form-control"
                      placeholder="Customer Support Agent"
                      value={newAgent.name}
                      onChange={(e) => setNewAgent({ ...newAgent, name: e.target.value })}
                      required
                    />
                  </div>
                  <div className="col-12">
                    <label className="form-label">Description</label>
                    <input
                      className="form-control"
                      placeholder="Describe this agent..."
                      value={newAgent.description}
                      onChange={(e) => setNewAgent({ ...newAgent, description: e.target.value })}
                    />
                  </div>
                  <div className="col-12 d-flex justify-content-end gap-2">
                    <button type="button" className="btn btn-outline-secondary" onClick={() => setIsAgentModalOpen(false)}>
                      <i className="bi bi-x-lg me-1" aria-hidden={true} />
                      Cancel
                    </button>
                    <button type="submit" className="btn btn-primary">
                      <i className="bi bi-check-lg me-1" aria-hidden={true} />
                      Create Agent
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
