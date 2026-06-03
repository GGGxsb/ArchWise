const requirementEl = document.querySelector("#requirement");
const topKEl = document.querySelector("#topK");
const topologyModeEl = document.querySelector("#topologyMode");
const topologyTimeoutEl = document.querySelector("#topologyTimeout");
const topologyRoundsEl = document.querySelector("#topologyRounds");
const btn = document.querySelector("#recommendBtn");
const statusEl = document.querySelector("#status");
const winnerEl = document.querySelector("#winner");
const featuresEl = document.querySelector("#features");
const compositionEl = document.querySelector("#composition");
const compositionStatusEl = document.querySelector("#compositionStatus");
const matrixEl = document.querySelector("#matrix");
const matrixCountEl = document.querySelector("#matrixCount");
const reportEl = document.querySelector("#report");
const decisionTraceEl = document.querySelector("#decisionTrace");
const decisionSummaryEl = document.querySelector("#decisionSummary");
const traceEl = document.querySelector("#trace");
const traceSummaryEl = document.querySelector("#traceSummary");
const topologyTabsEl = document.querySelector("#topologyTabs");
const topologyEl = document.querySelector("#topology");
const toastRootEl = document.querySelector("#toastRoot");
const zoomOutBtn = document.querySelector("#zoomOutBtn");
const zoomResetBtn = document.querySelector("#zoomResetBtn");
const zoomInBtn = document.querySelector("#zoomInBtn");
const fullscreenTopologyBtn = document.querySelector("#fullscreenTopologyBtn");
const copyTopologyJsonBtn = document.querySelector("#copyTopologyJsonBtn");
const copySvgBtn = document.querySelector("#copySvgBtn");
const topologyModalEl = document.querySelector("#topologyModal");
const topologyModalCanvasEl = document.querySelector("#topologyModalCanvas");
const modalZoomOutBtn = document.querySelector("#modalZoomOutBtn");
const modalZoomResetBtn = document.querySelector("#modalZoomResetBtn");
const modalZoomInBtn = document.querySelector("#modalZoomInBtn");
const closeTopologyModalBtn = document.querySelector("#closeTopologyModalBtn");
let reportMarkdown = "";
let currentTopologyJson = "";
let currentTopologySource = "";
let currentTopologySvg = "";
let currentTopologyGraphs = {};
let currentTopologyName = "";
let currentInteractiveGraph = null;
let topologyScale = 1;
let modalTopologyScale = 1;
let hasStreamResult = false;
let pendingReportDelta = "";
let reportRenderTimer = null;
let topologyAbortController = null;
let latestTopologyRequest = null;
const serviceNoticeKeys = new Set();

if (window.mermaid) {
  mermaid.initialize({ startOnLoad: false, theme: "base" });
}

btn.addEventListener("click", recommend);
copyTopologyJsonBtn.addEventListener("click", () => copyText(currentTopologyJson, "已复制拓扑 JSON"));
copySvgBtn.addEventListener("click", () => copyText(currentTopologySvg, "已复制 SVG"));
zoomOutBtn.addEventListener("click", () => setTopologyScale(topologyScale - 0.15));
zoomResetBtn.addEventListener("click", fitTopologyToContainer);
zoomInBtn.addEventListener("click", () => setTopologyScale(topologyScale + 0.15));
fullscreenTopologyBtn.addEventListener("click", toggleTopologyModal);
modalZoomOutBtn.addEventListener("click", () => setModalTopologyScale(modalTopologyScale - 0.15));
modalZoomResetBtn.addEventListener("click", fitModalTopology);
modalZoomInBtn.addEventListener("click", () => setModalTopologyScale(modalTopologyScale + 0.15));
closeTopologyModalBtn.addEventListener("click", closeTopologyModal);
topologyModalEl.addEventListener("click", (event) => {
  if (event.target === topologyModalEl) closeTopologyModal();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && topologyModalEl.classList.contains("open")) {
    closeTopologyModal();
  }
});
window.addEventListener("resize", () => {
  if (currentTopologySvg) fitTopologyToContainer();
  if (topologyModalEl.classList.contains("open")) fitModalTopology();
});

async function recommend() {
  const requirement = requirementEl.value.trim();
  if (!requirement) {
    statusEl.textContent = "请输入需求";
    return;
  }
  const topK = Number(topKEl.value || 12);
  statusEl.textContent = "分析中...";
  btn.disabled = true;
  resetRecommendationView();
  try {
    const response = await fetch("/api/recommend/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requirement, top_k: topK }),
    });
    if (!response.ok || !response.body) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "流式推荐接口返回异常");
    }
    await consumeRecommendationStream(response.body);
  } catch (error) {
    const notice = classifyServiceError(error.message);
    statusEl.textContent = notice.title;
    showToast(notice.title, notice.message);
    if (hasStreamResult && /network|fetch|Failed to fetch|流式|连接/i.test(String(error.message || ""))) {
      renderTopologyUnavailable("推荐与报告已生成，但拓扑图推送连接中断。请重新点击生成推荐或稍后重试。");
    } else {
      renderErrorState(error.message);
    }
  } finally {
    btn.disabled = false;
  }
}

function readTopologyOptions() {
  const fastMode = (topologyModeEl?.value || "fast") === "fast";
  const timeoutValue = topologyTimeoutEl?.value ?? "12";
  return {
    topology_fast_mode: fastMode,
    topology_llm_timeout_seconds: Number(timeoutValue),
    topology_repair_max_rounds: Number(topologyRoundsEl?.value || 1),
  };
}

