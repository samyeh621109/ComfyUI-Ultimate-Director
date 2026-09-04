const { app } = window.comfyAPI.app;
const { api } = window.comfyAPI.api;

const NODE_CLASS = "UltimateDirectorMediaDashboard";
const LEGACY_INPUTS = new Set([
  "storyboard_text",
  "storyboard_images",
  "reference_images",
  "reference_video_1",
  "reference_video_2",
  "reference_video_3",
  "reference_video_audio_1",
  "reference_video_audio_2",
  "reference_video_audio_3",
  "reference_audio_1",
  "reference_audio_2",
  "reference_audio_3",
]);
const LEGACY_OUTPUTS = new Set([
  "编译提示词",
  "帧数",
  "帧率",
  "输出宽度",
  "输出高度",
  "compiled_prompt",
  "frame_count",
  "frame_rate",
  "output_width",
  "output_height",
]);

function removeLegacyInputs(node) {
  for (let index = (node.inputs?.length || 0) - 1; index >= 0; index -= 1) {
    if (LEGACY_INPUTS.has(node.inputs[index]?.name)) node.removeInput(index);
  }
}

function removeLegacyOutputs(node) {
  for (let index = (node.outputs?.length || 0) - 1; index >= 0; index -= 1) {
    const output = node.outputs[index];
    if (LEGACY_OUTPUTS.has(output?.name) || LEGACY_OUTPUTS.has(output?.localized_name)) {
      node.removeOutput(index);
    }
  }
}
const STYLE_ID = "ultimate-director-style";

function getWidget(node, name) {
  return node.widgets?.find((widget) => widget.name === name);
}

function widgetValue(node, name, fallback) {
  const widget = getWidget(node, name);
  return widget?.value ?? fallback;
}

function hideWidget(widget) {
  if (!widget) return;
  widget.computeSize = () => [0, -4];
  widget.hidden = true;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Number(value) || 0));
}

function gridDimensions(node) {
  const match = String(widgetValue(node, "grid_layout", "3x2 六宫格")).match(/(\d+)\s*x\s*(\d+)/i);
  return match ? [Number(match[1]), Number(match[2])] : [3, 2];
}

