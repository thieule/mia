import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api";

/** Khớp với bảng workflow_definition / workflow_step_definition (runtime/schema/init.sql) — tải/lưu qua API → MySQL */
const DEFAULT_WORKFLOW_KEY = "wf01";
const DEFAULT_VERSION_TAG = "v1";
const END = "__end__";

const NODE_W = 228;
const NODE_H = 140;
/** Khoảng cắt dọc đường thẳng để nối đúng tâm cổng (px) — phải khớp kích thước cổng trong CSS */
const EDGE_TRIM = 7;
const CANVAS_PAD = 32;
/** Lưới căn node: mỗi ô = node + khoảng cách; bố cục gốc ưu tiên cột 0, thứ tự từ trên xuống */
const GRID_GAP_X = 48;
const GRID_GAP_Y = 56;
const GRID_CELL_W = NODE_W + GRID_GAP_X;
const GRID_CELL_H = NODE_H + GRID_GAP_Y;
const GRID_MAX_COL = 8;
const GRID_MAX_ROW = 64;
const ZOOM_MIN = 0.35;
const ZOOM_MAX = 2;
const PALETTE_MIME = "application/x-poc-wf-kind";

function clampZoom(z) {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));
}

function genId() {
  return `s_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
}

function slugFromName(name) {
  const s = String(name || "workflow")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_")
    .replace(/[^a-z0-9_]/g, "");
  return s || "workflow";
}

function defaultWorkflowMeta(nameHint) {
  return {
    workflow_key: slugFromName(nameHint),
    version_tag: "1.0.0",
    domain: "default",
    module_name: "core",
    risk_class: "medium",
    execution_mode: "manual",
    input_schema_key: "",
    output_schema_key: "",
    prompt_key: "",
    policy_rule_set_key: "",
    approval_key: "",
    status: "active",
    name: typeof nameHint === "string" && nameHint ? nameHint : "Quy trình mẫu",
    retry_policy_json: {},
    timeout_policy_json: {},
    observability_json: {},
  };
}

function pixelFromGrid(col, row) {
  return {
    x: CANVAS_PAD + col * GRID_CELL_W,
    y: CANVAS_PAD + row * GRID_CELL_H,
  };
}

function snapPointToGrid(x, y) {
  const col = Math.round((x - CANVAS_PAD) / GRID_CELL_W);
  const row = Math.round((y - CANVAS_PAD) / GRID_CELL_H);
  return pixelFromGrid(col, row);
}

/** Ô (col,row) đang bị chiếm bởi node khác (bỏ qua excludeId nếu đang kéo node đó) */
function occupiedGridKeys(layout, excludeId) {
  const set = new Set();
  for (const [id, p] of Object.entries(layout)) {
    if (!p || typeof p.x !== "number" || typeof p.y !== "number") continue;
    if (excludeId && id === excludeId) continue;
    const col = Math.round((p.x - CANVAS_PAD) / GRID_CELL_W);
    const row = Math.round((p.y - CANVAS_PAD) / GRID_CELL_H);
    set.add(`${col},${row}`);
  }
  return set;
}

/** Snap (x,y) về lưới; nếu ô đã có node khác thì ưu tiên dịch xuống dòng, rồi mới sang cột phải */
function snapLayoutPosition(layout, id, x, y) {
  const used = occupiedGridKeys(layout, id);
  const base = snapPointToGrid(x, y);
  let col = Math.round((base.x - CANVAS_PAD) / GRID_CELL_W);
  let row = Math.round((base.y - CANVAS_PAD) / GRID_CELL_H);
  let key = `${col},${row}`;
  let guard = 0;
  while (used.has(key) && guard < 500) {
    guard++;
    row++;
    if (row >= GRID_MAX_ROW) {
      row = 0;
      col++;
    }
    if (col >= GRID_MAX_COL) {
      col = 0;
    }
    key = `${col},${row}`;
  }
  return pixelFromGrid(col, row);
}

/** Ô trống đầu tiên: ưu tiên cột 0 từ trên xuống, rồi cột 1… (thêm bước theo thứ tự dọc) */
function nextFreeGridSlot(layout) {
  const used = occupiedGridKeys(layout, null);
  for (let col = 0; col < GRID_MAX_COL; col++) {
    for (let row = 0; row < GRID_MAX_ROW; row++) {
      const key = `${col},${row}`;
      if (!used.has(key)) return pixelFromGrid(col, row);
    }
  }
  return pixelFromGrid(0, 0);
}

/** Chuẩn hoá toàn bộ layout theo lưới (khi import / load), giữ thứ tự steps; trùng ô thì xuống dòng trước */
function snapFullLayoutOrdered(layout, orderedStepIds) {
  const used = new Set();
  const out = { ...layout };
  for (const id of orderedStepIds) {
    const p = out[id];
    if (!p || typeof p.x !== "number" || typeof p.y !== "number") continue;
    const base = snapPointToGrid(p.x, p.y);
    let col = Math.round((base.x - CANVAS_PAD) / GRID_CELL_W);
    let row = Math.round((base.y - CANVAS_PAD) / GRID_CELL_H);
    let key = `${col},${row}`;
    let guard = 0;
    while (used.has(key) && guard < 500) {
      guard++;
      row++;
      if (row >= GRID_MAX_ROW) {
        row = 0;
        col++;
      }
      if (col >= GRID_MAX_COL) {
        col = 0;
      }
      key = `${col},${row}`;
    }
    used.add(key);
    out[id] = pixelFromGrid(col, row);
  }
  return out;
}

/** Bố cục gốc: một cột (col=0), step_order chạy từ trên xuống */
function emptyLayoutForSteps(stepIds) {
  const layout = {};
  stepIds.forEach((id, i) => {
    layout[id] = pixelFromGrid(0, i);
  });
  return layout;
}

function emptyDefinition() {
  const meta = defaultWorkflowMeta("Quy trình mẫu");
  const idTask = genId();
  const idAi = genId();
  const idAp = genId();
  const steps = [
    {
      id: idTask,
      step_key: idTask,
      title: "Thu thập yêu cầu",
      kind: "task",
      step_type: "manual_task",
      executor_kind: "human",
      executor_target: "",
      description: "",
      output_schema_key: "",
      on_success_state: "",
      on_failure_state: "",
      input_mapping_json: "",
      artifact_type: "",
      artifact_enabled: 0,
      approval_required: 0,
      step_approval_key: "",
    },
    {
      id: idAi,
      step_key: idAi,
      title: "Soạn thảo bằng AI",
      kind: "ai",
      step_type: "ai_agent",
      executor_kind: "llm",
      executor_target: "",
      description: "",
      output_schema_key: "",
      on_success_state: "",
      on_failure_state: "",
      input_mapping_json: "",
      artifact_type: "",
      artifact_enabled: 0,
      approval_required: 0,
      step_approval_key: "",
    },
    {
      id: idAp,
      step_key: idAp,
      title: "Phê duyệt nội dung",
      kind: "approval",
      step_type: "human_approval",
      executor_kind: "human",
      executor_target: "",
      description: "",
      output_schema_key: "",
      on_success_state: "",
      on_failure_state: "",
      input_mapping_json: "",
      artifact_type: "",
      artifact_enabled: 0,
      approval_required: 1,
      step_approval_key: "",
      onApprove: END,
      onReject: idAi,
    },
  ];
  return {
    ...meta,
    steps,
    layout: emptyLayoutForSteps(steps.map((s) => s.id)),
    canvasView: { panX: 0, panY: 0, zoom: 1 },
  };
}

/** Không lưu tọa độ node ra disk — chỉ giữ phần định nghĩa + canvasView */
function persistPayload(source) {
  const copy = { ...source };
  delete copy.layout;
  delete copy.layoutVersion;
  return copy;
}

function normalizeStep(raw, allIds, index) {
  const id = typeof raw?.id === "string" ? raw.id : genId();
  const kind = raw?.kind === "ai" || raw?.kind === "approval" ? raw.kind : "task";
  const stepKey = typeof raw?.step_key === "string" ? raw.step_key : id;
  const stepType =
    typeof raw?.step_type === "string"
      ? raw.step_type
      : kind === "approval"
        ? "human_approval"
        : kind === "ai"
          ? "ai_agent"
          : "manual_task";
  const inputMappingRaw = raw?.input_mapping_json;
  const input_mapping_json =
    typeof inputMappingRaw === "string"
      ? inputMappingRaw
      : inputMappingRaw && typeof inputMappingRaw === "object"
        ? JSON.stringify(inputMappingRaw)
        : "";
  const base = {
    id,
    step_key: stepKey,
    title: typeof raw?.title === "string" ? raw.title : "Bước",
    kind,
    step_type: stepType,
    executor_kind: typeof raw?.executor_kind === "string" ? raw.executor_kind : kind === "ai" ? "llm" : "human",
    executor_target: typeof raw?.executor_target === "string" ? raw.executor_target : "",
    description: typeof raw?.description === "string" ? raw.description : "",
    output_schema_key: typeof raw?.output_schema_key === "string" ? raw.output_schema_key : "",
    on_success_state: typeof raw?.on_success_state === "string" ? raw.on_success_state : "",
    on_failure_state: typeof raw?.on_failure_state === "string" ? raw.on_failure_state : "",
    input_mapping_json,
    artifact_type: typeof raw?.artifact_type === "string" ? raw.artifact_type : "",
    artifact_enabled: raw?.artifact_enabled ? 1 : 0,
    approval_required: raw?.approval_required ? 1 : kind === "approval" ? 1 : 0,
    step_approval_key: typeof raw?.step_approval_key === "string" ? raw.step_approval_key : "",
  };
  if (kind !== "approval") return { ...base, step_order: index };
  const approve = typeof raw?.onApprove === "string" ? raw.onApprove : END;
  const reject = typeof raw?.onReject === "string" ? raw.onReject : "";
  return {
    ...base,
    step_order: index,
    onApprove: allIds.includes(approve) || approve === END ? approve : END,
    onReject: allIds.includes(reject) ? reject : "",
  };
}

function normalizeDefinition(parsed) {
  const meta = defaultWorkflowMeta(parsed?.name);
  const merged = {
    workflow_key: typeof parsed?.workflow_key === "string" ? parsed.workflow_key : meta.workflow_key,
    version_tag: typeof parsed?.version_tag === "string" ? parsed.version_tag : meta.version_tag,
    domain: typeof parsed?.domain === "string" ? parsed.domain : meta.domain,
    module_name: typeof parsed?.module_name === "string" ? parsed.module_name : meta.module_name,
    risk_class: typeof parsed?.risk_class === "string" ? parsed.risk_class : meta.risk_class,
    execution_mode: typeof parsed?.execution_mode === "string" ? parsed.execution_mode : meta.execution_mode,
    input_schema_key: typeof parsed?.input_schema_key === "string" ? parsed.input_schema_key : meta.input_schema_key,
    output_schema_key: typeof parsed?.output_schema_key === "string" ? parsed.output_schema_key : meta.output_schema_key,
    prompt_key: typeof parsed?.prompt_key === "string" ? parsed.prompt_key : meta.prompt_key,
    policy_rule_set_key:
      typeof parsed?.policy_rule_set_key === "string" ? parsed.policy_rule_set_key : meta.policy_rule_set_key,
    approval_key: typeof parsed?.approval_key === "string" ? parsed.approval_key : meta.approval_key,
    status: typeof parsed?.status === "string" ? parsed.status : meta.status,
    name: typeof parsed?.name === "string" ? parsed.name : meta.name,
    retry_policy_json:
      parsed?.retry_policy_json && typeof parsed.retry_policy_json === "object" ? parsed.retry_policy_json : {},
    timeout_policy_json:
      parsed?.timeout_policy_json && typeof parsed.timeout_policy_json === "object"
        ? parsed.timeout_policy_json
        : {},
    observability_json:
      parsed?.observability_json && typeof parsed.observability_json === "object"
        ? parsed.observability_json
        : {},
  };

  const stepsIn = Array.isArray(parsed?.steps) ? parsed.steps : [];
  const ids = stepsIn.map((s, i) => (typeof s?.id === "string" ? s.id : `tmp_${i}`)).filter(Boolean);
  const steps = stepsIn.map((s, i) => normalizeStep(s, ids, i));

  /** Luôn bố trí lại từ thứ tự steps (không dùng layout trong JSON / localStorage đã lưu) */
  let layout = {};
  steps.forEach((s, i) => {
    layout[s.id] = pixelFromGrid(0, i);
  });
  layout = snapFullLayoutOrdered(layout, steps.map((s) => s.id));

  const cv = parsed?.canvasView;
  const canvasView = {
    panX: typeof cv?.panX === "number" ? cv.panX : 0,
    panY: typeof cv?.panY === "number" ? cv.panY : 0,
    zoom: typeof cv?.zoom === "number" ? clampZoom(cv.zoom) : 1,
  };

  return { ...merged, steps, layout, canvasView };
}

/** Trạng thái ban đầu trước khi GET MySQL xong (0 bước — tránh flash mẫu local). */
function initialPlaceholderDef() {
  return normalizeDefinition({
    name: "…",
    workflow_key: DEFAULT_WORKFLOW_KEY,
    version_tag: DEFAULT_VERSION_TAG,
    steps: [],
  });
}

function kindLabel(kind) {
  if (kind === "ai") return "AI";
  if (kind === "approval") return "Phê duyệt";
  return "Thủ công";
}

function kindIcon(kind) {
  if (kind === "ai") return "◇";
  if (kind === "approval") return "✓";
  return "▢";
}

function kindAccentClass(kind) {
  if (kind === "approval") return "workflow-node-n8n--approval";
  if (kind === "ai") return "workflow-node-n8n--ai";
  return "workflow-node-n8n--task";
}

function createStepFromKind(kind, id) {
  if (kind === "approval") {
    return {
      id,
      step_key: id,
      title: "Phê duyệt",
      kind: "approval",
      step_type: "human_approval",
      executor_kind: "human",
      executor_target: "",
      description: "",
      output_schema_key: "",
      on_success_state: "",
      on_failure_state: "",
      input_mapping_json: "",
      artifact_type: "",
      artifact_enabled: 0,
      approval_required: 1,
      step_approval_key: "",
      onApprove: END,
      onReject: "",
    };
  }
  return {
    id,
    step_key: id,
    title: kind === "ai" ? "Bước AI" : "Bước thủ công",
    kind,
    step_type: kind === "ai" ? "ai_agent" : "manual_task",
    executor_kind: kind === "ai" ? "llm" : "human",
    executor_target: "",
    description: "",
    output_schema_key: "",
    on_success_state: "",
    on_failure_state: "",
    input_mapping_json: "",
    artifact_type: "",
    artifact_enabled: 0,
    approval_required: 0,
    step_approval_key: "",
  };
}

/** Cạnh hiển thị: phản ánh transition (from step → to step / end) */
function buildEdges(def) {
  const steps = def.steps;
  if (steps.length === 0) return [];
  const idSet = new Set(steps.map((x) => x.id));
  const edges = [];
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    if (s.kind === "approval") {
      const ap = s.onApprove === END || !idSet.has(s.onApprove) ? END : s.onApprove;
      edges.push({ from: s.id, to: ap, label: "on_success_state", dashed: false });
      if (s.onReject === END) {
        edges.push({ from: s.id, to: END, label: "on_failure_state", dashed: true });
      } else if (s.onReject && idSet.has(s.onReject)) {
        edges.push({ from: s.id, to: s.onReject, label: "on_failure_state", dashed: true });
      }
    } else {
      const next = steps[i + 1];
      if (next) edges.push({ from: s.id, to: next.id, label: "luồng chính", dashed: false });
      else edges.push({ from: s.id, to: END, label: "kết thúc", dashed: false });
    }
  }
  return edges;
}

function centerBottom(layout, id) {
  const p = layout[id];
  if (!p) return null;
  return { x: p.x + NODE_W / 2, y: p.y + NODE_H };
}

function centerTop(layout, id) {
  const p = layout[id];
  if (!p) return null;
  return { x: p.x + NODE_W / 2, y: p.y };
}

/** Cắt hai đầu đoạn thẳng để đường nối liền mạch với cổng in/out (tránh lệch do marker / chiều cao DOM) */
function trimLine(x1, y1, x2, y2, trimStart = EDGE_TRIM, trimEnd = EDGE_TRIM) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy);
  if (len < 1e-6) return { x1, y1, x2, y2 };
  const ux = dx / len;
  const uy = dy / len;
  const half = len / 2 - 1;
  const t0 = Math.min(trimStart, Math.max(0, half));
  const t1 = Math.min(trimEnd, Math.max(0, half));
  if (t0 + t1 >= len - 1e-6) return { x1, y1, x2, y2 };
  return {
    x1: x1 + ux * t0,
    y1: y1 + uy * t0,
    x2: x2 - ux * t1,
    y2: y2 - uy * t1,
  };
}

function pathBetween(x1, y1, x2, y2) {
  const d = `M ${x1} ${y1} L ${x2} ${y2}`;
  return { d };
}

export default function WorkflowPage() {
  const [def, setDef] = useState(() => initialPlaceholderDef());
  const [jsonText, setJsonText] = useState("");
  const [showJson, setShowJson] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [drag, setDrag] = useState(null);
  const [panDrag, setPanDrag] = useState(null);
  /** Ẩn cột form trái để canvas trải full hàng (mở rộng về phía trái) */
  const [leftPanelCollapsed, setLeftPanelCollapsed] = useState(false);
  const [dbLoading, setDbLoading] = useState(true);
  const [dbError, setDbError] = useState(null);
  const [saveMessage, setSaveMessage] = useState(null);
  const defRef = useRef(def);
  const viewportClipRef = useRef(null);
  const transformRef = useRef(null);
  const dragLayoutRef = useRef({ x: 0, y: 0 });

  useEffect(() => {
    defRef.current = def;
  }, [def]);

  const fetchDefinition = useCallback(async (workflowKey, versionTag) => {
    setDbLoading(true);
    setDbError(null);
    setSaveMessage(null);
    try {
      const data = await api.getWorkflowDefinition(workflowKey, versionTag);
      setDef(normalizeDefinition(data));
      setSelectedId(null);
    } catch (e) {
      const msg = e?.message || String(e);
      setDbError(msg);
      setDef(
        normalizeDefinition({
          ...persistPayload(initialPlaceholderDef()),
          workflow_key: workflowKey,
          version_tag: versionTag,
          name: "Lỗi tải",
          steps: [],
        }),
      );
    } finally {
      setDbLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDefinition(DEFAULT_WORKFLOW_KEY, DEFAULT_VERSION_TAG);
  }, [fetchDefinition]);

  const saveToDb = useCallback(async () => {
    setSaveMessage(null);
    setDbError(null);
    try {
      const payload = persistPayload(def);
      await api.putWorkflowDefinition(def.workflow_key, payload, def.version_tag);
      setSaveMessage("Đã lưu định nghĩa lên MySQL.");
    } catch (e) {
      setDbError(e?.message || String(e));
    }
  }, [def]);

  const edges = useMemo(() => buildEdges(def), [def]);

  const canvasSize = useMemo(() => {
    const layout = def.layout || {};
    let maxX = CANVAS_PAD + NODE_W + 200;
    let maxY = CANVAS_PAD + NODE_H + 160;
    for (const s of def.steps) {
      const p = layout[s.id];
      if (p) {
        maxX = Math.max(maxX, p.x + NODE_W + CANVAS_PAD);
        maxY = Math.max(maxY, p.y + NODE_H + CANVAS_PAD);
      }
    }
    if (edges.some((e) => e.to === END)) {
      maxY += 100;
    }
    return { width: maxX, height: maxY };
  }, [def.steps, def.layout, edges]);

  const endAnchor = useMemo(() => {
    const layout = def.layout || {};
    let maxY = CANVAS_PAD;
    for (const s of def.steps) {
      const p = layout[s.id];
      if (p) maxY = Math.max(maxY, p.y + NODE_H);
    }
    return {
      x: Math.max(CANVAS_PAD, (canvasSize.width - NODE_W) / 2),
      y: maxY + 36,
    };
  }, [def.steps, def.layout, canvasSize.width]);

  const updateStep = useCallback((id, patch) => {
    setDef((d) => ({
      ...d,
      steps: d.steps.map((s, idx) => (s.id === id ? { ...s, ...patch, step_order: idx } : { ...s, step_order: idx })),
    }));
  }, []);

  const addStepAt = useCallback((kind, px, py) => {
    const id = genId();
    const step = createStepFromKind(kind, id);
    setDef((d) => {
      const idx = d.steps.length;
      const pos = snapLayoutPosition({ ...d.layout }, id, px, py);
      return {
        ...d,
        steps: [...d.steps.map((s, i) => ({ ...s, step_order: i })), { ...step, step_order: idx }],
        layout: { ...d.layout, [id]: pos },
      };
    });
    setSelectedId(id);
  }, []);

  const addStep = useCallback((kind) => {
    const id = genId();
    const step = createStepFromKind(kind, id);
    setDef((d) => {
      const idx = d.steps.length;
      const pos = nextFreeGridSlot(d.layout || {});
      return {
        ...d,
        steps: [...d.steps.map((s, i) => ({ ...s, step_order: i })), { ...step, step_order: idx }],
        layout: { ...d.layout, [id]: pos },
      };
    });
    setSelectedId(id);
  }, []);

  const removeStep = useCallback((id) => {
    setDef((d) => ({
      ...d,
      steps: d.steps
        .filter((s) => s.id !== id)
        .map((s, i) => ({ ...s, step_order: i }))
        .map((s) => {
          if (s.kind !== "approval") return s;
          let onApprove = s.onApprove;
          let onReject = s.onReject;
          if (onApprove === id) onApprove = END;
          if (onReject === id) onReject = "";
          return { ...s, onApprove, onReject };
        }),
      layout: Object.fromEntries(Object.entries(d.layout || {}).filter(([k]) => k !== id)),
    }));
    setSelectedId((cur) => (cur === id ? null : cur));
  }, []);

  const moveStep = useCallback((id, dir) => {
    setDef((d) => {
      const idx = d.steps.findIndex((s) => s.id === id);
      if (idx < 0) return d;
      const j = idx + dir;
      if (j < 0 || j >= d.steps.length) return d;
      const next = [...d.steps];
      [next[idx], next[j]] = [next[j], next[idx]];
      return {
        ...d,
        steps: next.map((s, i) => ({ ...s, step_order: i })),
      };
    });
  }, []);

  const onNodePointerDown = useCallback((e, id) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    setSelectedId(id);
    const layout = def.layout?.[id];
    if (!layout) return;
    const z = def.canvasView?.zoom ?? 1;
    dragLayoutRef.current = { x: layout.x, y: layout.y };
    setDrag({
      id,
      startX: e.clientX,
      startY: e.clientY,
      origX: layout.x,
      origY: layout.y,
      zoom: z,
    });
  }, [def.layout, def.canvasView?.zoom]);

  useEffect(() => {
    if (!drag) return;
    const onMove = (e) => {
      const z = drag.zoom || 1;
      const dx = (e.clientX - drag.startX) / z;
      const dy = (e.clientY - drag.startY) / z;
      const x = Math.max(0, drag.origX + dx);
      const y = Math.max(0, drag.origY + dy);
      dragLayoutRef.current = { x, y };
      setDef((d) => ({
        ...d,
        layout: {
          ...d.layout,
          [drag.id]: { x, y },
        },
      }));
    };
    const onUp = () => {
      const id = drag.id;
      setDef((d) => {
        const { x, y } = dragLayoutRef.current;
        const snapped = snapLayoutPosition(d.layout, id, x, y);
        return {
          ...d,
          layout: {
            ...d.layout,
            [id]: snapped,
          },
        };
      });
      setDrag(null);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [drag]);

  useEffect(() => {
    if (!panDrag) return;
    const onMove = (e) => {
      const dx = e.clientX - panDrag.startX;
      const dy = e.clientY - panDrag.startY;
      setDef((d) => ({
        ...d,
        canvasView: {
          panX: panDrag.origPanX + dx,
          panY: panDrag.origPanY + dy,
          zoom: d.canvasView?.zoom ?? 1,
        },
      }));
    };
    const onUp = () => setPanDrag(null);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [panDrag]);

  const onViewportPointerDown = useCallback((e) => {
    if (e.target.closest(".workflow-node-n8n")) return;
    if (e.shiftKey || e.button === 1) {
      e.preventDefault();
      const cv = defRef.current.canvasView || { panX: 0, panY: 0, zoom: 1 };
      setPanDrag({
        startX: e.clientX,
        startY: e.clientY,
        origPanX: cv.panX,
        origPanY: cv.panY,
      });
      return;
    }
    if (e.button !== 0) return;
    setSelectedId(null);
  }, []);

  const fitToView = useCallback(() => {
    const clip = viewportClipRef.current;
    if (!clip) return;
    const d = defRef.current;
    const layout = d.layout || {};
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const s of d.steps) {
      const p = layout[s.id];
      if (!p) continue;
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x + NODE_W);
      maxY = Math.max(maxY, p.y + NODE_H);
    }
    const edgesList = buildEdges(d);
    if (edgesList.some((x) => x.to === END)) {
      let maxYNodes = CANVAS_PAD;
      let maxXContent = CANVAS_PAD + NODE_W + 200;
      for (const s of d.steps) {
        const p = layout[s.id];
        if (p) {
          maxYNodes = Math.max(maxYNodes, p.y + NODE_H);
          maxXContent = Math.max(maxXContent, p.x + NODE_W + CANVAS_PAD);
        }
      }
      const ex = Math.max(CANVAS_PAD, (maxXContent - NODE_W) / 2);
      const ey = maxYNodes + 36;
      minX = Math.min(minX, ex);
      minY = Math.min(minY, ey);
      maxX = Math.max(maxX, ex + NODE_W);
      maxY = Math.max(maxY, ey + 48);
    }
    if (!Number.isFinite(minX) || d.steps.length === 0) {
      setDef((prev) => ({
        ...prev,
        canvasView: { panX: 24, panY: 24, zoom: 1 },
      }));
      return;
    }
    const pad = 56;
    const bw = maxX - minX + pad * 2;
    const bh = maxY - minY + pad * 2;
    const cw = clip.clientWidth || 800;
    const ch = clip.clientHeight || 520;
    const scale = Math.min(cw / bw, ch / bh, 1) * 0.88;
    const z = clampZoom(scale);
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    setDef((prev) => ({
      ...prev,
      canvasView: {
        zoom: z,
        panX: cw / 2 - cx * z,
        panY: ch / 2 - cy * z,
      },
    }));
  }, []);

  /** Sau khi canvas giãn full hàng, căn lại khung nhìn cho vừa màn */
  useEffect(() => {
    if (!leftPanelCollapsed) return;
    const id = window.setTimeout(() => fitToView(), 120);
    return () => clearTimeout(id);
  }, [leftPanelCollapsed, fitToView]);

  const zoomIn = useCallback(() => {
    setDef((d) => {
      const cv = d.canvasView || { panX: 0, panY: 0, zoom: 1 };
      return { ...d, canvasView: { ...cv, zoom: clampZoom(cv.zoom * 1.12) } };
    });
  }, []);

  const zoomOut = useCallback(() => {
    setDef((d) => {
      const cv = d.canvasView || { panX: 0, panY: 0, zoom: 1 };
      return { ...d, canvasView: { ...cv, zoom: clampZoom(cv.zoom / 1.12) } };
    });
  }, []);

  const resetView = useCallback(() => {
    setDef((d) => ({ ...d, canvasView: { panX: 0, panY: 0, zoom: 1 } }));
  }, []);

  const onCanvasDragOver = useCallback((e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  const onCanvasDrop = useCallback(
    (e) => {
      e.preventDefault();
      const kind = e.dataTransfer.getData(PALETTE_MIME);
      if (kind !== "task" && kind !== "ai" && kind !== "approval") return;
      const clip = viewportClipRef.current;
      if (!clip) return;
      const rect = clip.getBoundingClientRect();
      const lx = e.clientX - rect.left + clip.scrollLeft;
      const ly = e.clientY - rect.top + clip.scrollTop;
      const d = defRef.current;
      const cv = d.canvasView || { panX: 0, panY: 0, zoom: 1 };
      const wx = (lx - cv.panX) / cv.zoom - NODE_W / 2;
      const wy = (ly - cv.panY) / cv.zoom - NODE_H / 2;
      addStepAt(kind, Math.max(0, wx), Math.max(0, wy));
    },
    [addStepAt],
  );

  const exportJson = useCallback(() => {
    const blob = new Blob([JSON.stringify(persistPayload(def), null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(def.workflow_key || def.name || "workflow").replace(/\s+/g, "_")}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }, [def]);

  const applyImportedJson = useCallback(() => {
    try {
      const parsed = JSON.parse(jsonText);
      setDef(normalizeDefinition(parsed));
      setShowJson(false);
      setSelectedId(null);
    } catch {
      window.alert("JSON không hợp lệ.");
    }
  }, [jsonText]);

  const selected = def.steps.find((s) => s.id === selectedId) || null;
  const selectedIdx = selected ? def.steps.indexOf(selected) : -1;
  const cv = def.canvasView || { panX: 0, panY: 0, zoom: 1 };

  const scrollSpacerSize = useMemo(() => {
    const z = cv.zoom ?? 1;
    const px = cv.panX ?? 0;
    const py = cv.panY ?? 0;
    const w = Math.ceil(canvasSize.width * z + Math.abs(px) + 3 * CANVAS_PAD);
    const h = Math.ceil(canvasSize.height * z + Math.abs(py) + 3 * CANVAS_PAD);
    return { width: Math.max(w, 520), height: Math.max(h, 440) };
  }, [cv.panX, cv.panY, cv.zoom, canvasSize.width, canvasSize.height]);

  return (
    <div className="row g-4 workflow-page align-items-start">
      <div className={`col-12 col-xl-4 ${leftPanelCollapsed ? "d-none" : ""}`}>
        <div className="card shadow-sm border-0">
          <div className="card-body">
            <h2 className="h5 mb-3">Định nghĩa workflow</h2>
            <p className="small text-muted mb-3">
              Dữ liệu đọc/ghi qua backend vào MySQL (<code>workflow_definition</code>, <code>workflow_step_definition</code>
              ). Không dùng localStorage. Các trường dưới khớp schema runtime (workflow_key, version_tag, domain, …).
            </p>
            {dbLoading && (
              <div className="alert alert-light border py-2 small mb-2" role="status">
                <span className="spinner-border spinner-border-sm me-2" aria-hidden />
                Đang tải từ MySQL…
              </div>
            )}
            {dbError && (
              <div className="alert alert-danger py-2 small mb-2" role="alert">
                {dbError}
              </div>
            )}
            {saveMessage && !dbError && (
              <div className="alert alert-success py-2 small mb-2" role="status">
                {saveMessage}
              </div>
            )}
            <div className="d-flex flex-wrap gap-2 mb-3">
              <button
                type="button"
                className="btn btn-sm btn-outline-primary"
                disabled={dbLoading}
                onClick={() => fetchDefinition(def.workflow_key, def.version_tag)}
              >
                Tải lại từ MySQL
              </button>
              <button type="button" className="btn btn-sm btn-primary" disabled={dbLoading} onClick={() => saveToDb()}>
                Lưu lên MySQL
              </button>
            </div>
            <div className="mb-2">
              <label className="form-label small text-muted mb-1">name (hiển thị)</label>
              <input
                className="form-control form-control-sm"
                value={def.name}
                onChange={(e) => setDef((d) => ({ ...d, name: e.target.value }))}
              />
            </div>
            <div className="row g-2">
              <div className="col-12 col-md-6">
                <label className="form-label small text-muted mb-1">workflow_key</label>
                <input
                  className="form-control form-control-sm font-monospace"
                  value={def.workflow_key}
                  onChange={(e) => setDef((d) => ({ ...d, workflow_key: e.target.value }))}
                />
              </div>
              <div className="col-12 col-md-6">
                <label className="form-label small text-muted mb-1">version_tag</label>
                <input
                  className="form-control form-control-sm font-monospace"
                  value={def.version_tag}
                  onChange={(e) => setDef((d) => ({ ...d, version_tag: e.target.value }))}
                />
              </div>
              <div className="col-12 col-md-6">
                <label className="form-label small text-muted mb-1">domain</label>
                <input
                  className="form-control form-control-sm"
                  value={def.domain}
                  onChange={(e) => setDef((d) => ({ ...d, domain: e.target.value }))}
                />
              </div>
              <div className="col-12 col-md-6">
                <label className="form-label small text-muted mb-1">module_name</label>
                <input
                  className="form-control form-control-sm"
                  value={def.module_name}
                  onChange={(e) => setDef((d) => ({ ...d, module_name: e.target.value }))}
                />
              </div>
              <div className="col-12 col-md-6">
                <label className="form-label small text-muted mb-1">risk_class</label>
                <select
                  className="form-select form-select-sm"
                  value={def.risk_class}
                  onChange={(e) => setDef((d) => ({ ...d, risk_class: e.target.value }))}
                >
                  <option value="low">low</option>
                  <option value="medium">medium</option>
                  <option value="high">high</option>
                </select>
              </div>
              <div className="col-12 col-md-6">
                <label className="form-label small text-muted mb-1">execution_mode</label>
                <input
                  className="form-control form-control-sm font-monospace"
                  value={def.execution_mode}
                  onChange={(e) => setDef((d) => ({ ...d, execution_mode: e.target.value }))}
                  placeholder="manual"
                />
              </div>
              <div className="col-12">
                <label className="form-label small text-muted mb-1">input_schema_key</label>
                <input
                  className="form-control form-control-sm font-monospace"
                  value={def.input_schema_key}
                  onChange={(e) => setDef((d) => ({ ...d, input_schema_key: e.target.value }))}
                />
              </div>
              <div className="col-12">
                <label className="form-label small text-muted mb-1">output_schema_key</label>
                <input
                  className="form-control form-control-sm font-monospace"
                  value={def.output_schema_key}
                  onChange={(e) => setDef((d) => ({ ...d, output_schema_key: e.target.value }))}
                />
              </div>
              <div className="col-12">
                <label className="form-label small text-muted mb-1">prompt_key</label>
                <input
                  className="form-control form-control-sm font-monospace"
                  value={def.prompt_key}
                  onChange={(e) => setDef((d) => ({ ...d, prompt_key: e.target.value }))}
                />
              </div>
              <div className="col-12">
                <label className="form-label small text-muted mb-1">policy_rule_set_key</label>
                <input
                  className="form-control form-control-sm font-monospace"
                  value={def.policy_rule_set_key}
                  onChange={(e) => setDef((d) => ({ ...d, policy_rule_set_key: e.target.value }))}
                />
              </div>
              <div className="col-12">
                <label className="form-label small text-muted mb-1">approval_key (workflow)</label>
                <input
                  className="form-control form-control-sm font-monospace"
                  value={def.approval_key}
                  onChange={(e) => setDef((d) => ({ ...d, approval_key: e.target.value }))}
                />
              </div>
              <div className="col-12">
                <label className="form-label small text-muted mb-1">status</label>
                <select
                  className="form-select form-select-sm"
                  value={def.status}
                  onChange={(e) => setDef((d) => ({ ...d, status: e.target.value }))}
                >
                  <option value="active">active</option>
                  <option value="draft">draft</option>
                  <option value="retired">retired</option>
                </select>
              </div>
            </div>

            <div className="d-flex flex-wrap gap-2 mt-3">
              <button type="button" className="btn btn-sm btn-outline-primary" onClick={() => addStep("task")}>
                + Bước thủ công
              </button>
              <button type="button" className="btn btn-sm btn-outline-primary" onClick={() => addStep("ai")}>
                + Bước AI
              </button>
              <button type="button" className="btn btn-sm btn-primary" onClick={() => addStep("approval")}>
                + Phê duyệt
              </button>
            </div>

            <div className="d-flex flex-wrap gap-2 mt-3 pt-3 border-top">
              <button type="button" className="btn btn-outline-secondary btn-sm" onClick={exportJson}>
                Tải JSON
              </button>
              <button type="button" className="btn btn-outline-secondary btn-sm" onClick={() => setShowJson((v) => !v)}>
                {showJson ? "Đóng nhập JSON" : "Nhập JSON"}
              </button>
            </div>
            {showJson && (
              <div className="mt-3">
                <label className="form-label small">Dán JSON (định nghĩa workflow; vị trí node tự xếp theo thứ tự bước)</label>
                <textarea
                  className="form-control font-monospace small"
                  rows={8}
                  value={jsonText}
                  onChange={(e) => setJsonText(e.target.value)}
                  placeholder='{"workflow_key":"...","steps":[...]}'
                />
                <button type="button" className="btn btn-sm btn-primary mt-2" onClick={applyImportedJson}>
                  Áp dụng
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="card shadow-sm border-0 mt-3">
          <div className="card-body">
            <h2 className="h6 mb-2">Chi tiết bước (workflow_step_definition)</h2>
            {!selected ? (
              <p className="small text-muted mb-0">Chọn một node trên canvas để sửa step_key, step_type, executor, …</p>
            ) : (
              <>
                <div className="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-2">
                  <span className="badge text-bg-secondary">step_order: {selectedIdx + 1}</span>
                  <div className="btn-group btn-group-sm">
                    <button
                      type="button"
                      className="btn btn-outline-secondary"
                      disabled={selectedIdx === 0}
                      onClick={() => moveStep(selected.id, -1)}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="btn btn-outline-secondary"
                      disabled={selectedIdx === def.steps.length - 1}
                      onClick={() => moveStep(selected.id, 1)}
                    >
                      ↓
                    </button>
                    <button type="button" className="btn btn-outline-danger" onClick={() => removeStep(selected.id)}>
                      Xóa
                    </button>
                  </div>
                </div>
                <div className="mb-2">
                  <label className="form-label small mb-0">step_key</label>
                  <input
                    className="form-control form-control-sm font-monospace"
                    value={selected.step_key ?? ""}
                    onChange={(e) => {
                      const v = e.target.value;
                      updateStep(selected.id, { step_key: v });
                    }}
                  />
                </div>
                <div className="mb-2">
                  <label className="form-label small mb-0">step_type</label>
                  <input
                    className="form-control form-control-sm font-monospace"
                    value={selected.step_type ?? ""}
                    onChange={(e) => updateStep(selected.id, { step_type: e.target.value })}
                  />
                </div>
                <div className="row g-2 mb-2">
                  <div className="col-12">
                    <label className="form-label small mb-0">Tiêu đề</label>
                    <input
                      className="form-control form-control-sm"
                      value={selected.title}
                      onChange={(e) => updateStep(selected.id, { title: e.target.value })}
                    />
                  </div>
                  <div className="col-12 col-md-6">
                    <label className="form-label small mb-0">executor_kind</label>
                    <input
                      className="form-control form-control-sm font-monospace"
                      value={selected.executor_kind ?? ""}
                      onChange={(e) => updateStep(selected.id, { executor_kind: e.target.value })}
                    />
                  </div>
                  <div className="col-12 col-md-6">
                    <label className="form-label small mb-0">executor_target</label>
                    <input
                      className="form-control form-control-sm font-monospace"
                      value={selected.executor_target ?? ""}
                      onChange={(e) => updateStep(selected.id, { executor_target: e.target.value })}
                      placeholder="model / tool id"
                    />
                  </div>
                  <div className="col-12">
                    <label className="form-label small mb-0">output_schema_key</label>
                    <input
                      className="form-control form-control-sm font-monospace"
                      value={selected.output_schema_key ?? ""}
                      onChange={(e) => updateStep(selected.id, { output_schema_key: e.target.value })}
                    />
                  </div>
                  <div className="col-12">
                    <label className="form-label small mb-0">Mô tả</label>
                    <textarea
                      className="form-control form-control-sm"
                      rows={2}
                      value={selected.description}
                      onChange={(e) => updateStep(selected.id, { description: e.target.value })}
                    />
                  </div>
                  <div className="col-12">
                    <details className="border rounded px-2 py-1 bg-light">
                      <summary className="small text-muted" style={{ cursor: "pointer" }}>
                        Runtime / DB — trạng thái sau bước, artifact, input mapping (workflow_step_definition)
                      </summary>
                      <div className="row g-2 pt-2">
                        <div className="col-12 col-md-6">
                          <label className="form-label small mb-0">on_success_state</label>
                          <input
                            className="form-control form-control-sm font-monospace"
                            placeholder="vd. VALIDATING"
                            value={selected.on_success_state ?? ""}
                            onChange={(e) => updateStep(selected.id, { on_success_state: e.target.value })}
                          />
                        </div>
                        <div className="col-12 col-md-6">
                          <label className="form-label small mb-0">on_failure_state</label>
                          <input
                            className="form-control form-control-sm font-monospace"
                            placeholder="vd. FAILED"
                            value={selected.on_failure_state ?? ""}
                            onChange={(e) => updateStep(selected.id, { on_failure_state: e.target.value })}
                          />
                        </div>
                        <div className="col-12 col-md-6">
                          <label className="form-label small mb-0">artifact_type</label>
                          <input
                            className="form-control form-control-sm font-monospace"
                            value={selected.artifact_type ?? ""}
                            onChange={(e) => updateStep(selected.id, { artifact_type: e.target.value })}
                          />
                        </div>
                        <div className="col-12 col-md-6 d-flex align-items-end">
                          <div className="form-check mb-1">
                            <input
                              type="checkbox"
                              className="form-check-input"
                              id={`artifact_enabled_${selected.id}`}
                              checked={!!selected.artifact_enabled}
                              onChange={(e) =>
                                updateStep(selected.id, { artifact_enabled: e.target.checked ? 1 : 0 })
                              }
                            />
                            <label className="form-check-label small" htmlFor={`artifact_enabled_${selected.id}`}>
                              artifact_enabled
                            </label>
                          </div>
                        </div>
                        <div className="col-12">
                          <label className="form-label small mb-0">input_mapping_json</label>
                          <textarea
                            className="form-control form-control-sm font-monospace"
                            rows={3}
                            placeholder='{"field": "$.run.input"}'
                            value={selected.input_mapping_json ?? ""}
                            onChange={(e) => updateStep(selected.id, { input_mapping_json: e.target.value })}
                          />
                        </div>
                      </div>
                    </details>
                  </div>
                  {selected.kind === "approval" && (
                    <>
                      <div className="col-12">
                        <label className="form-label small mb-0">approval_key (bước)</label>
                        <input
                          className="form-control form-control-sm font-monospace"
                          value={selected.step_approval_key ?? ""}
                          onChange={(e) => updateStep(selected.id, { step_approval_key: e.target.value })}
                        />
                      </div>
                      <div className="col-12 col-md-6">
                        <label className="form-label small mb-0">on_success_state →</label>
                        <select
                          className="form-select form-select-sm"
                          value={selected.onApprove}
                          onChange={(e) => updateStep(selected.id, { onApprove: e.target.value })}
                        >
                          <option value={END}>Kết thúc (__end__)</option>
                          {def.steps.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.step_key || t.title}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="col-12 col-md-6">
                        <label className="form-label small mb-0">on_failure_state →</label>
                        <select
                          className="form-select form-select-sm"
                          value={selected.onReject}
                          onChange={(e) => updateStep(selected.id, { onReject: e.target.value })}
                        >
                          <option value="">— Chọn bước —</option>
                          <option value={END}>Kết thúc</option>
                          {def.steps.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.step_key || t.title}
                            </option>
                          ))}
                        </select>
                      </div>
                    </>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      <div className={`col-12 workflow-canvas-column ${leftPanelCollapsed ? "" : "col-xl-8"}`}>
        <div className="card shadow-sm border-0 h-100">
          <div className="card-body">
            <div className="d-flex flex-wrap align-items-start gap-2 mb-2">
              {leftPanelCollapsed ? (
                <button
                  type="button"
                  className="btn btn-outline-primary btn-sm workflow-canvas-toggle flex-shrink-0"
                  title="Hiện lại panel định nghĩa workflow (bên trái)"
                  onClick={() => setLeftPanelCollapsed(false)}
                >
                  <span className="me-1" aria-hidden>
                    ▶
                  </span>
                  <span className="small">Form</span>
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm workflow-canvas-toggle flex-shrink-0"
                  title="Ẩn panel trái — canvas trải full hàng"
                  onClick={() => setLeftPanelCollapsed(true)}
                >
                  <span aria-hidden>◀</span>
                </button>
              )}
              <div className="flex-grow-1 min-w-0">
                <div className="d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <h2 className="h5 mb-0">Canvas (gợi ý từ n8n)</h2>
                  {leftPanelCollapsed && (
                    <span className="badge text-bg-light border text-secondary small">Chế độ full hàng</span>
                  )}
                </div>
              </div>
            </div>
            <p className="small text-muted mb-3">
              Node căn lưới — thả chuột để snap · palette / thêm bước · <strong>cuộn</strong> trong khung canvas ·
              Shift+kéo nền = pan · zoom bằng nút +/−. Luồng theo <strong>step_order</strong> và nhánh phê duyệt (
              <code>on_success_state</code> / <code>on_failure_state</code>).
            </p>

            <div className="workflow-n8n-frame rounded border bg-white">
              <div className="workflow-n8n-toolbar d-flex flex-wrap align-items-center gap-2 px-2 py-2 border-bottom bg-light">
                <span className="small text-muted me-1">Khung nhìn</span>
                <div className="btn-group btn-group-sm">
                  <button type="button" className="btn btn-outline-secondary" title="Thu nhỏ" onClick={zoomOut}>
                    −
                  </button>
                  <button type="button" className="btn btn-outline-secondary" title="Phóng to" onClick={zoomIn}>
                    +
                  </button>
                </div>
                <span className="small font-monospace text-secondary">{Math.round(cv.zoom * 100)}%</span>
                <button type="button" className="btn btn-sm btn-outline-primary" onClick={fitToView}>
                  Vừa khung
                </button>
                <button type="button" className="btn btn-sm btn-outline-secondary" onClick={resetView}>
                  Reset 100%
                </button>
              </div>

              <div className="d-flex workflow-n8n-main">
                <aside className="workflow-palette border-end bg-light py-2 px-2 flex-shrink-0">
                  <div className="small fw-semibold text-muted text-uppercase mb-2" style={{ fontSize: "0.65rem", letterSpacing: "0.06em" }}>
                    Nodes
                  </div>
                  {[
                    { kind: "task", label: "Thủ công", hint: "manual_task" },
                    { kind: "ai", label: "AI", hint: "ai_agent" },
                    { kind: "approval", label: "Phê duyệt", hint: "human_approval" },
                  ].map((p) => (
                    <button
                      key={p.kind}
                      type="button"
                      draggable
                      className={`workflow-palette-item workflow-palette-item--${p.kind} w-100 text-start mb-2`}
                      onDragStart={(e) => {
                        e.dataTransfer.setData(PALETTE_MIME, p.kind);
                        e.dataTransfer.effectAllowed = "copy";
                      }}
                    >
                      <span className="workflow-palette-item-icon">{kindIcon(p.kind)}</span>
                      <span>
                        <span className="d-block fw-semibold small">{p.label}</span>
                        <span className="d-block text-muted" style={{ fontSize: "0.7rem" }}>
                          {p.hint}
                        </span>
                      </span>
                    </button>
                  ))}
                  <p className="small text-muted mb-0 mt-2" style={{ fontSize: "0.7rem", maxWidth: 132 }}>
                    Kéo thả lên lưới để đặt node; hoặc dùng nút “+ Bước…” ở form bên trái.
                  </p>
                </aside>

                <div
                  ref={viewportClipRef}
                  className="workflow-viewport-clip flex-grow-1 position-relative overflow-auto min-h-0"
                  style={{
                    height: 560,
                    maxHeight: "min(75vh, 720px)",
                    cursor: panDrag ? "grabbing" : "default",
                  }}
                  onPointerDown={onViewportPointerDown}
                >
                  <div
                    className="workflow-canvas-scroll-spacer position-relative"
                    style={{
                      width: scrollSpacerSize.width,
                      height: scrollSpacerSize.height,
                    }}
                  >
                    <div
                      ref={transformRef}
                      className="workflow-transform-layer workflow-canvas-n8n-bg position-absolute top-0 start-0"
                      style={{
                        width: canvasSize.width,
                        height: canvasSize.height,
                        transform: `translate(${cv.panX}px, ${cv.panY}px) scale(${cv.zoom})`,
                        transformOrigin: "0 0",
                      }}
                      onDragOver={onCanvasDragOver}
                      onDrop={onCanvasDrop}
                    >
                    <svg
                      className="workflow-edges"
                      width={canvasSize.width}
                      height={canvasSize.height}
                      viewBox={`0 0 ${canvasSize.width} ${canvasSize.height}`}
                      style={{ overflow: "visible" }}
                    >
                      <defs>
                        <marker id="arrow-wf" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                          <path d="M0,0 L8,4 L0,8 Z" fill="#64748b" />
                        </marker>
                        <marker id="arrow-wf-dim" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                          <path d="M0,0 L8,4 L0,8 Z" fill="#94a3b8" />
                        </marker>
                      </defs>
                      {edges.map((e, i) => {
                        const layout = def.layout || {};
                        const from = centerBottom(layout, e.from);
                        if (!from) return null;
                        let toX;
                        let toY;
                        if (e.to === END) {
                          toX = endAnchor.x + NODE_W / 2;
                          toY = endAnchor.y;
                        } else {
                          const to = centerTop(layout, e.to);
                          if (!to) return null;
                          toX = to.x;
                          toY = to.y;
                        }
                        const tr = trimLine(from.x, from.y, toX, toY);
                        const a = pathBetween(tr.x1, tr.y1, tr.x2, tr.y2);
                        const stroke = e.dashed ? "#94a3b8" : "#64748b";
                        return (
                          <path
                            key={`${e.from}-${e.to}-${e.label}-${i}`}
                            d={a.d}
                            fill="none"
                            stroke={stroke}
                            strokeWidth={e.dashed ? 1.5 : 2}
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeDasharray={e.dashed ? "6 4" : undefined}
                            markerEnd={e.dashed ? "url(#arrow-wf-dim)" : "url(#arrow-wf)"}
                          />
                        );
                      })}
                    </svg>

                    {def.steps.map((s) => {
                      const p = def.layout?.[s.id];
                      const pos = p || { x: CANVAS_PAD, y: CANVAS_PAD };
                      const isSel = selectedId === s.id;
                      const isDragging = drag?.id === s.id;
                      return (
                        <div
                          key={s.id}
                          className={`workflow-node-n8n position-absolute ${kindAccentClass(s.kind)} ${
                            isSel ? "workflow-node-n8n--selected" : ""
                          } ${isDragging ? "workflow-node-n8n--dragging" : ""}`}
                          style={{
                            left: pos.x,
                            top: pos.y,
                            width: NODE_W,
                            height: NODE_H,
                            zIndex: isSel ? 4 : 2,
                          }}
                          onPointerDown={(e) => onNodePointerDown(e, s.id)}
                        >
                          <div className="workflow-node-port workflow-node-port--in" aria-hidden />
                          <div className="workflow-node-n8n-inner">
                            <div className="workflow-node-n8n-head">
                              <span className="workflow-node-n8n-ico">{kindIcon(s.kind)}</span>
                              <div className="workflow-node-n8n-titles">
                                <div className="workflow-node-n8n-title text-truncate" title={s.title}>
                                  {s.title || s.step_key}
                                </div>
                                <div className="workflow-node-n8n-sub font-monospace text-truncate">{s.step_key}</div>
                              </div>
                              <span className="workflow-node-n8n-badge">{kindLabel(s.kind)}</span>
                            </div>
                            <div className="workflow-node-n8n-meta font-monospace text-truncate">{s.step_type}</div>
                          </div>
                          <div className="workflow-node-port workflow-node-port--out" aria-hidden />
                        </div>
                      );
                    })}

                    {edges.some((e) => e.to === END) && (
                      <div
                        className="workflow-end-node workflow-end-node-n8n position-absolute text-center"
                        style={{
                          left: endAnchor.x,
                          top: endAnchor.y,
                          width: NODE_W,
                          zIndex: 1,
                        }}
                      >
                        <div className="workflow-node-port workflow-node-port--in" aria-hidden />
                        <div className="workflow-end-node-n8n-label small">Kết thúc</div>
                        <span className="font-monospace text-muted" style={{ fontSize: "0.7rem" }}>
                          {END}
                        </span>
                      </div>
                    )}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <p className="small text-muted mt-4 mb-0">
              Nút <strong>Lưu lên MySQL</strong> gửi định nghĩa + <code>canvasView</code> (pan/zoom); <strong>không lưu tọa độ
              node</strong> — vị trí luôn tính lại theo thứ tự bước. Bảng transition (
              <code>workflow_transition_definition</code>) không chỉnh từ màn này (giữ seed / SQL).
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