function resetRecommendationView() {
  reportMarkdown = "";
  currentTopologyJson = "";
  currentTopologySource = "";
  currentTopologySvg = "";
  currentTopologyGraphs = {};
  currentTopologyName = "";
  currentInteractiveGraph = null;
  topologyScale = 1;
  modalTopologyScale = 1;
  hasStreamResult = false;
  pendingReportDelta = "";
  latestTopologyRequest = null;
  if (topologyAbortController) {
    topologyAbortController.abort();
    topologyAbortController = null;
  }
  if (reportRenderTimer) {
    clearTimeout(reportRenderTimer);
    reportRenderTimer = null;
  }
  serviceNoticeKeys.clear();
  closeTopologyModal();

  winnerEl.className = "winner empty";
  winnerEl.textContent = "正在分析...";
  featuresEl.className = "feature-list empty";
  featuresEl.textContent = "正在提取需求特征...";
  compositionEl.className = "composition empty";
  compositionEl.textContent = "正在判断是否需要组合架构...";
  compositionStatusEl.textContent = "分析中";
  matrixEl.innerHTML = "";
  matrixCountEl.textContent = "分析中";
  decisionTraceEl.className = "decision-trace empty";
  decisionTraceEl.textContent = "正在收集决策证据...";
  decisionSummaryEl.textContent = "分析中";
  traceEl.innerHTML = "";
  traceSummaryEl.textContent = "正在执行 Agent 协作";
  renderMarkdownReport("");
  renderTopologyLoading();
}

async function recommendClassic(requirement, topK = 12) {
  const response = await fetch("/api/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ requirement, top_k: topK }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "推荐接口返回异常");
  }
  const data = await response.json();
  renderInitial(data);
  reportMarkdown = data.report;
  renderMarkdownReport(reportMarkdown);
  await renderTopology(data.topology_graphs, data.topology_diagrams);
  statusEl.textContent = "已生成";
}

async function consumeRecommendationStream(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  statusEl.textContent = "正在接收 DeepSeek 流式输出...";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const rawEvent of events) {
      await handleSseEvent(rawEvent);
    }
  }
  if (buffer.trim()) await handleSseEvent(buffer);
}

async function handleSseEvent(rawEvent) {
  const lines = rawEvent.split("\n");
  const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim() || "message";
  const dataText = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim())
    .join("\n");
  if (!dataText) return;
  const payload = JSON.parse(dataText);

  if (event === "features") {
    hasStreamResult = true;
    renderFeatures(payload.features);
    renderTrace(payload.trace);
    statusEl.textContent = "需求特征已提取，正在匹配候选架构...";
  }
  if (event === "recommendation" || event === "initial") {
    hasStreamResult = true;
    if (payload.features) renderFeatures(payload.features);
    renderRecommendation(payload);
    reportMarkdown = "";
    renderMarkdownReport("");
    renderTopologyLoading();
    startTopologyStream(payload);
    statusEl.textContent = "DeepSeek 正在生成评估报告...";
  }
  if (event === "report_delta") {
    hasStreamResult = true;
    enqueueReportDelta(payload.delta || "");
  }
  if (event === "topology") {
    flushReportDelta();
    hasStreamResult = true;
    mergeTrace(payload.trace);
    if (payload.decision_trace) renderDecisionTrace(payload.decision_trace);
    await renderTopology(payload.topology_graphs, payload.topology_diagrams);
    statusEl.textContent = "正在渲染定制拓扑...";
  }
  if (event === "heartbeat") {
    if (payload.trace) renderTrace(payload.trace);
    statusEl.textContent = payload.message || "拓扑图仍在后台生成中...";
  }
  if (event === "error") {
    renderTrace(payload.trace || []);
    const message = payload.message || "DeepSeek 需求解析失败，请检查 API Key、模型服务或输入需求。";
    const notice = classifyServiceError(message);
    renderErrorState(message);
    showToast(notice.title, notice.message);
    statusEl.textContent = notice.title;
  }
  if (event === "done") {
    flushReportDelta();
    if (payload.ok !== false) {
      statusEl.textContent = "已生成";
    }
  }
}

async function startTopologyStream(recommendationPayload) {
  const requirement = recommendationPayload.requirement || requirementEl.value.trim();
  const features = recommendationPayload.features;
  const finalRecommendation = recommendationPayload.final_recommendation;
  if (!requirement || !features || !finalRecommendation) {
    renderTopologyUnavailable("推荐结果缺少需求特征或最终推荐架构，无法启动拓扑生成。");
    return;
  }
  if (topologyAbortController) topologyAbortController.abort();
  const controller = new AbortController();
  topologyAbortController = controller;
  latestTopologyRequest = {
    requirement,
    features,
    final_recommendation: finalRecommendation,
    composition_recommendation: recommendationPayload.composition_recommendation || {},
    decision_trace: recommendationPayload.decision_trace || {},
    ...readTopologyOptions(),
  };

  try {
    const response = await fetch("/api/topology/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(latestTopologyRequest),
      signal: controller.signal,
    });
    if (!response.ok || !response.body) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "拓扑流式接口返回异常");
    }
    await consumeTopologyStream(response.body);
  } catch (error) {
    if (error.name === "AbortError") return;
    const notice = classifyServiceError(error.message);
    renderTopologyUnavailable(notice.message);
    showToast(notice.title, notice.message);
  } finally {
    if (topologyAbortController === controller) {
      topologyAbortController = null;
    }
  }
}

async function consumeTopologyStream(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const rawEvent of events) {
      await handleTopologySseEvent(rawEvent);
    }
  }
  if (buffer.trim()) await handleTopologySseEvent(buffer);
}

async function handleTopologySseEvent(rawEvent) {
  const lines = rawEvent.split("\n");
  const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim() || "message";
  const dataText = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim())
    .join("\n");
  if (!dataText) return;
  const payload = JSON.parse(dataText);

  if (event === "heartbeat") {
    if (payload.trace) mergeTrace(payload.trace);
    if (payload.decision_trace) renderDecisionTrace(payload.decision_trace);
    statusEl.textContent = payload.message || "架构图生成中...";
  }
  if (event === "topology") {
    if (payload.trace) mergeTrace(payload.trace);
    if (payload.decision_trace) renderDecisionTrace(payload.decision_trace);
    await renderTopology(payload.topology_graphs, payload.topology_diagrams);
    statusEl.textContent = "架构图已生成";
  }
  if (event === "error") {
    const message = payload.message || "拓扑生成失败。";
    const notice = classifyServiceError(message);
    if (payload.trace) mergeTrace(payload.trace);
    renderTopologyUnavailable(message);
    showToast(notice.title, notice.message);
  }
}