function makeId(prefix = "ref") {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function mediaUrl(relativeName) {
  if (!relativeName) return "";
  const parts = String(relativeName).replace(/\\/g, "/").split("/");
  const filename = parts.pop();
  return api.apiURL(
    `/view?filename=${encodeURIComponent(filename)}&subfolder=${encodeURIComponent(parts.join("/"))}&type=input`
  );
}

function previewUrl(info) {
  if (!info) return "";
  const filename = info.filename || info.name || "";
  if (!filename) return "";
  return api.apiURL(
    `/view?filename=${encodeURIComponent(filename)}&subfolder=${encodeURIComponent(info.subfolder || "")}&type=${encodeURIComponent(info.type || "temp")}`
  );
}

function injectStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    .cs-h3-director { color: #e8e8e8; background: #151515; border: 1px solid #3a3a3a; font: 13px/1.45 system-ui, sans-serif; overflow: hidden; outline:none; }
    .cs-h3-director * { box-sizing: border-box; }
    .cs-h3-head { display:flex; align-items:center; gap:8px; padding:9px 10px; background:#202020; border-bottom:1px solid #3a3a3a; }
    .cs-h3-title { font-weight:700; color:#fff; margin-right:auto; }
    .cs-h3-summary { color:#a9d5b8; font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:62%; }
    .cs-h3-mode-switch { display:grid; grid-template-columns:1fr 1fr; gap:4px; padding:8px 10px; background:#191919; border-bottom:1px solid #333; }
    .cs-h3-mode-btn { border:1px solid #4a4a4a; background:#252525; color:#bbb; min-height:34px; border-radius:4px; cursor:pointer; font-weight:600; }
    .cs-h3-mode-btn:hover { background:#303030; color:#eee; }
    .cs-h3-mode-btn.active { background:#315f43; border-color:#70a982; color:#fff; }
    .cs-h3-toolbar { display:flex; flex-wrap:wrap; gap:6px; padding:8px 10px; border-bottom:1px solid #333; }
    .cs-h3-btn { border:1px solid #505050; background:#292929; color:#eee; min-height:30px; padding:4px 9px; border-radius:4px; cursor:pointer; }
    .cs-h3-btn:hover { background:#353535; border-color:#6a6a6a; }
    .cs-h3-btn.danger { color:#ffb7b7; }
    .cs-h3-section { padding:9px 10px; border-bottom:1px solid #303030; }
    .cs-h3-label { display:block; color:#c9c9c9; font-size:12px; margin-bottom:5px; }
    .cs-h3-textarea, .cs-h3-input { width:100%; border:1px solid #444; border-radius:4px; background:#111; color:#eee; padding:7px 8px; outline:none; }
    .cs-h3-textarea:focus, .cs-h3-input:focus { border-color:#6a9f7b; }
    .cs-h3-global { min-height:66px; resize:vertical; }
    .cs-h3-director.reference-layout .cs-h3-global { min-height:220px; }
    .cs-h3-ruler { display:flex; justify-content:space-between; color:#888; font-size:11px; padding:0 2px 4px; margin-left:119px; }
    .cs-h3-timeline-row { display:grid; grid-template-columns:112px minmax(0, 1fr); gap:7px; align-items:stretch; margin-top:6px; }
    .cs-h3-track-label { display:flex; align-items:center; justify-content:space-between; gap:5px; padding:6px; border:1px solid #3d3d3d; background:#1d1d1d; color:#cfcfcf; font-size:12px; font-weight:600; }
    .cs-h3-track-toggle { border:1px solid #555; background:#292929; color:#ddd; min-width:38px; height:24px; padding:2px 5px; border-radius:3px; cursor:pointer; font-size:11px; }
    .cs-h3-track-toggle.off { color:#999; background:#191919; border-color:#3b3b3b; }
    .cs-h3-timeline-row.disabled { opacity:.46; }
    .cs-h3-track { position:relative; height:178px; background:#0b0b0b; border:1px solid #3d3d3d; overflow:hidden; }
    .cs-h3-track.compact { height:66px; }
    .cs-h3-track::before { content:""; position:absolute; inset:0; background:repeating-linear-gradient(90deg, transparent 0, transparent calc(10% - 1px), #242424 10%); pointer-events:none; }
    .cs-h3-track.reference-mode { display:flex; gap:8px; align-items:stretch; height:142px; padding:8px; overflow-x:auto; }
    .cs-h3-track.reference-mode::before { display:none; }
    .cs-h3-track.reference-mode .cs-h3-playhead { display:none; }
    .cs-h3-card { position:absolute; top:8px; height:112px; min-width:58px; border:1px solid #555; background:#202020; overflow:hidden; cursor:pointer; border-radius:4px; }
    .cs-h3-track.reference-mode .cs-h3-card { position:relative; inset:auto; flex:0 0 150px; width:150px; height:124px; }
    .cs-h3-card.selected { border:2px solid #77b58a; box-shadow:0 0 0 1px #101010; }
    .cs-h3-card img, .cs-h3-card video { width:100%; height:72px; display:block; object-fit:cover; background:#090909; }
    .cs-h3-grid-thumb { width:100%; height:72px; background-repeat:no-repeat; background-color:#090909; }
    .cs-h3-placeholder { height:72px; display:flex; align-items:center; justify-content:center; color:#bbb; background:#1a2520; font-size:12px; }
    .cs-h3-card-meta { padding:4px 6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:#ddd; font-size:11px; }
    .cs-h3-audio-row { display:flex; gap:6px; min-height:42px; padding-top:7px; overflow-x:auto; }
    .cs-h3-timeline-card { position:absolute; top:8px; bottom:8px; min-width:46px; border:1px solid #555; background:#202020; overflow:hidden; cursor:grab; border-radius:4px; user-select:none; transition:box-shadow .12s ease, opacity .12s ease; }
    .cs-h3-timeline-card.selected { border:2px solid #77b58a; box-shadow:0 0 0 1px #101010; }
    .cs-h3-timeline-card.dragging { z-index:7; cursor:grabbing; opacity:.92; box-shadow:0 5px 18px rgba(0,0,0,.65), 0 0 0 2px #77b58a; }
    .cs-h3-timeline-card.motion { border-color:#55758a; background:#18242b; }
    .cs-h3-timeline-card.audio { border-color:#765c82; background:#2a202f; }
    .cs-h3-timeline-card img, .cs-h3-timeline-card video { width:100%; height:calc(100% - 29px); display:block; object-fit:cover; background:#090909; pointer-events:none; }
    .cs-h3-timeline-card .cs-h3-grid-thumb, .cs-h3-timeline-card .cs-h3-placeholder { height:calc(100% - 29px); }
    .cs-h3-resize-handle { position:absolute; top:0; right:0; width:10px; height:100%; cursor:ew-resize; background:linear-gradient(90deg, transparent, rgba(255,255,255,.22)); }
    .cs-h3-resize-handle.left { left:0; right:auto; background:linear-gradient(90deg, rgba(255,255,255,.18), transparent); }
    .cs-h3-playhead { position:absolute; z-index:8; top:0; bottom:0; width:12px; margin-left:-6px; cursor:ew-resize; touch-action:none; }
    .cs-h3-playhead::before { content:""; position:absolute; top:0; bottom:0; left:5px; width:2px; background:#ff4354; }
    .cs-h3-playhead::after { content:""; position:absolute; top:0; left:2px; width:8px; height:8px; background:#ff4354; clip-path:polygon(0 0,100% 0,50% 100%); }
    .cs-h3-playhead.dragging::before, .cs-h3-playhead.dragging::after { background:#ff7582; }
    .cs-h3-transport { margin-top:8px; padding:9px 10px; border:1px solid #3d3d3d; background:#1a1a1a; }
    .cs-h3-transport-info { display:flex; align-items:baseline; gap:14px; margin-bottom:8px; color:#9d9d9d; font-variant-numeric:tabular-nums; }
    .cs-h3-current-time { display:flex; align-items:center; color:#fff; font-size:16px; font-weight:700; min-width:108px; }
    .cs-h3-current-time-input { width:78px; box-sizing:border-box; padding:3px 6px; border:1px solid #555; border-radius:3px; background:#111; color:#fff; font:inherit; font-size:15px; text-align:right; font-variant-numeric:tabular-nums; }
    .cs-h3-current-time-input:focus { border-color:#ff4354; outline:none; box-shadow:0 0 0 1px #ff4354; }
    .cs-h3-current-time-unit { margin-left:2px; }
    .cs-h3-transport-controls { display:grid; grid-template-columns:34px 34px minmax(0, 1fr); gap:7px; align-items:center; }
    .cs-h3-transport-btn { width:34px; height:32px; padding:0; border:1px solid #505050; background:#292929; color:#fff; border-radius:4px; cursor:pointer; font-size:16px; }
    .cs-h3-transport-btn:hover { background:#353535; }
    .cs-h3-scrubber { width:100%; accent-color:#ff4354; cursor:pointer; }
    .cs-h3-audio-chip { flex:0 0 auto; max-width:210px; border:1px solid #5a5363; background:#27212d; color:#ddd; padding:7px 9px; border-radius:4px; cursor:pointer; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .cs-h3-audio-chip.selected { border-color:#b28ac7; }
    .cs-h3-editor { display:block; }
    .cs-h3-editor textarea { height:300px; min-height:300px; resize:vertical; }
    .cs-h3-empty { color:#888; padding:14px 4px; text-align:center; }
    .cs-h3-check { display:flex; align-items:center; gap:7px; min-height:32px; color:#ddd; }
    .cs-h3-output { max-height:86px; overflow:auto; white-space:pre-wrap; color:#bfc8bf; background:#101210; border:1px solid #333; padding:7px 8px; border-radius:4px; }
  `;
  document.head.appendChild(style);
}

function emptyState() {
  return {
    version: 5,
    updatedAt: 0,
    globalPrompt: "",
    allReferencePrompt: "",
    gridImage: null,
    items: [],
    selectedId: null,
    motionTrackEnabled: true,
    audioTrackEnabled: true,
    hiddenStoryboardIndices: [],
  };
}

function normalizeState(value) {
  try {
    const parsed = typeof value === "string" ? JSON.parse(value || "{}") : value;
    if (!parsed || typeof parsed !== "object") return emptyState();
    return {
      version: Number.isFinite(Number(parsed.version)) ? Number(parsed.version) : 4,
      updatedAt: Number.isFinite(Number(parsed.updatedAt)) ? Number(parsed.updatedAt) : 0,
      globalPrompt: String(parsed.globalPrompt || ""),
      allReferencePrompt: String(parsed.allReferencePrompt || ""),
      gridImage: parsed.gridImage && typeof parsed.gridImage === "object" ? parsed.gridImage : null,
      items: Array.isArray(parsed.items) ? parsed.items.filter(Boolean) : [],
      selectedId: parsed.selectedId || null,
      motionTrackEnabled: parsed.motionTrackEnabled !== false,
      audioTrackEnabled: parsed.audioTrackEnabled !== false,
      hiddenStoryboardIndices: Array.isArray(parsed.hiddenStoryboardIndices)
        ? parsed.hiddenStoryboardIndices.map(Number).filter(Number.isFinite)
        : [],
    };
  } catch (_) {
    return emptyState();
  }
}

function hasStateContent(state) {
  return !!(
    state.globalPrompt ||
    state.allReferencePrompt ||
    state.gridImage ||
    state.items.length ||
    state.selectedId ||
    state.motionTrackEnabled === false ||
    state.audioTrackEnabled === false
    || state.hiddenStoryboardIndices.length
  );
}

function workflowSessionKey(node) {
  const activeTab = document.querySelector('button[data-pc-name="pctogglebutton"][aria-pressed="true"]');
  const workflowId = String(activeTab?.textContent || "workflow")
    .replace(/[•×]/g, "")
    .trim();
  const position = Array.isArray(node.pos) ? node.pos.map((value) => Math.round(Number(value) || 0)).join(",") : "0,0";
  const nodeId = Number(node.id) >= 0 ? node.id : `${node.type || NODE_CLASS}@${position}`;
  return `cs_h3_director:${workflowId}:${nodeId}`;
}

function readSessionState(storageKey) {
  try {
    return window.sessionStorage?.getItem(storageKey) || "";
  } catch (_) {
    return "";
  }
}

function loadPersistedState(node, dataWidget, serializedWidget = null, storageKey = "") {
  const candidates = [
    normalizeState(node.properties?.csH3Timeline),
    normalizeState(dataWidget?.value),
    normalizeState(serializedWidget?.value),
    normalizeState(readSessionState(storageKey)),
  ];
  const newest = Math.max(...candidates.map((state) => state.updatedAt));
  const current = candidates.filter((state) => state.updatedAt === newest);
  return current.find(hasStateContent) || current[0];
}

class H3DirectorUI {
  constructor(node, root) {
    this.node = node;
    this.root = root;
    this.dataWidget = getWidget(node, "dashboard_data");
    this.promptWidget = getWidget(node, "global_prompt");
    this.serializedWidget = getWidget(node, "cs_h3_director_ui");
    this.storageKey = workflowSessionKey(node);
    const modeWidget = getWidget(node, "mode");
    if (modeWidget && !["宮格模式", "全能參考", "宫格模式", "全能参考"].includes(modeWidget.value)) modeWidget.value = "宮格模式";
    this.state = loadPersistedState(node, this.dataWidget, this.serializedWidget, this.storageKey);
    if (!this.state.globalPrompt && this.promptWidget?.value) this.state.globalPrompt = String(this.promptWidget.value);
    if (!this.state.allReferencePrompt && (this.mode === "全能參考" || this.mode === "全能参考")) {
      this.state.allReferencePrompt = this.state.globalPrompt;
    }
    this.compiledPrompt = "運行後將在這裡顯示最終編譯提示詞。";
    this.summary = "等待新增參考素材";
    this.storyboardPreviews = [];
    this.playheadSeconds = 0;
    this.playing = false;
    this.build();
    this.hookWidgets();
    if ((this.mode === "宮格模式" || this.mode === "宫格模式") && !this.state.items.some((item) => item.source === "storyboard")) {
      this.createStoryboardSlots(false);
    }
    if (this.state.version < 5) this.migrateVisualTrackLayout(false);
    this.render();
  }

  get totalSeconds() {
    return clamp(widgetValue(this.node, "duration_seconds", 5), 4, 15);
  }

  get selected() {
    return this.activeItems.find((item) => item.id === this.state.selectedId) || null;
  }

  get mode() {
    const value = widgetValue(this.node, "mode", "宮格模式");
    return (value === "全能參考" || value === "全能参考") ? "全能參考" : "宮格模式";
  }

  get activeItems() {
    const gridMode = this.mode === "宮格模式" || this.mode === "宫格模式";
    return this.state.items.filter((item) => {
      if (item.source === "storyboard") return gridMode;
      const scope = item.scope || "reference";
      return gridMode ? scope === "grid" : scope !== "grid";
    });
  }

  itemTrack(item) {
    if (item.source === "storyboard") return "visual";
    if (item.track) return item.track;
    if (item.kind === "audio") return (this.mode === "宮格模式" || this.mode === "宫格模式") ? "audio" : "reference";
    return (this.mode === "宮格模式" || this.mode === "宫格模式") ? "visual" : "reference";
  }

  build() {
    this.root.className = "cs-h3-director";
    this.root.tabIndex = 0;
    this.root.innerHTML = "";
    this.deleteShortcutHandler = (event) => {
      if (!this.root.isConnected) {
        document.removeEventListener("keydown", this.deleteShortcutHandler, true);
        return;
      }
      if (document.activeElement !== this.root && !this.root.contains(event.target)) return;
      const target = event.target;
      const editingText = target instanceof HTMLInputElement
        || target instanceof HTMLTextAreaElement
        || target?.isContentEditable;
      if (editingText || !["Backspace", "Delete"].includes(event.key)) return;
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      if (this.state.selectedId) this.removeSelected();
    };
    this.deleteShortcutReleaseHandler = (event) => {
      if (!this.root.isConnected) {
        document.removeEventListener("keyup", this.deleteShortcutReleaseHandler, true);
        return;
      }
      if (document.activeElement !== this.root || !["Backspace", "Delete"].includes(event.key)) return;
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
    };
    document.addEventListener("keydown", this.deleteShortcutHandler, true);
    document.addEventListener("keyup", this.deleteShortcutReleaseHandler, true);

    const head = document.createElement("div");
    head.className = "cs-h3-head";
    this.titleEl = document.createElement("span");
    this.titleEl.className = "cs-h3-title";
    this.summaryEl = document.createElement("span");
    this.summaryEl.className = "cs-h3-summary";
    head.append(this.titleEl, this.summaryEl);
    this.root.appendChild(head);

    const modeSwitch = document.createElement("div");
    modeSwitch.className = "cs-h3-mode-switch";
    this.modeButtons = new Map();
    for (const mode of ["宮格模式", "全能參考"]) {
      const button = document.createElement("button");
      button.className = "cs-h3-mode-btn";
      button.textContent = mode;
      button.title = mode === "宮格模式"
        ? "拆分四宮格、六宮格或九宮格，並按分鏡文字產生時間線"
        : "使用普通圖片、影片與音訊作為 H3 多模態參考";
      button.addEventListener("click", () => this.setMode(mode));
      this.modeButtons.set(mode, button);
      modeSwitch.appendChild(button);
    }
    this.root.appendChild(modeSwitch);

    const toolbar = document.createElement("div");
    toolbar.className = "cs-h3-toolbar";
    this.referenceControls = [
      this.addToolbarButton(toolbar, "＋ 圖片", "新增一張或多張參考圖片", "image"),
      this.addToolbarButton(toolbar, "＋ 影片", "新增最多三段參考影片", "video"),
      this.addToolbarButton(toolbar, "＋ 音訊", "新增參考聲音或音色", "audio"),
    ];
    this.gridControls = [
      this.addGridUploadButton(toolbar),
      this.addToolbarButton(toolbar, "＋ 單張圖片", "向主畫面軌道新增一張或多張獨立圖片", "image", "visual"),
      this.addToolbarButton(toolbar, "＋ 動作參考", "向動作參考軌道新增影片", "video", "motion"),
      this.addToolbarButton(toolbar, "＋ 音訊", "向音訊軌道新增聲音", "audio", "audio"),
    ];
    this.deleteButton = this.addActionButton(toolbar, "刪除", "刪除當前選取的參考素材", () => this.removeSelected(), "danger");
    this.root.appendChild(toolbar);

    this.globalSection = document.createElement("div");
    this.globalSection.className = "cs-h3-section";
    this.globalLabel = document.createElement("label");
    this.globalLabel.className = "cs-h3-label";
    this.globalInput = document.createElement("textarea");
    this.globalInput.className = "cs-h3-textarea cs-h3-global";
    this.globalInput.placeholder = "整體風格、人物一致性、畫面質感、聲音氛圍和必須遵守的要求……";
    this.globalInput.addEventListener("input", () => {
      this.persistPromptInput();
      this.save();
    });
    this.globalInput.addEventListener("blur", () => {
      this.save();
      clearTimeout(this.workflowCaptureTimer);
      this.notifyWorkflowChanged();
    });
    this.globalSection.append(this.globalLabel, this.globalInput);
    this.root.appendChild(this.globalSection);

    this.timelineSection = document.createElement("div");
    this.timelineSection.className = "cs-h3-section";
    this.ruler = document.createElement("div");
    this.ruler.className = "cs-h3-ruler";
    this.track = document.createElement("div");
    this.track.className = "cs-h3-track";
    this.visualRow = this.makeTimelineRow("主畫面軌道", this.track);
    this.motionTrack = document.createElement("div");
    this.motionTrack.className = "cs-h3-track compact";
    this.motionRow = this.makeTimelineRow("動作參考", this.motionTrack, "motion");
    this.audioTrack = document.createElement("div");
    this.audioTrack.className = "cs-h3-track compact";
    this.audioTrackRow = this.makeTimelineRow("音訊", this.audioTrack, "audio");
    this.audioRow = document.createElement("div");
    this.audioRow.className = "cs-h3-audio-row";
    this.transport = document.createElement("div");
    this.transport.className = "cs-h3-transport";
    const transportInfo = document.createElement("div");
    transportInfo.className = "cs-h3-transport-info";
    this.currentTimeEl = document.createElement("label");
    this.currentTimeEl.className = "cs-h3-current-time";
    this.currentTimeInput = document.createElement("input");
    this.currentTimeInput.className = "cs-h3-current-time-input";
    this.currentTimeInput.type = "number";
    this.currentTimeInput.min = "0";
    this.currentTimeInput.step = "0.01";
    this.currentTimeInput.title = "輸入當前播放時間，按 Enter 確認";
    const currentTimeUnit = document.createElement("span");
    currentTimeUnit.className = "cs-h3-current-time-unit";
    currentTimeUnit.textContent = "秒";
    this.currentTimeInput.addEventListener("focus", () => this.stopPlayback());
    this.currentTimeInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        this.commitCurrentTimeInput();
        this.currentTimeInput.blur();
      } else if (event.key === "Escape") {
        event.preventDefault();
        this.currentTimeInput.value = this.playheadSeconds.toFixed(2);
        this.currentTimeInput.blur();
      }
    });
    this.currentTimeInput.addEventListener("blur", () => this.commitCurrentTimeInput());
    this.currentTimeEl.append(this.currentTimeInput, currentTimeUnit);
    this.rangeInfoEl = document.createElement("span");
    transportInfo.append(this.currentTimeEl, this.rangeInfoEl);
    const transportControls = document.createElement("div");
    transportControls.className = "cs-h3-transport-controls";
    this.playButton = document.createElement("button");
    this.playButton.className = "cs-h3-transport-btn";
    this.playButton.textContent = "▶";
    this.playButton.title = "播放时间轴";
    this.playButton.addEventListener("click", () => this.togglePlayback());
    this.resetButton = document.createElement("button");
    this.resetButton.className = "cs-h3-transport-btn";
    this.resetButton.textContent = "↻";
    this.resetButton.title = "返回时间轴起点";
    this.resetButton.addEventListener("click", () => {
      this.stopPlayback();
      this.setPlayhead(0);
    });
    this.scrubber = document.createElement("input");
    this.scrubber.className = "cs-h3-scrubber";
    this.scrubber.type = "range";
    this.scrubber.min = "0";
    this.scrubber.step = "0.01";
    this.scrubber.addEventListener("input", () => {
      this.stopPlayback();
      this.setPlayhead(this.snapPlayheadTime(Number(this.scrubber.value || 0), this.scrubber.clientWidth));
    });
    transportControls.append(this.playButton, this.resetButton, this.scrubber);
    this.transport.append(transportInfo, transportControls);
    this.timelineSection.append(this.ruler, this.visualRow, this.motionRow, this.audioTrackRow, this.audioRow, this.transport);
    this.root.appendChild(this.timelineSection);

    this.editorSection = document.createElement("div");
    this.editorSection.className = "cs-h3-section";
    this.root.appendChild(this.editorSection);

    this.outputSection = document.createElement("div");
    this.outputSection.className = "cs-h3-section";
    const outputLabel = document.createElement("span");
    outputLabel.className = "cs-h3-label";
    outputLabel.textContent = "H3最终提示词预览";
    this.outputEl = document.createElement("div");
    this.outputEl.className = "cs-h3-output";
    this.outputSection.append(outputLabel, this.outputEl);
    this.root.appendChild(this.outputSection);
  }

  makeTimelineRow(labelText, track, toggleType = "") {
    const row = document.createElement("div");
    row.className = "cs-h3-timeline-row";
    const label = document.createElement("div");
    label.className = "cs-h3-track-label";
    const name = document.createElement("span");
    name.textContent = labelText;
    label.appendChild(name);
    if (toggleType) {
      const toggle = document.createElement("button");
      toggle.className = "cs-h3-track-toggle";
      toggle.addEventListener("click", () => this.toggleTrack(toggleType));
      label.appendChild(toggle);
      if (toggleType === "motion") this.motionToggle = toggle;
      if (toggleType === "audio") this.audioToggle = toggle;
    }
    row.append(label, track);
    track.addEventListener("pointerdown", (event) => {
      if (this.mode === "全能参考") return;
      if (event.target !== track && !event.target.classList?.contains("cs-h3-empty")) return;
      const rect = track.getBoundingClientRect();
      const rawSeconds = (event.clientX - rect.left) / Math.max(1, rect.width) * this.totalSeconds;
      const seconds = this.snapPlayheadTime(rawSeconds, rect.width);
      this.stopPlayback(false);
      this.setPlayhead(seconds);
    });
    return row;
  }

  trackEnabled(type) {
    return type === "motion" ? this.state.motionTrackEnabled !== false : this.state.audioTrackEnabled !== false;
  }

  toggleTrack(type) {
    if (type === "motion") this.state.motionTrackEnabled = !this.trackEnabled("motion");
    if (type === "audio") this.state.audioTrackEnabled = !this.trackEnabled("audio");
    this.save();
    this.render();
  }

  setPlayhead(seconds, shouldRender = true) {
    this.playheadSeconds = clamp(seconds, 0, this.totalSeconds);
    if (shouldRender) this.renderPlayheads();
  }

  commitCurrentTimeInput() {
    const value = Number(this.currentTimeInput?.value);
    if (Number.isFinite(value)) this.setPlayhead(value);
    if (this.currentTimeInput) this.currentTimeInput.value = this.playheadSeconds.toFixed(2);
  }

  togglePlayback() {
    if (this.playing) {
      this.stopPlayback();
      return;
    }
    if (this.playheadSeconds >= this.totalSeconds - 0.001) this.playheadSeconds = 0;
    this.playing = true;
    let previous = performance.now();
    const tick = (now) => {
      if (!this.playing) return;
      this.playheadSeconds += Math.max(0, now - previous) / 1000;
      previous = now;
      if (this.playheadSeconds >= this.totalSeconds) {
        this.playheadSeconds = this.totalSeconds;
        this.stopPlayback(false);
      }
      this.renderPlayheads();
      if (this.playing) this.playbackFrame = requestAnimationFrame(tick);
    };
    this.renderPlayheads();
    this.playbackFrame = requestAnimationFrame(tick);
  }

  stopPlayback(updateControls = true) {
    this.playing = false;
    if (this.playbackFrame) cancelAnimationFrame(this.playbackFrame);
    this.playbackFrame = 0;
    if (updateControls) this.renderPlayheads();
  }

  renderPlayheads() {
    if (this.mode === "全能参考") {
      for (const track of [this.track, this.motionTrack, this.audioTrack]) {
        track.querySelectorAll(".cs-h3-playhead").forEach((playhead) => playhead.remove());
      }
      return;
    }
    const percent = this.totalSeconds > 0 ? this.playheadSeconds / this.totalSeconds * 100 : 0;
    for (const track of [this.track, this.motionTrack, this.audioTrack]) {
      let playhead = track.querySelector(".cs-h3-playhead");
      if (!playhead) {
        playhead = document.createElement("div");
        playhead.className = "cs-h3-playhead";
        this.bindPlayheadDrag(playhead, track);
        track.appendChild(playhead);
      }
      playhead.style.left = `${percent}%`;
    }
    if (this.currentTimeInput && document.activeElement !== this.currentTimeInput) {
      this.currentTimeInput.max = String(this.totalSeconds);
      this.currentTimeInput.value = this.playheadSeconds.toFixed(2);
    }
    if (this.rangeInfoEl) {
      this.rangeInfoEl.textContent = `开始：0.00｜结束：${this.totalSeconds.toFixed(2)}｜总长：${this.totalSeconds.toFixed(2)}秒`;
    }
    if (this.scrubber) {
      this.scrubber.max = String(this.totalSeconds);
      this.scrubber.value = String(this.playheadSeconds);
    }
    if (this.playButton) {
      this.playButton.textContent = this.playing ? "Ⅱ" : "▶";
      this.playButton.title = this.playing ? "暂停时间轴" : "播放时间轴";
    }
  }

  bindPlayheadDrag(playhead, track) {
    playhead.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      this.stopPlayback(false);
      playhead.classList.add("dragging");
      playhead.setPointerCapture?.(event.pointerId);
      const move = (moveEvent) => {
        const rect = track.getBoundingClientRect();
        const rawSeconds = (moveEvent.clientX - rect.left) / Math.max(1, rect.width) * this.totalSeconds;
        const seconds = this.snapPlayheadTime(rawSeconds, rect.width);
        this.setPlayhead(seconds);
      };
      const finish = () => {
        playhead.classList.remove("dragging");
        playhead.removeEventListener("pointermove", move);
        playhead.removeEventListener("pointerup", finish);
        playhead.removeEventListener("pointercancel", finish);
      };
      playhead.addEventListener("pointermove", move);
      playhead.addEventListener("pointerup", finish);
      playhead.addEventListener("pointercancel", finish);
    });
  }

  snapTime(value, currentItem = null, ignoredIds = []) {
    const ignored = new Set(ignoredIds.map(String));
    const candidates = [0, this.totalSeconds, this.playheadSeconds];
    for (const item of this.activeItems) {
      if (item === currentItem || ignored.has(String(item.id))) continue;
      candidates.push(Number(item.start || 0));
      candidates.push(Number(item.start || 0) + Number(item.duration || 0));
    }
    const rounded = Math.round(Number(value || 0) * 10) / 10;
    let snapped = rounded;
    for (const candidate of candidates) {
      if (Math.abs(candidate - value) <= 0.12) {
        snapped = candidate;
        break;
      }
    }
    return clamp(snapped, 0, this.totalSeconds);
  }

  snapPlayheadTime(value, trackWidth = 1000) {
    const candidates = [0, this.totalSeconds];
    for (const item of this.activeItems) {
      if (this.itemTrack(item) !== "visual") continue;
      candidates.push(Number(item.start || 0));
      candidates.push(Number(item.start || 0) + Number(item.duration || 0));
    }
    const threshold = Math.max(0.04, 12 / Math.max(1, trackWidth) * this.totalSeconds);
    let best = clamp(value, 0, this.totalSeconds);
    let bestDistance = threshold;
    for (const candidate of candidates) {
      const distance = Math.abs(candidate - value);
      if (distance <= bestDistance) {
        best = candidate;
        bestDistance = distance;
      }
    }
    return clamp(best, 0, this.totalSeconds);
  }

  resolveVisualTrackDrag(draggedItem, desiredStart, cursorSeconds, initialItems) {
    const dragged = initialItems.find((item) => item.id === draggedItem.id);
    if (!dragged) return;
    const base = initialItems
      .filter((item) => item.id !== dragged.id)
      .sort((a, b) => a.start - b.start)
      .map((item) => ({ ...item, originalStart: item.start }));
    let insertIndex = base.length;
    for (let index = 0; index < base.length; index += 1) {
      if (cursorSeconds < base[index].start + base[index].duration / 2) {
        insertIndex = index;
        break;
      }
    }

    const leftBound = insertIndex > 0
      ? base[insertIndex - 1].start + base[insertIndex - 1].duration
      : 0;
    const rightBound = insertIndex < base.length ? base[insertIndex].start : this.totalSeconds;
    let resolvedStart = clamp(desiredStart, 0, Math.max(0, this.totalSeconds - dragged.duration));
    if (rightBound - leftBound >= dragged.duration) {
      resolvedStart = clamp(resolvedStart, leftBound, rightBound - dragged.duration);
    } else {
      resolvedStart = (leftBound + rightBound - dragged.duration) / 2;
    }

    const arranged = [
      ...base.slice(0, insertIndex),
      { ...dragged, start: resolvedStart, originalStart: resolvedStart },
      ...base.slice(insertIndex),
    ];
    for (let index = insertIndex + 1; index < arranged.length; index += 1) {
      const previous = arranged[index - 1];
      arranged[index].start = Math.max(
        arranged[index].originalStart,
        previous.start + previous.duration
      );
    }
    for (let index = insertIndex - 1; index >= 0; index -= 1) {
      const next = arranged[index + 1];
      arranged[index].start = Math.min(
        arranged[index].originalStart,
        next.start - arranged[index].duration
      );
    }

    let rightCursor = this.totalSeconds;
    for (let index = arranged.length - 1; index >= 0; index -= 1) {
      arranged[index].start = Math.min(arranged[index].start, rightCursor - arranged[index].duration);
      rightCursor = arranged[index].start;
    }
    let leftCursor = 0;
    for (const segment of arranged) {
      segment.start = Math.max(segment.start, leftCursor);
      leftCursor = segment.start + segment.duration;
    }

    const liveItems = new Map(this.activeItems.map((item) => [item.id, item]));
    for (const segment of arranged) {
      const live = liveItems.get(segment.id);
      if (live) live.start = clamp(segment.start, 0, Math.max(0, this.totalSeconds - segment.duration));
    }
  }

  updateTrackCardPositions(track) {
    const items = new Map(this.activeItems.map((item) => [item.id, item]));
    for (const card of track.querySelectorAll(".cs-h3-timeline-card")) {
      const item = items.get(card.dataset.itemId);
      if (!item) continue;
      const start = clamp(item.start, 0, this.totalSeconds);
      const duration = clamp(item.duration, 0.1, this.totalSeconds - start || 0.1);
      card.style.left = `${start / this.totalSeconds * 100}%`;
      card.style.width = `${Math.max(3, duration / this.totalSeconds * 100)}%`;
    }
  }

  findVisualPlacement(visualItems) {
    const occupied = visualItems
      .map((item) => ({
        start: clamp(Number(item.start || 0), 0, this.totalSeconds),
        end: clamp(Number(item.start || 0) + Number(item.duration || 0.1), 0, this.totalSeconds),
      }))
      .sort((a, b) => a.start - b.start);
    const gaps = [];
    let cursor = 0;
    for (const segment of occupied) {
      if (segment.start > cursor) gaps.push({ start: cursor, duration: segment.start - cursor });
      cursor = Math.max(cursor, segment.end);
    }
    if (cursor < this.totalSeconds) gaps.push({ start: cursor, duration: this.totalSeconds - cursor });
    const gap = gaps.sort((a, b) => b.duration - a.duration)[0];
    if (!gap || gap.duration < 0.1) return null;
    const preferredDuration = Math.min(2.5, this.totalSeconds / (visualItems.length + 2));
    return {
      start: gap.start,
      duration: Math.max(0.1, Math.min(preferredDuration, gap.duration)),
    };
  }

  addToolbarButton(parent, text, title, kind, track = "reference") {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.hidden = true;
    input.accept = kind === "image" ? "image/*" : kind === "video" ? "video/*" : "audio/*";
    input.addEventListener("change", async () => {
      const files = Array.from(input.files || []);
      input.value = "";
      await this.upload(files, kind, track);
    });
    const button = document.createElement("button");
    button.className = "cs-h3-btn";
    button.textContent = text;
    button.title = title;
    button.addEventListener("click", () => input.click());
    parent.append(button, input);
    return button;
  }

  addActionButton(parent, text, title, action, extraClass = "") {
    const button = document.createElement("button");
    button.className = `cs-h3-btn ${extraClass}`.trim();
    button.textContent = text;
    button.title = title;
    button.addEventListener("click", action);
    parent.appendChild(button);
    return button;
  }

  addGridUploadButton(parent) {
    const input = document.createElement("input");
    input.type = "file";
    input.hidden = true;
    input.accept = "image/*";
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      input.value = "";
      if (file) await this.importGridImage(file);
    });
    const button = document.createElement("button");
    button.className = "cs-h3-btn";
    button.textContent = "匯入宮格圖";
    button.title = "直接匯入四宮格、六宮格或九宮格圖片並立即預覽";
    button.addEventListener("click", () => input.click());
    parent.append(button, input);
    return button;
  }

  async importGridImage(file) {
    this.summary = `正在匯入宮格圖：${file.name}`;
    this.renderSummary();
    const form = new FormData();
    form.append("file", file, file.name);
    try {
      const response = await api.fetchApi("/ultimate_director/upload", { method: "POST", body: form });
      const result = await response.json();
      if (!response.ok || result.error) throw new Error(result.error || `上傳失敗：${response.status}`);
      if (result.kind !== "image") throw new Error("宮格模式只能匯入圖片檔案。");
      this.state.gridImage = {
        file: result.name,
        name: result.original_name || file.name,
        width: result.width || 0,
        height: result.height || 0,
      };
      this.storyboardPreviews = [];
      this.createStoryboardSlots(false);
      this.summary = "等待新增參考素材";
      this.save();
      this.render();
    } catch (error) {
      this.summary = `匯入失敗：${String(error?.message || error)}`;
      this.renderSummary();
    }
  }

  setMode(mode) {
    const nextMode = (mode === "全能參考" || mode === "全能参考") ? "全能參考" : "宮格模式";
    this.persistPromptInput(this.mode);
    const widget = getWidget(this.node, "mode");
    if (widget) widget.value = nextMode;
    this.syncPromptEditor(true);
    if ((nextMode === "宮格模式" || nextMode === "宫格模式") && !this.state.items.some((item) => item.source === "storyboard")) {
      this.createStoryboardSlots(false);
    }
    if (!this.selected) this.state.selectedId = this.activeItems[0]?.id || null;
    this.save();
    this.render();
  }

  persistPromptInput(mode = this.mode) {
    if (!this.globalInput) return;
    if (mode === "全能參考" || mode === "全能参考") {
      this.state.allReferencePrompt = this.globalInput.value;
    } else {
      this.state.globalPrompt = this.globalInput.value;
      if (this.promptWidget) this.promptWidget.value = this.globalInput.value;
    }
  }

  syncPromptEditor(force = false) {
    if (!this.globalInput || (!force && document.activeElement === this.globalInput)) return;
    if (this.mode === "全能參考" || this.mode === "全能参考") {
      this.globalLabel.textContent = "全能參考提示詞";
      this.globalInput.placeholder = "點擊下方素材插入 @圖片1、@影片1、@音訊1，再描述主體、動作、運鏡、臺詞和聲音……";
      this.globalInput.value = this.state.allReferencePrompt || "";
    } else {
      this.globalLabel.textContent = "全域創作要求";
      this.globalInput.placeholder = "整體風格、人物一致性、畫面質感、聲音氛圍和必須遵守的要求……";
      this.globalInput.value = this.state.globalPrompt || "";
    }
  }

  referenceToken(item, items = this.activeItems) {
    const labels_tw = { image: "圖片", video: "影片", audio: "音訊" };
    const sameKind = items.filter((candidate) => candidate.kind === item.kind);
    const index = sameKind.findIndex((candidate) => candidate.id === item.id);
    return index >= 0 && labels_tw[item.kind] ? `@${labels_tw[item.kind]}${index + 1}` : "";
  }

  insertReferenceToken(item) {
    const token = this.referenceToken(item);
    if (!token || (this.mode !== "全能參考" && this.mode !== "全能参考")) return;
    const input = this.globalInput;
    const start = Number.isFinite(input.selectionStart) ? input.selectionStart : input.value.length;
    const end = Number.isFinite(input.selectionEnd) ? input.selectionEnd : start;
    const before = input.value.slice(0, start);
    const after = input.value.slice(end);
    const leftSpace = before && !/\s$/.test(before) ? " " : "";
    const rightSpace = after && !/^\s/.test(after) ? " " : "";
    const inserted = `${leftSpace}${token}${rightSpace}`;
    input.value = before + inserted + after;
    const cursor = before.length + inserted.length;
    input.focus();
    input.setSelectionRange(cursor, cursor);
    this.state.allReferencePrompt = input.value;
    this.state.selectedId = item.id;
    this.save();
    this.renderTrack();
  }

  updateModeUI() {
    for (const [mode, button] of this.modeButtons || []) {
      button.classList.toggle("active", mode === this.mode);
    }
    for (const button of this.referenceControls || []) button.hidden = this.mode !== "全能參考" && this.mode !== "全能参考";
    for (const button of this.gridControls || []) button.hidden = this.mode !== "宮格模式" && this.mode !== "宫格模式";
    this.deleteButton.hidden = this.mode !== "全能參考" && this.mode !== "全能参考";
    this.titleEl.textContent = (this.mode === "宮格模式" || this.mode === "宫格模式") ? "宮格分鏡時間線" : "全能參考素材畫布";
    const referenceMode = this.mode === "全能參考" || this.mode === "全能参考";
    this.root.classList.toggle("reference-layout", referenceMode);
    if (referenceMode) {
      this.root.insertBefore(this.globalSection, this.editorSection);
    } else {
      this.root.insertBefore(this.globalSection, this.timelineSection);
    }
    this.ruler.style.display = referenceMode ? "none" : "flex";
    this.visualRow.classList.toggle("cs-h3-reference-row", referenceMode);
    this.visualRow.style.display = "grid";
    this.visualRow.querySelector(".cs-h3-track-label").style.display = referenceMode ? "none" : "flex";
    this.visualRow.style.gridTemplateColumns = referenceMode ? "minmax(0, 1fr)" : "112px minmax(0, 1fr)";
    this.motionRow.style.display = referenceMode ? "none" : "grid";
    this.audioTrackRow.style.display = referenceMode ? "none" : "grid";
    this.audioRow.style.display = referenceMode ? "flex" : "none";
    this.transport.style.display = referenceMode ? "none" : "block";
    const motionEnabled = this.trackEnabled("motion");
    const audioEnabled = this.trackEnabled("audio");
    this.motionRow.classList.toggle("disabled", !motionEnabled);
    this.audioTrackRow.classList.toggle("disabled", !audioEnabled);
    this.motionToggle.classList.toggle("off", !motionEnabled);
    this.audioToggle.classList.toggle("off", !audioEnabled);
    this.motionToggle.textContent = motionEnabled ? "啟用" : "停用";
    this.audioToggle.textContent = audioEnabled ? "啟用" : "靜音";
    this.motionToggle.title = motionEnabled ? "關閉動作參考軌道" : "啟用動作參考軌道";
    this.audioToggle.title = audioEnabled ? "靜音所有參考聲音" : "啟用參考聲音";
    if (referenceMode && this.playing) this.stopPlayback(false);
    this.editorSection.style.display = referenceMode ? "none" : "block";
    this.track.classList.toggle("reference-mode", this.mode === "全能參考" || this.mode === "全能参考");
    this.syncPromptEditor();
  }

  hookWidgets() {
    for (const name of ["duration_seconds", "mode", "grid_layout"]) {
      const widget = getWidget(this.node, name);
      if (!widget || widget._csH3Hooked) continue;
      const original = widget.callback;
      widget.callback = (...args) => {
        const result = original?.apply(widget, args);
        if (name === "duration_seconds") this.autoArrange(false);
        if (name === "grid_layout" && this.mode === "宫格模式") this.createStoryboardSlots(false);
        if (name === "mode" && !this.selected) this.state.selectedId = this.activeItems[0]?.id || null;
        this.render();
        return result;
      };
      widget._csH3Hooked = true;
    }
  }

  async upload(files, requestedKind, requestedTrack = "reference") {
    if (!files.length) return;
    const gridMode = this.mode === "宫格模式";
    if (!gridMode && requestedTrack !== "reference") return;
    this.summary = `正在上传 ${files.length} 个素材……`;
    this.renderSummary();
    const uploadErrors = [];
    let shouldAutoArrangeVisuals = false;
    for (const file of files) {
      const form = new FormData();
      form.append("file", file, file.name);
      try {
        const response = await api.fetchApi("/ultimate_director/upload", { method: "POST", body: form });
        const result = await response.json();
        if (!response.ok || result.error) throw new Error(result.error || `上传失败：${response.status}`);
        const kind = result.kind || requestedKind;
        if (requestedTrack === "motion" && kind !== "video") throw new Error("动作参考轨道只接受视频文件。");
        const track = gridMode ? requestedTrack : "reference";
        const scopedItems = this.state.items.filter((item) => item.scope === (gridMode ? "grid" : "reference"));
        const visualItems = scopedItems.filter((item) => item.track === track && (item.kind === "image" || item.kind === "video"));
        const lastEnd = visualItems.reduce((end, item) => Math.max(end, Number(item.start || 0) + Number(item.duration || 0)), 0);
        const visualPlacement = gridMode && requestedTrack === "visual"
          ? this.findVisualPlacement(visualItems)
          : null;
        if (gridMode && requestedTrack === "visual" && !visualPlacement) shouldAutoArrangeVisuals = true;
        const item = {
          id: makeId(kind),
          kind,
          file: result.name,
          name: result.original_name || file.name,
          width: result.width || 0,
          height: result.height || 0,
          mediaDuration: result.duration || 0,
          hasAudio: !!result.has_audio,
          includeAudio: kind === "video" && !!result.has_audio,
          scope: gridMode ? "grid" : "reference",
          track,
          start: kind === "audio"
            ? 0
            : visualPlacement?.start ?? Math.min(lastEnd, Math.max(0, this.totalSeconds - 0.5)),
          duration: kind === "audio"
            ? this.totalSeconds
            : visualPlacement?.duration ?? Math.min(2.5, this.totalSeconds),
          prompt: "",
          sound: "",
        };
        this.state.items.push(item);
        this.state.selectedId = item.id;
      } catch (error) {
        uploadErrors.push(String(error?.message || error));
        this.summary = `上传失败：${uploadErrors.join("；")}`;
        this.renderSummary();
      }
    }
    if (!uploadErrors.length) this.summary = "素材已添加";
    if (!gridMode || (requestedTrack === "visual" && shouldAutoArrangeVisuals)) this.autoArrange(false);
    this.save();
    this.render();
  }

  createStoryboardSlots(shouldRender = true) {
    const [cols, rows] = gridDimensions(this.node);
    const count = cols * rows;
    const previous = new Map(
      this.state.items
        .filter((item) => item.source === "storyboard")
        .map((item) => [Number(item.gridIndex), item])
    );
    this.state.items = this.state.items.filter((item) => item.source !== "storyboard");
    this.state.hiddenStoryboardIndices = [];
    const duration = this.totalSeconds / (count + 1);
    for (let index = 0; index < count; index += 1) {
      const old = previous.get(index) || {};
      this.state.items.push({
        id: `storyboard_${index}`,
        source: "storyboard",
        scope: "grid",
        track: "visual",
        gridIndex: index,
        kind: "image",
        name: old.name || `宫格分镜 ${index + 1}`,
        start: index * duration,
        duration,
        prompt: old.prompt || "",
        sound: old.sound || "",
      });
    }
    this.state.selectedId = "storyboard_0";
    this.save();
    if (shouldRender) this.render();
  }

  autoArrange(shouldRender = true) {
    const visuals = this.activeItems.filter((item) =>
      (item.kind === "image" || item.kind === "video") &&
      (this.mode === "全能参考" || this.itemTrack(item) === "visual")
    );
    if (!visuals.length) return;
    const duration = this.totalSeconds / (visuals.length + (this.mode === "宫格模式" ? 1 : 0));
    visuals.forEach((item, index) => {
      item.start = index * duration;
      item.duration = duration;
    });
    this.activeItems.filter((item) => this.itemTrack(item) === "audio").forEach((item) => {
      item.start = 0;
      item.duration = this.totalSeconds;
    });
    this.save();
    if (shouldRender) this.render();
  }

  migrateVisualTrackLayout(shouldRender = true) {
    const previousVersion = Number(this.state.version || 0);
    this.state.version = 5;
    if (previousVersion >= 5 || this.mode !== "宫格模式") return;

    const visuals = this.activeItems
      .filter((item) => item.source === "storyboard" && this.itemTrack(item) === "visual")
      .sort((a, b) => Number(a.start || 0) - Number(b.start || 0));
    const isPackedDefault = visuals.length > 0
      && Math.abs(Number(visuals[0].start || 0)) <= 0.03
      && visuals.every((item, index) => {
        if (index === 0) return true;
        const previous = visuals[index - 1];
        return Math.abs(
          Number(item.start || 0) - (Number(previous.start || 0) + Number(previous.duration || 0))
        ) <= 0.03;
      })
      && Math.abs(
        Number(visuals.at(-1).start || 0) + Number(visuals.at(-1).duration || 0) - this.totalSeconds
      ) <= 0.05;

    if (isPackedDefault) {
      const duration = this.totalSeconds / (visuals.length + 1);
      visuals.forEach((item, index) => {
        item.start = index * duration;
        item.duration = duration;
      });
    }
    this.save(false);
    if (shouldRender) this.render();
  }

  removeSelected() {
    if (!this.state.selectedId) return;
    const previousItems = this.activeItems.slice();
    const selected = this.selected;
    if (selected?.source === "storyboard") {
      const hidden = new Set(this.state.hiddenStoryboardIndices || []);
      hidden.add(Number(selected.gridIndex));
      this.state.hiddenStoryboardIndices = Array.from(hidden).sort((a, b) => a - b);
    }
    this.state.items = this.state.items.filter((item) => item.id !== this.state.selectedId);
    if (this.mode === "全能参考") this.renumberReferencePrompt(previousItems);
    this.state.selectedId = this.activeItems[0]?.id || null;
    this.save();
    this.render();
  }

  renumberReferencePrompt(previousItems) {
    let prompt = this.state.allReferencePrompt || "";
    const placeholders = new Map();
    for (const item of previousItems) {
      const oldToken = this.referenceToken(item, previousItems);
      if (!oldToken) continue;
      const placeholder = `__CS_H3_REF_${String(item.id).replace(/[^A-Za-z0-9_]/g, "_")}__`;
      prompt = prompt.split(oldToken).join(placeholder);
      placeholders.set(item.id, placeholder);
    }
    for (const item of previousItems) {
      const placeholder = placeholders.get(item.id);
      if (!placeholder) continue;
      const nextToken = this.state.items.some((candidate) => candidate.id === item.id)
        ? this.referenceToken(item)
        : "";
      prompt = prompt.split(placeholder).join(nextToken);
    }
    this.state.allReferencePrompt = prompt.replace(/[ \t]{2,}/g, " ").trim();
    if (this.globalInput) this.globalInput.value = this.state.allReferencePrompt;
  }

  notifyWorkflowChanged() {
    const graph = this.node.graph || app.graph;
    this.node.setDirtyCanvas?.(true, false);
    graph?.change?.();
    graph?.onNodeChanged?.(this.node);
    graph?.onStateChanged?.();

    clearTimeout(this.workflowCaptureTimer);
    this.workflowCaptureTimer = setTimeout(() => {
      try {
        const canvasEl = app.canvasEl || app.canvas?.canvas;
        canvasEl?.dispatchEvent(new PointerEvent("pointerup", {
          bubbles: true,
          cancelable: true,
        }));
        app.canvas?.checkState?.();
        app.canvas?.captureCanvasState?.();
      } catch (_) {
        // Older ComfyUI builds persist through the graph change callbacks above.
      }
    }, 100);
  }

  save(updateTimestamp = true) {
    this.storageKey = workflowSessionKey(this.node);
    this.persistPromptInput();
    if (updateTimestamp) this.state.updatedAt = Date.now();
    const serialized = JSON.stringify(this.state);
    for (const [widget, value] of [
      [this.dataWidget, serialized],
      [this.promptWidget, this.state.globalPrompt],
    ]) {
      if (!widget || widget.value === value) continue;
      const previous = widget.value;
      widget.value = value;
      this.node.onWidgetChanged?.(widget.name, value, previous, widget);
      try {
        widget.callback?.call(widget, value);
      } catch (_) { }
    }
    this.node.properties = this.node.properties || {};
    this.node.properties.csH3Timeline = serialized;
    this.node.properties.timeline_data = serialized;
    this.node.properties.global_prompt = this.state.globalPrompt;
    if (updateTimestamp) {
      try {
        window.sessionStorage?.setItem(this.storageKey, serialized);
      } catch (_) { }
    }
    if (updateTimestamp) this.notifyWorkflowChanged();
  }

  restore() {
    this.storageKey = workflowSessionKey(this.node);
    this.state = loadPersistedState(this.node, this.dataWidget, this.serializedWidget, this.storageKey);
    if (!this.state.allReferencePrompt && (this.mode === "全能參考" || this.mode === "全能参考")) {
      this.state.allReferencePrompt = this.state.globalPrompt || String(this.promptWidget?.value || "");
    }
    if (this.state.version < 5) this.migrateVisualTrackLayout(false);
    if (!this.selected) this.state.selectedId = this.activeItems[0]?.id || null;
    this.syncPromptEditor(true);
    this.render();
  }

  renderSummary() {
    const images = this.activeItems.filter((item) => item.kind === "image").length;
    const videos = this.activeItems.filter((item) => item.kind === "video").length;
    const audios = this.activeItems.filter((item) => item.kind === "audio").length;
    this.summaryEl.textContent = this.summary.startsWith("正在") || this.summary.includes("失敗")
      ? this.summary
      : (this.mode === "宮格模式" || this.mode === "宫格模式")
        ? `宮格模式｜主畫面${this.activeItems.filter((item) => this.itemTrack(item) === "visual").length}段 ` +
          `動作${this.activeItems.filter((item) => this.itemTrack(item) === "motion").length}段 ` +
          `音訊${this.activeItems.filter((item) => this.itemTrack(item) === "audio").length}段｜${this.totalSeconds.toFixed(1)}秒`
        : `全能參考｜${images}圖 ${videos}影片 ${audios}音訊｜${this.totalSeconds.toFixed(1)}秒`;
  }

  render() {
    this.updateModeUI();
    this.renderSummary();
    this.renderRuler();
    this.renderTrack();
    this.renderEditor();
    this.outputEl.textContent = this.compiledPrompt;
  }

  renderRuler() {
    this.playheadSeconds = clamp(this.playheadSeconds, 0, this.totalSeconds);
    this.ruler.innerHTML = "";
    for (let index = 0; index <= 5; index += 1) {
      const span = document.createElement("span");
      span.textContent = `${(this.totalSeconds * index / 5).toFixed(1)}秒`;
      this.ruler.appendChild(span);
    }
  }

  renderTrack() {
    this.track.innerHTML = "";
    this.motionTrack.innerHTML = "";
    this.audioTrack.innerHTML = "";
    this.audioRow.innerHTML = "";
    const referenceMode = this.mode === "全能參考" || this.mode === "全能参考";
    if (referenceMode) {
      this.renderReferenceMaterials();
      return;
    }

    const visualItems = this.activeItems.filter((item) =>
      this.itemTrack(item) === "visual" && (item.kind === "image" || item.kind === "video")
    );
    const motionItems = this.activeItems.filter((item) => this.itemTrack(item) === "motion");
    const audioItems = this.activeItems.filter((item) => this.itemTrack(item) === "audio");
    if (!visualItems.length) this.renderTrackEmpty(this.track, "時間軸為空，重新匯入宮格圖可自動恢復");
    if (!motionItems.length) this.renderTrackEmpty(this.motionTrack, "可新增動作與運鏡參考影片");
    if (!audioItems.length) this.renderTrackEmpty(this.audioTrack, "可新增對白、音色或環境音訊");
    for (const item of visualItems) this.renderTimelineItem(item, this.track, "visual");
    for (const item of motionItems) this.renderTimelineItem(item, this.motionTrack, "motion");
    for (const item of audioItems) this.renderTimelineItem(item, this.audioTrack, "audio");
    this.renderPlayheads();
  }

  renderTrackEmpty(track, text) {
    const empty = document.createElement("div");
    empty.className = "cs-h3-empty";
    empty.textContent = text;
    track.appendChild(empty);
  }

  appendItemMedia(card, item) {
    const storyboardPreview = item.source === "storyboard" ? this.storyboardPreviews[item.gridIndex] : null;
    const importedGrid = item.source === "storyboard" ? this.state.gridImage : null;
    if (storyboardPreview) {
      const media = document.createElement("img");
      media.src = previewUrl(storyboardPreview);
      card.appendChild(media);
    } else if (importedGrid?.file) {
      const [cols, rows] = gridDimensions(this.node);
      const col = Number(item.gridIndex || 0) % cols;
      const row = Math.floor(Number(item.gridIndex || 0) / cols);
      const thumb = document.createElement("div");
      thumb.className = "cs-h3-grid-thumb";
      thumb.style.backgroundImage = `url("${mediaUrl(importedGrid.file)}")`;
      thumb.style.backgroundSize = `${cols * 100}% ${rows * 100}%`;
      thumb.style.backgroundPosition = `${cols > 1 ? col * 100 / (cols - 1) : 0}% ${rows > 1 ? row * 100 / (rows - 1) : 0}%`;
      card.appendChild(thumb);
    } else if (item.file && item.kind !== "audio") {
      const media = document.createElement(item.kind === "video" ? "video" : "img");
      media.src = mediaUrl(item.file);
      if (item.kind === "video") {
        media.muted = true;
        media.preload = "metadata";
      }
      card.appendChild(media);
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "cs-h3-placeholder";
      placeholder.textContent = item.kind === "audio" ? "聲音參考" : item.name || "宮格分鏡";
      card.appendChild(placeholder);
    }
  }

  renderTimelineItem(item, track, trackType) {
    const card = document.createElement("div");
    card.dataset.itemId = item.id;
    card.className = `cs-h3-timeline-card ${trackType} ${item.id === this.state.selectedId ? "selected" : ""}`;
    const start = clamp(item.start, 0, this.totalSeconds);
    const duration = clamp(item.duration, 0.1, this.totalSeconds - start || 0.1);
    card.style.left = `${start / this.totalSeconds * 100}%`;
    card.style.width = `${Math.max(3, duration / this.totalSeconds * 100)}%`;
    card.title = `${item.name || "參考素材"}\n${start.toFixed(2)}秒 - ${(start + duration).toFixed(2)}秒\n拖曳片段可調整位置，拖曳左右邊緣可連動調整時長`;
    this.appendItemMedia(card, item);
    const meta = document.createElement("div");
    meta.className = "cs-h3-card-meta";
    const kindLabel = trackType === "motion" ? "動作" : trackType === "audio" ? "音訊" : item.kind === "video" ? "影片" : "圖片";
    const description = String(item.prompt || "").trim() || item.name || "未命名";
    meta.textContent = `${kindLabel}｜${description}`;
    card.appendChild(meta);
    const leftHandle = document.createElement("div");
    leftHandle.className = "cs-h3-resize-handle left";
    const rightHandle = document.createElement("div");
    rightHandle.className = "cs-h3-resize-handle";
    card.append(leftHandle, rightHandle);
    this.bindTimelineDrag(card, item, track, leftHandle, rightHandle);
    track.appendChild(card);
  }

  bindTimelineDrag(card, item, track, leftHandle, rightHandle) {
    card.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      const resizingLeft = event.target === leftHandle;
      const resizingRight = event.target === rightHandle;
      const originX = event.clientX;
      const originStart = clamp(item.start, 0, this.totalSeconds);
      const originDuration = clamp(item.duration, 0.1, this.totalSeconds);
      const originEnd = Math.min(this.totalSeconds, originStart + originDuration);
      const visualSnapshot = this.activeItems
        .filter((candidate) => this.itemTrack(candidate) === "visual")
        .map((candidate) => ({
          id: candidate.id,
          start: Number(candidate.start || 0),
          duration: Number(candidate.duration || 0.1),
        }));
      const orderedVisuals = visualSnapshot.slice().sort((a, b) => a.start - b.start);
      const visualIndex = orderedVisuals.findIndex((candidate) => candidate.id === item.id);
      const previousVisual = visualIndex > 0 ? orderedVisuals[visualIndex - 1] : null;
      const nextVisual = visualIndex >= 0 && visualIndex < orderedVisuals.length - 1
        ? orderedVisuals[visualIndex + 1]
        : null;
      const previousVisualEnd = visualIndex > 0
        ? orderedVisuals[visualIndex - 1].start + orderedVisuals[visualIndex - 1].duration
        : 0;
      const nextVisualStart = visualIndex >= 0 && visualIndex < orderedVisuals.length - 1
        ? orderedVisuals[visualIndex + 1].start
        : this.totalSeconds;
      const previousLive = previousVisual
        ? this.activeItems.find((candidate) => candidate.id === previousVisual.id)
        : null;
      const nextLive = nextVisual
        ? this.activeItems.find((candidate) => candidate.id === nextVisual.id)
        : null;
      const leftJoint = track === this.track && previousVisual
        && Math.abs(previousVisualEnd - originStart) <= 0.03;
      const rightJoint = track === this.track && nextVisual
        && Math.abs(nextVisualStart - originEnd) <= 0.03;
      this.state.selectedId = item.id;
      this.root.focus({ preventScroll: true });
      card.classList.add("selected");
      card.classList.add("dragging");
      card.setPointerCapture?.(event.pointerId);

      const move = (moveEvent) => {
        const width = Math.max(1, track.getBoundingClientRect().width);
        const delta = (moveEvent.clientX - originX) / width * this.totalSeconds;
        if (resizingLeft && leftJoint && previousLive) {
          const minBoundary = previousVisual.start + 0.1;
          const maxBoundary = originEnd - 0.1;
          const boundary = clamp(
            this.snapTime(originStart + delta, null, [previousVisual.id, item.id]),
            minBoundary,
            maxBoundary
          );
          previousLive.duration = boundary - previousVisual.start;
          item.start = boundary;
          item.duration = originEnd - boundary;
        } else if (resizingRight && rightJoint && nextLive) {
          const nextEnd = nextVisual.start + nextVisual.duration;
          const minBoundary = originStart + 0.1;
          const maxBoundary = nextEnd - 0.1;
          const boundary = clamp(
            this.snapTime(originEnd + delta, null, [item.id, nextVisual.id]),
            minBoundary,
            maxBoundary
          );
          item.duration = boundary - originStart;
          nextLive.start = boundary;
          nextLive.duration = nextEnd - boundary;
        } else if (resizingLeft) {
          const minStart = track === this.track ? previousVisualEnd : 0;
          const nextStart = this.snapTime(clamp(originStart + delta, minStart, originEnd - 0.1), item);
          item.start = clamp(nextStart, minStart, originEnd - 0.1);
          item.duration = originEnd - item.start;
        } else if (resizingRight) {
          const maxEnd = track === this.track ? nextVisualStart : this.totalSeconds;
          const nextEnd = clamp(
            this.snapTime(clamp(originEnd + delta, originStart + 0.1, maxEnd), item),
            originStart + 0.1,
            maxEnd
          );
          item.duration = Math.max(0.1, nextEnd - originStart);
        } else if (track === this.track) {
          const desiredStart = this.snapTime(
            clamp(originStart + delta, 0, Math.max(0, this.totalSeconds - originDuration)),
            item
          );
          const rect = track.getBoundingClientRect();
          const cursorSeconds = clamp(
            (moveEvent.clientX - rect.left) / Math.max(1, rect.width) * this.totalSeconds,
            0,
            this.totalSeconds
          );
          this.resolveVisualTrackDrag(item, desiredStart, cursorSeconds, visualSnapshot);
        } else {
          item.start = this.snapTime(clamp(originStart + delta, 0, Math.max(0, this.totalSeconds - originDuration)), item);
          item.start = Math.min(item.start, Math.max(0, this.totalSeconds - originDuration));
        }
        this.updateTrackCardPositions(track);
      };
      const finish = () => {
        card.removeEventListener("pointermove", move);
        card.removeEventListener("pointerup", finish);
        card.removeEventListener("pointercancel", finish);
        card.classList.remove("dragging");
        this.save();
        this.render();
      };
      card.addEventListener("pointermove", move);
      card.addEventListener("pointerup", finish);
      card.addEventListener("pointercancel", finish);
    });
  }

  renderReferenceMaterials() {
    const visuals = this.activeItems.filter((item) => item.kind === "image" || item.kind === "video");
    if (!visuals.length) this.renderTrackEmpty(this.track, "添加图片或视频参考");
    for (const item of visuals) {
      const card = document.createElement("div");
      card.className = `cs-h3-card ${item.id === this.state.selectedId ? "selected" : ""}`;
      const token = this.referenceToken(item);
      card.title = `点击插入 ${token}\n${item.name || "参考素材"}`;
      this.appendItemMedia(card, item);
      const meta = document.createElement("div");
      meta.className = "cs-h3-card-meta";
      meta.textContent = `${token}｜${item.name || "未命名"}`;
      card.appendChild(meta);
      card.addEventListener("click", () => this.insertReferenceToken(item));
      this.track.appendChild(card);
    }
    const audios = this.activeItems.filter((item) => item.kind === "audio");
    for (const item of audios) {
      const chip = document.createElement("button");
      chip.className = `cs-h3-audio-chip ${item.id === this.state.selectedId ? "selected" : ""}`;
      const token = this.referenceToken(item);
      chip.textContent = `${token}｜${item.name || "参考音频"}`;
      chip.title = `点击插入 ${token}`;
      chip.addEventListener("click", () => this.insertReferenceToken(item));
      this.audioRow.appendChild(chip);
    }
  }

  renderEditor() {
    this.editorSection.innerHTML = "";
    if (this.mode === "全能参考") return;
    const item = this.selected;
    if (!item) {
      const empty = document.createElement("div");
      empty.className = "cs-h3-empty";
      empty.textContent = "选择一个分镜或参考声音后，可以在这里编辑。";
      this.editorSection.appendChild(empty);
      return;
    }

    const editor = document.createElement("div");
    editor.className = "cs-h3-editor";
    const trackType = this.itemTrack(item);
    const legacySound = trackType === "visual" && String(item.sound || "").trim()
      ? `\n声音与台词：${String(item.sound).trim()}`
      : "";
    const prompt = this.textAreaField(
      trackType === "audio" ? "声音参考要求" : trackType === "motion" ? "动作与运镜参考要求" : "当前片段提示词",
      `${item.prompt || ""}${legacySound}`.trim(),
      trackType === "audio"
        ? "说明要参考的音色、说话方式、音乐节奏或环境氛围……"
        : trackType === "motion"
          ? "说明这段视频需要参考的人物动作、表演节奏或摄影机运动……"
          : "统一描述这一段的画面、动作、情绪、镜头、环境声和人物台词……",
      (value) => {
        item.prompt = value;
        if (trackType === "visual") item.sound = "";
        this.save();
      }
    );
    prompt.classList.add("wide");
    const promptInput = prompt.querySelector("textarea");
    if (promptInput) {
      promptInput.rows = 12;
      promptInput.style.height = "300px";
      promptInput.style.minHeight = "300px";
    }
    editor.appendChild(prompt);

    if (item.kind === "video" && item.hasAudio) {
      const wrap = document.createElement("label");
      wrap.className = "cs-h3-check wide";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = item.includeAudio !== false;
      checkbox.addEventListener("change", () => { item.includeAudio = checkbox.checked; this.save(); });
      wrap.append(checkbox, document.createTextNode("同时参考这段视频的原始声音"));
      editor.appendChild(wrap);
    }
    this.editorSection.appendChild(editor);
  }

  textAreaField(labelText, value, placeholder, onInput) {
    const wrap = document.createElement("label");
    const label = document.createElement("span");
    label.className = "cs-h3-label";
    label.textContent = labelText;
    const input = document.createElement("textarea");
    input.className = "cs-h3-textarea";
    input.value = value;
    input.placeholder = placeholder;
    input.addEventListener("input", () => onInput(input.value));
    wrap.append(label, input);
    return wrap;
  }

  onExecuted(message) {
    const prompt = message?.compiled_prompt?.[0] ?? message?.compiled_prompt;
    const summary = message?.summary?.[0] ?? message?.summary;
    const previews = message?.storyboard_previews;
    if (prompt) this.compiledPrompt = String(prompt);
    if (summary) this.summary = String(summary);
    if (Array.isArray(previews)) {
      this.storyboardPreviews = Array.isArray(previews[0]) ? previews[0] : previews;
    }
    this.render();
  }
}

app.registerExtension({
  name: "UltimateDirector.MediaDashboard",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_CLASS) return;

    const originalCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = originalCreated?.apply(this, arguments);
      injectStyles();
      this.title = "CS-H3 多模态参考导演台";
      removeLegacyInputs(this);
      removeLegacyOutputs(this);
      hideWidget(getWidget(this, "mode"));
      hideWidget(getWidget(this, "dashboard_data"));
      hideWidget(getWidget(this, "global_prompt"));

      const root = document.createElement("div");
      const domWidget = this.addDOMWidget("cs_h3_director_ui", "cs_h3_director_ui", root, {
        hideOnZoom: false,
        getMinHeight: () => 865,
        getValue: () => "",
        setValue: () => { },
      });
      domWidget.computeSize = (width) => [width, 865];
      this._csH3Director = new H3DirectorUI(this, root);
      const width = Math.max(this.size?.[0] || 0, 1080);
      const height = Math.max(this.size?.[1] || 0, 1085);
      this.setSize([width, height]);
      return result;
    };

    const originalConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (info) {
      const result = originalConfigure?.apply(this, arguments);
      removeLegacyInputs(this);
      removeLegacyOutputs(this);
      setTimeout(() => this._csH3Director?.restore(), 0);
      return result;
    };

    const originalSerialize = nodeType.prototype.onSerialize;
    nodeType.prototype.onSerialize = function (info) {
      this._csH3Director?.save(false);
      const result = originalSerialize?.apply(this, arguments);
      if (info && typeof info === "object") {
        for (const widget of this.widgets || []) {
          if (widget.name && widget.value !== undefined && widget.name !== "cs_h3_director_ui") {
            this.properties[widget.name] = widget.value;
          }
        }
        info.properties = { ...(this.properties || {}) };
        if (Array.isArray(info.widgets_values)) {
          for (const name of ["dashboard_data", "global_prompt"]) {
            const widget = getWidget(this, name);
            const index = this.widgets?.indexOf(widget) ?? -1;
            if (index >= 0 && index < info.widgets_values.length) {
              info.widgets_values[index] = widget.value;
            }
          }
        }
      }
      return result;
    };

    const originalExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      const result = originalExecuted?.apply(this, arguments);
      this._csH3Director?.onExecuted(message);
      return result;
    };
  },
});
