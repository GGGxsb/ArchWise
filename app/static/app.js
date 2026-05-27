mermaid.initialize({ startOnLoad: false, theme: "base" });

const requirementEl = document.querySelector("#requirement");
const topKEl = document.querySelector("#topK");
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
const copyMermaidBtn = document.querySelector("#copyMermaidBtn");
const copySvgBtn = document.querySelector("#copySvgBtn");
let reportMarkdown = "";
let currentTopologySource = "";
let currentTopologySvg = "";

btn.addEventListener("click", recommend);
copyMermaidBtn.addEventListener("click", () => copyText(currentTopologySource, "已复制 Mermaid 源码"));
copySvgBtn.addEventListener("click", () => copyText(currentTopologySvg, "已复制 SVG"));

async function recommend() {
  const requirement = requirementEl.value.trim();
  if (!requirement) {
    statusEl.textContent = "请输入需求";
    return;
  }
  const topK = Number(topKEl.value || 12);
  statusEl.textContent = "分析中...";
  btn.disabled = true;
  reportMarkdown = "";
  renderMarkdownReport("");
  renderTopologyLoading();
  try {
    const response = await fetch("/api/recommend/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requirement, top_k: topK }),
    });
    if (!response.ok || !response.body) throw new Error("流式推荐接口返回异常");
    await consumeRecommendationStream(response.body);
  } catch (error) {
    statusEl.textContent = `${error.message}，改用普通接口`;
    await recommendClassic(requirement, topK);
  } finally {
    btn.disabled = false;
  }
}

async function recommendClassic(requirement, topK = 12) {
  const response = await fetch("/api/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ requirement, top_k: topK }),
  });
  if (!response.ok) throw new Error("推荐接口返回异常");
  const data = await response.json();
  renderInitial(data);
  reportMarkdown = data.report;
  renderMarkdownReport(reportMarkdown);
  await renderTopology(data.topology_diagrams);
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

  if (event === "initial") {
    renderInitial(payload);
    reportMarkdown = "";
    renderMarkdownReport("");
    renderTopologyLoading();
    statusEl.textContent = "DeepSeek 正在生成评估报告...";
  }
  if (event === "report_delta") {
    reportMarkdown += payload.delta;
    renderMarkdownReport(reportMarkdown);
    reportEl.scrollTop = reportEl.scrollHeight;
  }
  if (event === "topology") {
    renderTrace(payload.trace);
    renderDecisionTrace(payload.decision_trace);
    await renderTopology(payload.topology_diagrams);
    statusEl.textContent = "正在渲染定制拓扑...";
  }
  if (event === "done") {
    statusEl.textContent = "已生成";
  }
}

function renderInitial(data) {
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

  featuresEl.className = "feature-list";
  featuresEl.innerHTML = `
    <div><b>领域</b><span>${escapeHtml(data.features.domain)}</span></div>
    <div><b>数据流</b><span>${escapeHtml(data.features.data_flow)}</span></div>
    <div><b>关键词</b><span>${data.features.keywords.map(escapeHtml).join("、") || "无"}</span></div>
    <div><b>模糊点</b><span>${data.features.ambiguity_notes.map(escapeHtml).join("；") || "无明显模糊点"}</span></div>
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

async function renderTopology(diagrams) {
  if (!diagrams || !Object.keys(diagrams).length) {
    renderTopologyLoading();
    return;
  }
  const entries = Object.entries(diagrams);
  topologyTabsEl.innerHTML = entries
    .map(([name], index) => `<button type="button" class="${index === 0 ? "active" : ""}" data-name="${escapeHtml(name)}">${escapeHtml(name)}</button>`)
    .join("");
  topologyTabsEl.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      topologyTabsEl.querySelectorAll("button").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      drawDiagram(button.dataset.name, diagrams[button.dataset.name]);
    });
  });
  if (entries[0]) await drawDiagram(entries[0][0], entries[0][1]);
}

function renderTopologyLoading() {
  currentTopologySource = "";
  currentTopologySvg = "";
  topologyTabsEl.innerHTML = "";
  topologyEl.innerHTML = `
    <div class="topology-loading">
      <div class="spinner"></div>
      <strong>架构图生成中</strong>
      <span>正在结合需求特征、知识图谱和规则校验生成定制拓扑</span>
    </div>
  `;
}

async function drawDiagram(name, source) {
  const id = `diagram-${Date.now()}`;
  currentTopologySource = source;
  try {
    const { svg } = await mermaid.render(id, source);
    currentTopologySvg = svg;
    topologyEl.innerHTML = svg;
  } catch (error) {
    currentTopologySvg = "";
    topologyEl.innerHTML = `<pre class="diagram-error">${escapeHtml(source)}</pre>`;
  }
}

async function copyText(value, successMessage) {
  if (!value) {
    statusEl.textContent = "暂无可复制内容";
    return;
  }
  try {
    await navigator.clipboard.writeText(value);
    statusEl.textContent = successMessage;
  } catch (error) {
    fallbackCopy(value);
    statusEl.textContent = successMessage;
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
  return value.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}