function enqueueReportDelta(delta) {
  pendingReportDelta += delta;
  if (reportRenderTimer) return;
  reportRenderTimer = window.setTimeout(() => {
    flushReportDelta();
  }, 80);
}

function flushReportDelta() {
  if (reportRenderTimer) {
    clearTimeout(reportRenderTimer);
    reportRenderTimer = null;
  }
  if (!pendingReportDelta) return;
  reportMarkdown += pendingReportDelta;
  pendingReportDelta = "";
  renderMarkdownReport(reportMarkdown);
  reportEl.scrollTop = reportEl.scrollHeight;
}

function renderErrorState(message) {
  winnerEl.className = "winner empty";
  winnerEl.textContent = "暂无推荐";
  featuresEl.className = "feature-list empty";
  featuresEl.textContent = "DeepSeek 未返回可用的结构化需求特征";
  compositionEl.className = "composition empty";
  compositionEl.textContent = "暂无结果";
  compositionStatusEl.textContent = "暂无结果";
  matrixEl.innerHTML = "";
  matrixCountEl.textContent = "暂无结果";
  reportMarkdown = `## 需求解析失败\n\n${message}\n\n请检查 DeepSeek API Key、模型服务状态，或重新输入更完整的软件需求描述。`;
  renderMarkdownReport(reportMarkdown);
  topologyTabsEl.innerHTML = "";
  topologyEl.innerHTML = `<div class="topology-loading"><strong>架构图未生成</strong><span>${escapeHtml(message)}</span></div>`;
  decisionTraceEl.className = "decision-trace empty";
  decisionTraceEl.textContent = "需求解析失败，未进入架构匹配和评估阶段";
  decisionSummaryEl.textContent = "暂无决策证据";
}

function renderInitial(data) {
  renderFeatures(data.features);
  renderRecommendation(data);
}

function renderFeatures(features) {
  if (!features) {
    featuresEl.className = "feature-list empty";
    featuresEl.textContent = "暂无结果";
    return;
  }
  featuresEl.className = "feature-list";
  featuresEl.innerHTML = `
    <div><b>领域</b><span>${escapeHtml(features.domain)}</span></div>
    <div><b>数据流</b><span>${escapeHtml(features.data_flow)}</span></div>
    <div><b>关键词</b><span>${(features.keywords || []).map(escapeHtml).join("、") || "无"}</span></div>
    <div><b>模糊点</b><span>${(features.ambiguity_notes || []).map(escapeHtml).join("；") || "无明显模糊点"}</span></div>
  `;
}

function renderRecommendation(data) {
  const winner = data.final_recommendation;
  winnerEl.className = "winner";
  winnerEl.innerHTML = `
    <strong>${escapeHtml(winner.name)}</strong>
    <span>${winner.score}/100</span>
    <p>
      <b>${escapeHtml(winner.recommendation_role || "核心推荐")}</b> · 置信度：${escapeHtml(winner.confidence || "中")}<br>
      ${winner.matched_reasons.map(escapeHtml).join("<br>")}
      ${winner.deductions?.length ? `<br><em>扣分：${winner.deductions.map(escapeHtml).join("；")}</em>` : ""}
    </p>
  `;

  renderMatrix(data.comparison_matrix);
  renderComposition(data.composition_recommendation);
  renderTrace(data.trace);
  renderDecisionTrace(data.decision_trace);
}

function renderComposition(composition) {
  if (!composition || !Object.keys(composition).length) {
    compositionEl.className = "composition empty";
    compositionEl.textContent = "暂无结果";
    compositionStatusEl.textContent = "暂无结果";
    return;
  }

  const needed = Boolean(composition.composition_needed);
  compositionEl.className = `composition ${needed ? "needed" : "not-needed"}`;
  compositionStatusEl.textContent = needed ? "建议组合" : "不建议组合";

  if (!needed) {
    compositionEl.innerHTML = `
      <div class="composition-main">
        <strong>不建议采用复杂组合架构</strong>
        <span>核心架构：${escapeHtml(composition.primary_style || "暂无")}</span>
      </div>
      <p>${escapeHtml(composition.reason || "单一架构即可满足当前需求。")}</p>
      ${listItems(composition.overengineering_warnings || [], "暂无过度设计风险")}
    `;
    return;
  }

  const supporting = composition.supporting_styles || [];
  compositionEl.innerHTML = `
    <div class="composition-main">
      <strong>核心架构：${escapeHtml(composition.primary_style || "暂无")}</strong>
      <span>${escapeHtml(composition.reason || "")}</span>
    </div>
    <div class="composition-cards">
      ${supporting.map((item) => `
        <article>
          <strong>${escapeHtml(item.style)}</strong>
          <span>${escapeHtml(item.role || "")}</span>
          <p>${escapeHtml(item.reason || "")}</p>
          <small>适用位置：${escapeHtml((item.apply_to || []).join("、") || "待详细设计确认")}</small>
        </article>
      `).join("")}
    </div>
    ${composition.triggers?.length ? `<div class="composition-notes"><b>触发依据</b>${listItems(composition.triggers, "")}</div>` : ""}
    ${composition.overengineering_warnings?.length ? `<div class="composition-notes warn"><b>风险提醒</b>${listItems(composition.overengineering_warnings, "")}</div>` : ""}
  `;
}

function renderMatrix(rows) {
  if (!rows.length) {
    matrixEl.innerHTML = "";
    matrixCountEl.textContent = "暂无结果";
    return;
  }
  const headers = Object.keys(rows[0]);
  matrixCountEl.textContent = `已展示 ${rows.length} 种候选架构`;
  matrixEl.innerHTML = `
    <thead><tr>${headers.map((head) => `<th>${escapeHtml(head)}</th>`).join("")}</tr></thead>
    <tbody>
      ${rows.map((row) => `<tr>${headers.map((head) => `<td>${escapeHtml(String(row[head]))}</td>`).join("")}</tr>`).join("")}
    </tbody>
  `;
}

function renderTrace(trace) {
  const items = trace || [];
  traceEl.innerHTML = items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  traceSummaryEl.textContent = items.length ? `${items.length} 个步骤，可展开查看` : "暂无推理过程";
}

function mergeTrace(trace) {
  const existing = Array.from(traceEl.querySelectorAll("li")).map((item) => item.textContent || "");
  const merged = Array.from(new Set([...existing, ...(trace || [])].filter(Boolean)));
  renderTrace(merged);
}

function renderDecisionTrace(trace) {
  if (!trace || !Object.keys(trace).length) {
    decisionTraceEl.className = "decision-trace empty";
    decisionTraceEl.textContent = "暂无结果";
    decisionSummaryEl.textContent = "暂无决策证据";
    return;
  }

  const features = trace.requirement_features || {};
  const rules = trace.rule_evidence || {};
  const graph = trace.graph_evidence || [];
  const scores = trace.score_evidence || [];
  const topology = trace.topology_evidence || {};
  const winner = scores[0];

  decisionTraceEl.className = "decision-trace";
  decisionSummaryEl.textContent = winner ? `${winner.name} · ${winner.score}/100 · ${winner.confidence}` : "已有决策证据";

  decisionTraceEl.innerHTML = `
    <div class="decision-section">
      <h3>需求证据</h3>
      <p><b>领域</b>${escapeHtml(features.domain || "未知")}</p>
      <p><b>数据流</b>${escapeHtml(features.data_flow || "未知")}</p>
      <p><b>关键词</b>${escapeHtml((features.keywords || []).join("、") || "无")}</p>
      <div class="evidence-pills">${qualityPills(features.quality_attributes || {})}</div>
    </div>
    <div class="decision-section">
      <h3>规则证据</h3>
      ${listItems(rules.reasons || [], "未命中特定规则")}
    </div>
    <div class="decision-section">
      <h3>知识图谱证据</h3>
      ${graph.length ? graph.slice(0, 5).map((item) => `
        <p><b>${escapeHtml(item.style_id)}</b>${escapeHtml(item.reason || "图谱匹配")} · ${escapeHtml(String(item.score ?? ""))}</p>
      `).join("") : "<p>暂无强匹配架构风格</p>"}
      ${topology.scenarios?.length ? `<p><b>拓扑场景</b>${escapeHtml(topology.scenarios.join("、"))}</p>` : ""}
      ${topology.capabilities?.length ? `<p><b>业务能力</b>${escapeHtml(topology.capabilities.slice(0, 10).join("、"))}</p>` : ""}
      ${renderTopologyRepair(topology.react_repair || [])}
    </div>
    <div class="decision-section">
      <h3>评分证据</h3>
      ${scores.slice(0, 5).map((item) => `
        <div class="score-evidence">
          <strong>${escapeHtml(item.name)} ${escapeHtml(String(item.score))}/100</strong>
          <span>${escapeHtml(item.role || "候选")} · 置信度 ${escapeHtml(item.confidence || "中")}</span>
          ${listItems((item.matched_reasons || []).slice(0, 2), "暂无匹配理由")}
          ${item.deductions?.length ? `<em>扣分：${escapeHtml(item.deductions.slice(0, 2).join("；"))}</em>` : ""}
        </div>
      `).join("")}
    </div>
    <div class="decision-section">
      <h3>LLM 复核</h3>
      ${listItems(trace.llm_review || [], "暂无 DeepSeek 复核意见")}
      <p><b>最终说明</b>${escapeHtml(trace.final_reason || "暂无")}</p>
    </div>
    <div class="decision-section">
      <h3>组合推荐证据</h3>
      <p><b>是否组合</b>${trace.composition_evidence?.composition_needed ? "建议组合" : "不建议组合"}</p>
      <p><b>说明</b>${escapeHtml(trace.composition_evidence?.reason || "暂无")}</p>
      ${listItems(trace.composition_evidence?.triggers || [], "暂无组合触发条件")}
    </div>
  `;
}

function renderTopologyRepair(repairTrace) {
  if (!repairTrace.length) return "";
  return `
    <div class="score-evidence">
      <strong>拓扑 ReAct 补全</strong>
      ${repairTrace.map((item) => {
        if (item.action === "coverage_check") {
          const coverage = item.coverage || {};
          return `
            <p><b>第 ${escapeHtml(String(item.round))} 轮多维覆盖率</b>${escapeHtml(String(coverage.score ?? "未知"))}</p>
            ${renderCoverageDimensions(coverage.dimensions || {})}
            ${coverage.missing_capabilities?.length ? `<em>缺失能力：${escapeHtml(coverage.missing_capabilities.slice(0, 8).join("、"))}</em>` : "<em>核心业务能力覆盖充足</em>"}
            ${coverage.missing_components?.length ? `<em>缺失组件：${escapeHtml(coverage.missing_components.slice(0, 8).join("、"))}</em>` : ""}
            ${coverage.missing_relations?.length ? `<em>缺失关系：${escapeHtml(coverage.missing_relations.slice(0, 6).join("、"))}</em>` : ""}
          `;
        }
        if (item.action === "llm_patch_merged" || item.action === "llm_gap_review_merged") {
          const patch = item.trial_patch || item.patch || {};
          const after = item.coverage_after || {};
          const neo4j = item.neo4j || {};
          const components = patch.components || [];
          const capNames = (patch.capabilities || []).map((cap) => cap.name).filter(Boolean);
          notifyRepairServiceStatus(item);
          return `
            <p><b>${item.action === "llm_gap_review_merged" ? "LLM 漏项复核" : "LLM 补全"}</b>${escapeHtml(patch.reason || "根据缺失业务能力补全拓扑知识")}</p>
            ${components.length ? `<em>新增组件：${escapeHtml(components.slice(0, 8).join("、"))}</em>` : ""}
            ${capNames.length ? `<em>新增能力：${escapeHtml(capNames.slice(0, 6).join("、"))}</em>` : ""}
            <p><b>补全后多维覆盖率</b>${escapeHtml(String(after.score ?? "未知"))}</p>
            ${renderCoverageDimensions(after.dimensions || {})}
            <p><b>Neo4j 写入</b>${neo4j.ok ? "成功" : escapeHtml(neo4j.error || neo4j.reason || "未写入")}</p>
          `;
        }
        if (item.action === "llm_patch_rejected") {
          notifyRepairServiceStatus(item);
          return `
            <p><b>LLM 补丁拒绝</b>${escapeHtml(item.message || "补丁未覆盖缺失业务能力")}</p>
            ${item.missing_capabilities?.length ? `<em>仍缺失：${escapeHtml(item.missing_capabilities.slice(0, 8).join("、"))}</em>` : ""}
          `;
        }
        if (item.action === "llm_patch_unavailable") {
          showToast("DeepSeek 补全失败", item.message || "知识图谱补全 Agent 未返回可用 patch。");
          return `<p><b>LLM 补全</b>${escapeHtml(item.message || "不可用")}</p>`;
        }
        return "";
      }).join("")}
    </div>
  `;
}

function renderCoverageDimensions(dimensions) {
  const labels = {
    business_capability: "能力",
    component: "组件",
    relation: "关系",
    quality_infrastructure: "基础设施",
    architecture_responsibility: "模式职责",
  };
  const entries = Object.entries(dimensions);
  if (!entries.length) return "";
  return `<p><b>维度</b>${entries.map(([key, item]) => `${labels[key] || key} ${item.score ?? "?"}`).map(escapeHtml).join(" · ")}</p>`;
}

function qualityPills(qualities) {
  return Object.entries(qualities)
    .map(([key, value]) => `<span>${escapeHtml(key)}：${escapeHtml(String(value))}</span>`)
    .join("");
}

function listItems(items, emptyText) {
  if (!items.length) return `<p>${escapeHtml(emptyText)}</p>`;
  return `<ul>${items.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>`;
}

function renderMarkdownReport(markdown) {
  if (!markdown.trim()) {
    reportEl.innerHTML = `<p class="empty">正在生成报告...</p>`;
    return;
  }
  reportEl.innerHTML = markdownToHtml(markdown);
}

function markdownToHtml(markdown) {
  const lines = markdown.split("\n");
  const html = [];
  let inList = false;
  let inTable = false;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      if (inList) {
        html.push("</ul>");
        inList = false;
      }
      if (inTable) {
        html.push("</tbody></table>");
        inTable = false;
      }
      continue;
    }

    if (line.startsWith("|") && line.endsWith("|")) {
      const cells = line.split("|").slice(1, -1).map((cell) => inlineMarkdown(cell.trim()));
      const isSeparator = cells.every((cell) => /^:?-{3,}:?$/.test(cell));
      if (isSeparator) continue;
      if (!inTable) {
        html.push("<table><tbody>");
        inTable = true;
      }
      const tag = html[html.length - 1] === "<table><tbody>" ? "th" : "td";
      html.push(`<tr>${cells.map((cell) => `<${tag}>${cell}</${tag}>`).join("")}</tr>`);
      continue;
    }

    if (inTable) {
      html.push("</tbody></table>");
      inTable = false;
    }

    if (line.startsWith("# ")) {
      html.push(`<h1>${inlineMarkdown(line.slice(2))}</h1>`);
      continue;
    }
    if (line.startsWith("## ")) {
      html.push(`<h2>${inlineMarkdown(line.slice(3))}</h2>`);
      continue;
    }
    if (line.startsWith("> ")) {
      html.push(`<blockquote>${inlineMarkdown(line.slice(2))}</blockquote>`);
      continue;
    }
    if (line.startsWith("- ")) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inlineMarkdown(line.slice(2))}</li>`);
      continue;
    }
    if (line.startsWith("√ ") || line.startsWith("× ")) {
      const isGood = line.startsWith("√ ");
      html.push(`<p class="${isGood ? "pro-line" : "con-line"}"><strong>${line.slice(0, 1)}</strong> ${inlineMarkdown(line.slice(2))}</p>`);
      continue;
    }
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
    html.push(`<p>${inlineMarkdown(line)}</p>`);
  }

  if (inList) html.push("</ul>");
  if (inTable) html.push("</tbody></table>");
  return html.join("");
}

function inlineMarkdown(text) {
  return escapeHtml(text)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/ {2}$/g, "<br>");
}

async function renderTopology(graphs, diagrams = {}) {
  const hasDiagrams = diagrams && Object.keys(diagrams).length;
  if (!hasDiagrams) {
    topologyTabsEl.innerHTML = "";
    renderTopologyUnavailable("后端没有返回 Mermaid 拓扑源码，无法渲染架构图。请检查 topology_diagrams 生成链路。");
    return;
  }
  currentTopologyGraphs = graphs || {};
  currentTopologyJson = graphs ? JSON.stringify(graphs, null, 2) : "";
  const entries = Object.entries(diagrams);
  const completeEntry = entries.find(([name]) => name.includes("完整图")) || entries[0];
  topologyTabsEl.innerHTML = "";
  if (completeEntry) {
    currentTopologyName = completeEntry[0];
    await drawMermaidTopology(completeEntry[0], completeEntry[1]);
  }
}

function renderTopologyLoading() {
  currentTopologyJson = "";
  currentTopologySource = "";
  currentTopologySvg = "";
  currentTopologyGraphs = {};
  currentTopologyName = "";
  currentInteractiveGraph = null;
  topologyScale = 1;
  modalTopologyScale = 1;
  closeTopologyModal();
  topologyTabsEl.innerHTML = "";
  topologyEl.innerHTML = `
    <div class="topology-loading">
      <div class="spinner"></div>
      <strong>架构图生成中</strong>
      <span>正在结合需求特征、知识图谱和规则校验生成定制拓扑</span>
    </div>
  `;
}

function renderTopologyUnavailable(message) {
  currentTopologyJson = "";
  currentTopologySource = "";
  currentTopologySvg = "";
  currentInteractiveGraph = null;
  topologyScale = 1;
  closeTopologyModal();
  topologyEl.innerHTML = `
    <div class="topology-loading">
      <strong>架构图未生成</strong>
      <span>${escapeHtml(message)}</span>
    </div>
  `;
}

async function drawMermaidTopology(name, source) {
  currentTopologySource = source || "";
  topologyScale = 1;
  currentInteractiveGraph = null;
  if (!currentTopologySource.trim()) {
    renderTopologyUnavailable(`${name || "当前视图"} 的 Mermaid 拓扑源码为空。`);
    return;
  }
  if (!window.mermaid) {
    renderTopologyUnavailable("Mermaid 渲染库未加载，请检查网络或刷新页面。");
    return;
  }
  try {
    const id = `topology-mermaid-${Date.now()}`;
    const { svg } = await mermaid.render(id, currentTopologySource);
    currentTopologySvg = svg;
    topologyEl.innerHTML = `<div class="topology-canvas mermaid-mode">${svg}</div>`;
    fitTopologyToContainer();
  } catch (error) {
    currentTopologySvg = "";
    showToast("架构图渲染失败", "Mermaid 无法渲染当前拓扑源码，请检查后端生成的 Mermaid 语法。");
    topologyEl.innerHTML = `<pre class="diagram-error">${escapeHtml(currentTopologySource)}</pre>`;
  }
}

function renderDraggableTopology(source) {
  const graph = normalizeTopologyGraph(source);
  if (!graph.nodes.length) return false;

  const layout = layoutTopologyGraph(graph);
  currentInteractiveGraph = { ...graph, positions: layout.positions, width: layout.width, height: layout.height };
  currentTopologySvg = buildInteractiveTopologySvg();
  topologyEl.innerHTML = `
    <div class="topology-canvas svg-mode">
      ${currentTopologySvg}
    </div>
  `;
  return true;
}

function normalizeTopologyGraph(graph) {
  const nodes = Array.isArray(graph?.nodes)
    ? graph.nodes
        .filter((node) => node && node.id)
        .map((node) => ({
          id: String(node.id),
          label: String(node.label || node.name || node.id),
          layer: String(node.layer || "组件"),
        }))
    : [];
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = Array.isArray(graph?.edges)
    ? graph.edges
        .filter((edge) => edge && nodeIds.has(String(edge.source)) && nodeIds.has(String(edge.target)))
        .map((edge) => ({
          source: String(edge.source),
          target: String(edge.target),
          label: String(edge.label || ""),
          kind: edge.kind === "event" || edge.kind === "responsibility" ? edge.kind : "sync",
          category: String(edge.category || edge.kind || "sync"),
        }))
    : [];
  const layers = Array.isArray(graph?.layers)
    ? graph.layers.map((layer) => String(layer))
    : Array.from(new Set(nodes.map((node) => node.layer)));
  return { nodes, edges, layerOrder: layers };
}

function layoutTopologyGraph(graph) {
  const layerOrder = graph.layerOrder.length ? graph.layerOrder : ["组件"];
  const positions = {};
  const nodeWidth = 140;
  const nodeHeight = 58;
  const gapX = 54;
  const gapY = 56;
  const padding = 44;
  let width = 980;
  let y = padding;

  for (const layer of layerOrder) {
    const layerNodes = graph.nodes.filter((node) => node.layer === layer);
    if (!layerNodes.length) continue;
    const columns = Math.min(5, Math.max(1, Math.ceil(Math.sqrt(layerNodes.length * 1.8))));
    layerNodes.forEach((node, index) => {
      const col = index % columns;
      const row = Math.floor(index / columns);
      positions[node.id] = {
        x: padding + col * (nodeWidth + gapX),
        y: y + row * (nodeHeight + gapY),
      };
    });
    width = Math.max(width, padding * 2 + columns * nodeWidth + (columns - 1) * gapX);
    y += Math.ceil(layerNodes.length / columns) * (nodeHeight + gapY) + 44;
  }
  return { positions, width, height: Math.max(420, y + padding) };
}

function bindTopologyDrag() {
  const board = topologyEl.querySelector(".topology-board");
  if (!board || !currentInteractiveGraph) return;
  board.querySelectorAll(".topology-node").forEach((nodeEl) => {
    nodeEl.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      const nodeId = nodeEl.dataset.nodeId;
      const boardRect = board.getBoundingClientRect();
      const nodeRect = nodeEl.getBoundingClientRect();
      const scale = topologyScale || 1;
      const offsetX = (event.clientX - nodeRect.left) / scale;
      const offsetY = (event.clientY - nodeRect.top) / scale;
      nodeEl.setPointerCapture(event.pointerId);
      nodeEl.classList.add("dragging");

      const move = (moveEvent) => {
        const nextX = (moveEvent.clientX - boardRect.left) / scale - offsetX;
        const nextY = (moveEvent.clientY - boardRect.top) / scale - offsetY;
        const x = clamp(nextX, 8, currentInteractiveGraph.width - nodeEl.offsetWidth - 8);
        const y = clamp(nextY, 8, currentInteractiveGraph.height - nodeEl.offsetHeight - 8);
        currentInteractiveGraph.positions[nodeId] = { x, y };
        nodeEl.style.left = `${x}px`;
        nodeEl.style.top = `${y}px`;
        redrawTopologyLinks();
      };

      const end = () => {
        nodeEl.classList.remove("dragging");
        nodeEl.removeEventListener("pointermove", move);
        nodeEl.removeEventListener("pointerup", end);
        nodeEl.removeEventListener("pointercancel", end);
        currentTopologySvg = buildInteractiveTopologySvg();
      };

      nodeEl.addEventListener("pointermove", move);
      nodeEl.addEventListener("pointerup", end);
      nodeEl.addEventListener("pointercancel", end);
    });
  });
}

function redrawTopologyLinks() {
  const board = topologyEl.querySelector(".topology-board");
  const svg = topologyEl.querySelector(".topology-links");
  if (!board || !svg || !currentInteractiveGraph) return;
  const nodeEls = new Map(
    Array.from(board.querySelectorAll(".topology-node")).map((nodeEl) => [nodeEl.dataset.nodeId, nodeEl])
  );
  svg.innerHTML = `
    <defs>
      <marker id="topology-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
        <path d="M0,0 L8,4 L0,8 z" fill="#6b7280"></path>
      </marker>
    </defs>
  `;
  currentInteractiveGraph.edges.forEach((edge) => {
    const sourceEl = nodeEls.get(edge.source);
    const targetEl = nodeEls.get(edge.target);
    if (!sourceEl || !targetEl) return;
    const source = nodeCenter(sourceEl);
    const target = nodeCenter(targetEl);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", curvedPath(source, target));
    path.setAttribute("class", `topology-link ${edge.kind === "event" ? "event" : ""}`);
    path.setAttribute("marker-end", "url(#topology-arrow)");
    svg.appendChild(path);
    if (edge.label) {
      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("x", String((source.x + target.x) / 2));
      text.setAttribute("y", String((source.y + target.y) / 2 - 6));
      text.setAttribute("class", "topology-link-label");
      text.textContent = edge.label;
      svg.appendChild(text);
    }
  });
}

function nodeCenter(nodeEl) {
  return {
    x: nodeEl.offsetLeft + nodeEl.offsetWidth / 2,
    y: nodeEl.offsetTop + nodeEl.offsetHeight / 2,
  };
}

function curvedPath(source, target) {
  const deltaY = Math.max(50, Math.abs(target.y - source.y) * 0.45);
  const c1 = { x: source.x, y: source.y + deltaY };
  const c2 = { x: target.x, y: target.y - deltaY };
  return `M ${source.x} ${source.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${target.x} ${target.y}`;
}

function buildInteractiveTopologySvg() {
  if (!currentInteractiveGraph) return currentTopologySvg || "";
  const nodesById = new Map(currentInteractiveGraph.nodes.map((node) => [node.id, node]));
  const nodeWidth = 140;
  const nodeHeight = 58;
  const paths = currentInteractiveGraph.edges.map((edge) => {
    const source = currentInteractiveGraph.positions[edge.source];
    const target = currentInteractiveGraph.positions[edge.target];
    if (!source || !target) return "";
    const sourceCenter = { x: source.x + nodeWidth / 2, y: source.y + nodeHeight / 2 };
    const targetCenter = { x: target.x + nodeWidth / 2, y: target.y + nodeHeight / 2 };
    const labelX = (sourceCenter.x + targetCenter.x) / 2;
    const labelY = (sourceCenter.y + targetCenter.y) / 2 - 6;
    return `
      <path d="${curvedPath(sourceCenter, targetCenter)}" fill="none" stroke="#7a869a" stroke-width="1.5" ${edge.kind === "event" ? 'stroke-dasharray="5 4"' : ""} marker-end="url(#arrow)" />
      ${edge.label ? `<text x="${labelX}" y="${labelY}" text-anchor="middle" font-size="11" fill="#52606d">${escapeHtml(edge.label)}</text>` : ""}
    `;
  }).join("");
  const boxes = Object.entries(currentInteractiveGraph.positions).map(([nodeId, position]) => {
    const node = nodesById.get(nodeId);
    if (!node) return "";
    return `
      <rect x="${position.x}" y="${position.y}" width="${nodeWidth}" height="${nodeHeight}" rx="8" fill="#ffffff" stroke="#cfd8e3" stroke-width="1.2" />
      <text x="${position.x + nodeWidth / 2}" y="${position.y + 27}" text-anchor="middle" font-size="13" font-weight="700" fill="#243447">${escapeHtml(node.label)}</text>
      <text x="${position.x + nodeWidth / 2}" y="${position.y + 45}" text-anchor="middle" font-size="10" fill="#667085">${escapeHtml(node.layer)}</text>
    `;
  }).join("");
  return `
    <svg xmlns="http://www.w3.org/2000/svg" width="${currentInteractiveGraph.width}" height="${currentInteractiveGraph.height}" viewBox="0 0 ${currentInteractiveGraph.width} ${currentInteractiveGraph.height}">
      <defs>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" fill="#7a869a" />
        </marker>
      </defs>
      ${paths}
      ${boxes}
    </svg>
  `.trim();
}

function setTopologyScale(value) {
  topologyScale = clamp(value, 0.35, 2.8);
  const canvas = topologyEl.querySelector(".topology-canvas");
  if (!canvas) return;
  const svg = canvas.querySelector("svg");
  if (!svg) return;
  applySvgScale(svg, topologyScale);
  if (currentInteractiveGraph) {
    canvas.style.width = `${Math.round(currentInteractiveGraph.width * topologyScale) + 32}px`;
    canvas.style.height = `${Math.round(currentInteractiveGraph.height * topologyScale) + 32}px`;
  }
}

function fitTopologyToContainer() {
  const svg = topologyEl.querySelector(".topology-canvas svg");
  if (!svg) return;
  const svgWidth = getSvgSize(svg).width;
  const available = Math.max(320, topologyEl.clientWidth - 48);
  const nextScale = Math.min(1.2, Math.max(0.35, available / svgWidth));
  setTopologyScale(nextScale);
}

function openTopologyModal() {
  if (!currentTopologySvg) {
    statusEl.textContent = "暂无可查看的架构图";
    showToast("架构图未生成", "当前还没有可放大的 SVG 拓扑图。", "info");
    return;
  }
  modalTopologyScale = 1;
  topologyModalCanvasEl.innerHTML = `<div class="topology-canvas modal">${currentTopologySvg}</div>`;
  topologyModalEl.classList.add("open");
  topologyModalEl.setAttribute("aria-hidden", "false");
  fullscreenTopologyBtn.textContent = "关闭大图";
  fitModalTopology();
}

function toggleTopologyModal() {
  if (topologyModalEl.classList.contains("open")) {
    closeTopologyModal();
    return;
  }
  openTopologyModal();
}

function closeTopologyModal() {
  topologyModalEl.classList.remove("open");
  topologyModalEl.setAttribute("aria-hidden", "true");
  topologyModalCanvasEl.innerHTML = "";
  fullscreenTopologyBtn.textContent = "大图查看";
}

function setModalTopologyScale(value) {
  modalTopologyScale = clamp(value, 0.35, 4);
  const canvas = topologyModalCanvasEl.querySelector(".topology-canvas");
  if (!canvas) return;
  const svg = canvas.querySelector("svg");
  if (!svg) return;
  applySvgScale(svg, modalTopologyScale);
}

function fitModalTopology() {
  const svg = topologyModalCanvasEl.querySelector("svg");
  if (!svg) return;
  const svgWidth = getSvgSize(svg).width;
  const available = Math.max(480, topologyModalCanvasEl.clientWidth - 80);
  const nextScale = Math.min(1.4, Math.max(0.35, available / svgWidth));
  setModalTopologyScale(nextScale);
}

function applySvgScale(svg, scale) {
  const size = getSvgSize(svg);
  svg.style.width = `${Math.round(size.width * scale)}px`;
  svg.style.height = `${Math.round(size.height * scale)}px`;
}

function getSvgSize(svg) {
  const viewBox = svg.getAttribute("viewBox");
  if (viewBox) {
    const parts = viewBox.split(/\s+/).map(Number);
    if (parts.length === 4 && parts[2] > 0 && parts[3] > 0) {
      return { width: parts[2], height: parts[3] };
    }
  }
  const width = parseFloat(svg.getAttribute("width") || "");
  const height = parseFloat(svg.getAttribute("height") || "");
  if (width > 0 && height > 0) return { width, height };
  const rect = svg.getBoundingClientRect();
  return { width: rect.width || 1000, height: rect.height || 700 };
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

async function copyText(value, successMessage) {
  if (!value) {
    statusEl.textContent = "暂无可复制内容";
    showToast("复制失败", "当前没有可复制的内容。");
    return;
  }
  try {
    await navigator.clipboard.writeText(value);
    statusEl.textContent = successMessage;
    showToast("复制成功", successMessage, "info");
  } catch (error) {
    try {
      fallbackCopy(value);
      statusEl.textContent = successMessage;
      showToast("复制成功", successMessage, "info");
    } catch (fallbackError) {
      statusEl.textContent = "复制失败";
      showToast("复制失败", "浏览器剪贴板服务不可用，请检查权限设置。");
    }
  }
}

function fallbackCopy(value) {
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

function notifyRepairServiceStatus(item) {
  if (item.semantic_available === false) {
    showServiceToast(
      `embedding:${item.round || ""}`,
      "Embedding 语义召回不可用",
      "未配置或无法调用 Embedding 服务，本轮补全的不确定节点只会临时用于拓扑，不写入 Neo4j。"
    );
  }
  const neo4j = item.neo4j || {};
  if (neo4j.pending) {
    showServiceToast(
      `neo4j-pending:${item.round || ""}:${neo4j.reason || ""}`,
      "知识库进化后台执行",
      neo4j.reason || "Embedding 规范化和 Neo4j 写入已转入后台，不阻塞本次架构图生成。",
      "info"
    );
  }
  if (neo4j.ok === false && !neo4j.skipped && !neo4j.pending) {
    showServiceToast(
      `neo4j-error:${item.round || ""}:${neo4j.error || neo4j.reason || ""}`,
      "Neo4j 写入失败",
      neo4j.error || neo4j.reason || "知识补丁未能写入图数据库。"
    );
  }
  if (neo4j.skipped) {
    showServiceToast(
      `neo4j-skipped:${item.round || ""}:${neo4j.reason || ""}`,
      "Neo4j 写入已跳过",
      neo4j.reason || "当前补丁没有达到永久写入条件。",
      "info"
    );
  }
}

function classifyServiceError(message) {
  const text = String(message || "");
  if (/需求解析|原始需求为空|业务特征|结构化需求|JSON 校验/i.test(text)) {
    return {
      title: "需求解析失败",
      message: text || "DeepSeek 未能把当前需求解析成有效结构化特征，请稍后重试或补充更多业务动作描述。",
    };
  }
  if (/Embedding|语义|向量/i.test(text)) {
    return {
      title: "Embedding 服务失败",
      message: text || "语义向量召回不可用，请检查 EMBEDDING_* 配置。",
    };
  }
  if (/Neo4j|Aura|图数据库|Cypher/i.test(text)) {
    return {
      title: "Neo4j 服务失败",
      message: text || "图数据库连接或写入失败，请检查 AuraDB 实例和账号配置。",
    };
  }
  if (/DeepSeek|LLM|模型|API Key/i.test(text)) {
    return {
      title: "DeepSeek 调用失败",
      message: text || "大模型服务未返回可用结果，请检查 API Key、模型名或网络连接。",
    };
  }
  if (/Failed to fetch|NetworkError|network error|Load failed|fetch failed/i.test(text)) {
    return {
      title: "推荐接口连接失败",
      message: text || "前端无法连接推荐服务，请确认后端服务正在运行。",
    };
  }
  return {
    title: "服务调用失败",
    message: text || "系统调用过程中出现异常，请查看 Agent 追踪或后端日志。",
  };
}

function showToast(title, message, type = "error") {
  if (!toastRootEl) return;
  const toast = document.createElement("div");
  toast.className = `toast ${type === "info" ? "info" : ""}`;
  toast.innerHTML = `
    <strong>${escapeHtml(title)}</strong>
    <span>${escapeHtml(message)}</span>
  `;
  toastRootEl.appendChild(toast);
  window.setTimeout(() => {
    toast.remove();
  }, 3000);
}

function showServiceToast(key, title, message, type = "error") {
  if (serviceNoticeKeys.has(key)) return;
  serviceNoticeKeys.add(key);
  showToast(title, message, type);
  window.setTimeout(() => {
    serviceNoticeKeys.delete(key);
  }, 3200);
}
