"use strict";

const $ = (id) => document.getElementById(id);
// 화면 상태만 보관한다. API 필드명·상태 코드는 서버 계약과 동일하게 유지한다.
const state = {
  config: null,
  mode: "demo",
  report: null,
  selected: null,
  timer: null,
  loadRevision: 0,
  busy: false,
  reviewing: false,
};
const statusNames = {running: "분석 중", draft: "검토 대기", approved: "검토 승인", held: "검토 보류", failed: "분석 실패"};
const findingNames = {aligned: "값 일치", conflict: "값 상충", insufficient: "근거 부족", not_comparable: "직접 비교 불가", revision_review: "수정 공지 검토"};
const confidenceNames = {unassessed: "평가 불가", low: "낮음", medium: "중간", high: "높음 · 사람 지정"};
const certaintyNames = {reported: "보도·공지된 값", estimated: "추정", possible: "가능성", planned: "예정", unconfirmed: "미확인"};
const quantifierNames = {exact: "정확값 표현", approx: "약", at_least: "최소", at_most: "최대"};
const polarityNames = {positive: "긍정", negative: "부정", unknown: "미확정"};
const langNames = {ko: "한국어", zh: "중국어", ja: "일본어", en: "영어", unknown: "언어 미확인"};
const ns = "http://www.w3.org/2000/svg";

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function svgEl(tag, attrs, text) {
  const node = document.createElementNS(ns, tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
  if (text !== undefined) node.textContent = text;
  return node;
}
function message(text, error = false) {
  $("message").textContent = text;
  $("message").classList.toggle("error", error);
}
function timeText(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "시각 미확인" : date.toLocaleString("ko-KR", {hour12: false});
}
function cut(text, n) {
  return text.length > n ? text.slice(0, n - 1) + "…" : text;
}

function utcTime(normalized) {
  return normalized.slice(11, 16) + " UTC";
}
function sourceLink(source, text) {
  if (!source.url) return el("span", text + " / 가상 문서");
  try {
    const url = new URL(source.url);
    if (url.protocol !== "https:") return el("span", "원문 주소 미확인");
    const link = el("a", text);
    link.href = url.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
  } catch { return el("span", "원문 주소 미확인"); }
}
async function api(path, options = {}) {
  const response = await fetch(path, {headers: {"Content-Type": "application/json"}, ...options});
  if (!response.ok) {
    let detail = "요청 실패 (" + response.status + ")";
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : "입력 형식을 확인하세요.";
    } catch { /* JSON이 아니면 안전한 상태 안내를 유지한다. */ }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.json();
}
function setMode(mode) {
  state.mode = mode;
  $("demo-mode").setAttribute("aria-pressed", String(mode === "demo"));
  $("live-mode").setAttribute("aria-pressed", String(mode === "live"));
  $("question").readOnly = mode === "demo";
  $("question").value = mode === "demo" ? state.config.demo_question : state.config.live_preset;
  $("run-button").textContent = mode === "demo" ? "데모 분석 실행 →" : "공개 원문 분석 →";
  $("mode-notice").textContent = mode === "demo"
    ? "가상 문서 4개 · 실제 사건 아님 · 외부 API 호출 및 크레딧 사용 없음. 고정 질문만 지원합니다."
    : "선택한 언어별로 검색하지만 해당 언어의 원문 확보는 보장되지 않습니다. 실행 시 API 사용량이 발생합니다.";
  $("config-info").textContent = state.config.live_ready
    ? `${state.config.model} / 최대 ${state.config.max_documents}문서 · 문서당 ${state.config.max_document_chars.toLocaleString()}자`
    : "실시간 모드: 서버 .env에 OpenAI · Tavily 키 설정 필요";
  updateRunControls();
}
function updateRunControls() {
  $("run-button").disabled = state.busy ||
    (state.mode === "live" && !state.config?.live_ready);
  $("demo-mode").disabled = state.busy;
  $("live-mode").disabled = state.busy;
  $("languages").disabled = state.busy || state.mode === "demo";
}

function setBusy(busy) {
  state.busy = busy;
  updateRunControls();
}

function updateReviewControls() {
  const report = state.report;
  const disabled = state.reviewing || !report || report.status === "running" ||
    report.status === "failed" || !report.findings.length;
  $("review-form").querySelectorAll("input,select,textarea,button").forEach(node => {
    node.disabled = disabled;
  });
}
// 진행 상태와 근거 시각화. 원문·번역은 textContent로만 넣어 HTML 실행을 막는다.
function renderSteps(report) {
  $("progress").hidden = false;
  const labels = {
    pending: "대기", running: "진행", done: "완료",
    partial: "일부 완료", failed: "실패",
  };
  $("progress").replaceChildren(...report.steps.map((step, index) => {
    const node = el("div", undefined, "step");
    node.dataset.status = step.status;
    node.append(
      el("div", `0${index + 1} / ${labels[step.status]}`, "step-index"),
      el("strong", step.name),
      el("small", step.detail),
    );
    return node;
  }));
}

function renderMap(finding, claims, sources) {
  const height = Math.max(150, claims.length * 68 + 55);
  const svg = svgEl("svg", {
    viewBox: `0 0 650 ${height}`,
    role: "img",
    "aria-label": `${finding.label}: ${claims.length}개 주장의 원문 출처, 정규화 값, 비교 결과 연결도`,
  });
  svg.append(
    svgEl("text", {x: 16, y: 23, class: "map-head"}, "원문 / 출처 그룹"),
    svgEl("text", {x: 230, y: 23, class: "map-head"}, "비교에 사용한 값"),
    svgEl("text", {x: 495, y: 23, class: "map-head"}, "비교 결과"),
  );
  const middleY = 38 + (height - 45) / 2;
  for (const [index, claim] of claims.entries()) {
    const y = 44 + index * 68;
    const source = sources.get(claim.source_id);
    const lineClass = "map-line" + (finding.status === "conflict" ? " alert" : "");
    svg.append(svgEl("path", {
      d: `M 193 ${y + 23} L 218 ${y + 23} M 466 ${y + 23} C 478 ${y + 23} 478 ${middleY} 491 ${middleY}`,
      class: lineClass,
    }));
    svg.append(
      svgEl("rect", {x: 12, y, width: 181, height: 47, class: "map-node"}),
      svgEl("text", {x: 22, y: y + 19, class: "map-source"},
        `${source.id} · ${langNames[source.language] || source.language}`),
      svgEl("text", {x: 22, y: y + 36, class: "map-sub"}, cut(source.publisher_group, 25)),
    );
    const value = claim.normalized?.includes("T")
      ? utcTime(claim.normalized) : claim.normalized || claim.value;
    svg.append(
      svgEl("rect", {x: 218, y, width: 248, height: 47, class: "map-node"}),
      svgEl("text", {x: 230, y: y + 19, class: "map-label"}, cut(value, 32)),
      svgEl("text", {x: 230, y: y + 36, class: "map-sub"},
        `${claim.id} / ${certaintyNames[claim.certainty]}`),
    );
  }
  svg.append(
    svgEl("rect", {x: 491, y: middleY - 31, width: 147, height: 64, class: "map-result"}),
    svgEl("text", {x: 503, y: middleY - 7, class: "map-label"}, findingNames[finding.status]),
    svgEl("text", {x: 503, y: middleY + 13, class: "map-sub"},
      `${finding.publisher_groups}개 도메인 그룹`),
  );
  if (!claims.length) {
    svg.append(svgEl("text", {x: 20, y: 90, class: "map-label"}, "대응하는 원문 근거 없음"));
  }
  $("evidence-map").replaceChildren(svg);
}

function renderTimeline(claims) {
  const timed = claims.filter(claim =>
    claim.time_local && claim.normalized && !Number.isNaN(Date.parse(claim.normalized)));
  $("timeline-panel").hidden = timed.length === 0;
  if (!timed.length) return;

  const values = timed.map(claim => Date.parse(claim.normalized));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const svg = svgEl("svg", {
    viewBox: `0 0 650 ${timed.length * 35 + 42}`,
    role: "img",
    "aria-label": "정규화된 UTC 시각. 같은 시각이면 점이 같은 위치에 표시됩니다.",
  });
  for (const [index, claim] of timed.entries()) {
    const y = 25 + index * 35;
    const x = max === min ? 390 : 260 + (Date.parse(claim.normalized) - min) / (max - min) * 240;
    svg.append(
      svgEl("text", {x: 0, y: y + 4, class: "map-sub"},
        `${claim.source_id} / ${claim.time_local} ${claim.timezone}`),
      svgEl("line", {x1: 250, x2: 510, y1: y, y2: y, class: "map-line"}),
      svgEl("circle", {cx: x, cy: y, r: 4, fill: "#edbb66"}),
      svgEl("text", {x: 525, y: y + 4, class: "map-sub"}, utcTime(claim.normalized)),
    );
  }
  svg.append(svgEl("text", {x: 0, y: timed.length * 35 + 28, class: "map-sub"},
    `${timed[0].normalized.slice(0, 10)} UTC / 원문 시간대가 명시된 주장만 표시`));
  $("timeline").replaceChildren(svg);
}

function renderFinding() {
  const report = state.report;
  const finding = report.findings.find(item => item.id === state.selected);
  if (!finding) return;
  const claims = report.claims.filter(claim => finding.claim_ids.includes(claim.id));
  const sources = new Map(report.sources.map(source => [source.id, source]));
  $("findings").querySelectorAll("button").forEach(button => {
    button.setAttribute("aria-pressed", String(button.dataset.id === finding.id));
  });
  $("finding-title").textContent = finding.label;
  $("finding-status").textContent = findingNames[finding.status];
  $("finding-status").classList.toggle("alert", finding.status === "conflict");
  $("finding-reason").textContent = finding.reason;
  $("confidence").value = finding.confidence;
  $("review-note").value = finding.review_note;
  renderMap(finding, claims, sources);
  renderTimeline(claims);
  $("claim-table").replaceChildren(...claims.map(claim => {
    const row = el("tr");
    const language = langNames[sources.get(claim.source_id).language] || "미확인";
    row.append(
      el("td", `${claim.id} / ${language}`),
      el("td", claim.value),
      el("td", `${certaintyNames[claim.certainty]} · ${quantifierNames[claim.quantifier]} · ${polarityNames[claim.polarity]}`),
      el("td", claim.normalized || "미확정"),
    );
    return row;
  }));
  $("quotes").replaceChildren(...claims.map(claim => {
    const source = sources.get(claim.source_id);
    const article = el("article", undefined, "quote");
    const header = el("header");
    header.append(
      el("span", `${claim.id} · ${claim.paragraph_id} · ${claim.attribution}`),
      sourceLink(source, "원문 열기"),
    );
    article.append(
      header,
      el("blockquote", claim.quote),
      el("p", "한국어 번역 · " + claim.translation, "translation"),
      el("p", claim.normalization_note, "normalization"),
    );
    return article;
  }));
  if (!claims.length) {
    $("quotes").append(el("p", "원문에 없는 정보는 반박으로 해석하지 않습니다.", "muted"));
  }
}

// 보고서 전체는 완료 시에만 그린다. 진행 조회마다 SVG를 다시 만들지 않는다.
function renderReport(report) {
  state.report = report;
  renderSteps(report);
  const complete = report.status !== "running";
  setBusy(!complete);
  $("workspace").hidden = !complete;
  $("empty").hidden = complete || report.status === "running";
  if (!complete) return;
  renderReportHeader(report);
  renderFindings(report);
  renderSources(report);
  $("warnings").replaceChildren(...report.warnings.map(w => el("li", w)));
  $("usage").textContent = `LLM ${report.model_calls}회 / 확인된 입력 ${report.input_tokens.toLocaleString()} · 출력 ${report.output_tokens.toLocaleString()} 토큰 / 비용 청구액 아님`;
  renderAudit(report);
}

function renderReportHeader(report) {
  $("report-title").textContent = report.status === "failed" ? "분석 미완료" : "다국어 근거 검토";
  $("report-meta").textContent =
    `v${report.version} · ${timeText(report.created_at)} · ${report.sources.length}문서 / ${report.claims.length}주장`;
  $("report-state").textContent = statusNames[report.status];
  $("report-question").textContent = report.question;
  $("mode-banner").textContent = report.mode === "demo"
    ? "가상 데이터 데모 / 실제 사건 아님 / 검색·LLM API 호출 없음 / 승인해도 가상 자료입니다."
    : "공개 원문 분석 / 출처의 주장을 비교한 결과이며 진위 판정이 아닙니다. 원문과 독립성을 확인하세요.";
  $("export").href = `/api/runs/${report.id}/export`;
  $("export").setAttribute("download", "");
}

function renderFindings(report) {
  $("findings").replaceChildren(...report.findings.map(finding => {
    const button = el("button", undefined, "finding-button");
    button.type = "button";
    button.dataset.id = finding.id;
    button.append(
      el("strong", finding.label),
      el("span", `${findingNames[finding.status]} / ${confidenceNames[finding.confidence]}`),
    );
    button.addEventListener("click", () => {
      state.selected = finding.id;
      renderFinding();
    });
    return button;
  }));
  if (!report.findings.some(finding => finding.id === state.selected)) {
    state.selected = report.findings[0]?.id || null;
  }
  updateReviewControls();
  if (state.selected) {
    renderFinding();
    return;
  }
  $("finding-title").textContent = "검토 가능한 결과 없음";
  $("finding-status").textContent = "미완료";
  $("finding-reason").textContent = "아래 수집 한계를 확인하고 다시 실행하세요.";
  ["evidence-map", "claim-table", "quotes", "timeline"].forEach(id => $(id).replaceChildren());
  $("timeline-panel").hidden = true;
}

function renderSources(report) {
  $("source-count").textContent = `${report.sources.length}개 / 게시 시각 미확인은 추정하지 않음`;
  $("sources").replaceChildren(...report.sources.map(source => {
    const row = el("div", undefined, "source-row");
    const title = el("div");
    const group = el("div");
    const dates = el("div");
    title.append(
      sourceLink(source, source.title),
      el("small", `${langNames[source.language] || source.language} · ${source.truncated ? '본문 일부 분석' : '수집 본문 범위 분석'}`),
    );
    group.append(
      el("strong", source.publisher_group),
      el("small", "독립성 미확인 / 번역·재인용 확인 필요"),
    );
    dates.append(
      el("span", "수집 " + timeText(source.collected_at)),
      el("small", "게시 " + (source.published_at ? timeText(source.published_at) : "미확인")),
      el("small", "SHA256 " + source.content_hash.slice(0, 16) + "…"),
    );
    row.append(el("span", source.id), title, group, dates);
    return row;
  }));
}

function renderAudit(report) {
  $("audit").replaceChildren(...report.audit.toReversed().map(entry => {
    const item = el("div", undefined, "audit-item");
    item.append(
      el("span", `v${entry.version} · ${entry.reviewer} / ${entry.action}`),
      el("small", entry.note),
      el("small", timeText(entry.at)),
    );
    return item;
  }));
  if (!report.audit.length) {
    $("audit").append(el("p", "아직 검토 기록이 없습니다.", "muted"));
  }
}

async function refreshHistory() {
  const history = await api("/api/runs");
  $("history").replaceChildren(...history.map(report => {
    const button = el("button", undefined, "history-row");
    button.type = "button";
    button.append(
      el("strong", report.question),
      el("span", `${report.mode === 'demo' ? '가상 데모' : '공개 원문'} · ${statusNames[report.status]} · v${report.version}`),
      el("span", timeText(report.created_at)),
    );
    button.addEventListener("click", () => loadReport(report.id));
    return button;
  }));
  if (!history.length) {
    $("history").append(el("p", "저장된 분석이 없습니다.", "muted"));
  }
  return history;
}

/**
 * 예약된 조회를 멈추고 이전 응답을 무효화한다.
 * 타이머 취소만으로는 이미 전송된 요청을 취소할 수 없다.
 */
function stopPolling() {
  clearTimeout(state.timer);
  state.timer = null;
  state.loadRevision += 1;
  return state.loadRevision;
}

async function loadReport(id) {
  const revision = stopPolling();
  try {
    const report = await api(`/api/runs/${id}`);
    if (revision !== state.loadRevision) return;
    renderReport(report);
    if (report.status === "running") {
      message("분석 중입니다. 수집 및 추출 실패도 결과에 기록합니다.");
      state.timer = setTimeout(() => loadReport(id), 1000);
      return;
    }
    message(
      report.status === "failed"
        ? "분석을 완료하지 못했습니다. 미확정 사항을 확인하세요."
        : "원문 근거와 표현 차이를 확인한 뒤 검토해 주세요.",
      report.status === "failed",
    );
    await refreshHistory();
  } catch (error) {
    if (revision !== state.loadRevision) return;
    setBusy(false);
    message(error.message, true);
  }
}

async function startRun(event) {
  event.preventDefault();
  const languages = [...$("languages").querySelectorAll("input:checked")].map(node => node.value);
  if (state.mode === "live" && !languages.length) {
    message("검색어 언어를 하나 이상 선택하세요.", true);
    return;
  }
  const revision = stopPolling();
  setBusy(true);
  message("분석 작업을 시작합니다.");
  try {
    const report = await api("/api/runs", {
      method: "POST",
      body: JSON.stringify({
        question: $("question").value.trim(),
        mode: state.mode,
        languages: languages.length ? languages : ["ko", "zh", "ja"],
      }),
    });
    if (revision !== state.loadRevision) return;
    state.selected = null;
    await loadReport(report.id);
  } catch (error) {
    if (revision !== state.loadRevision) return;
    setBusy(false);
    message(error.message, true);
  }
}

// 검토 항목과 보고서 검토는 경로·입력이 다르고 저장 절차만 공유한다.
async function sendReview(path, method, changes) {
  if (state.reviewing || !$("review-form").reportValidity() || !state.report) return;
  const reportId = state.report.id;
  const revision = stopPolling();
  const body = {
    expected_version: state.report.version,
    reviewer: $("reviewer").value.trim(),
    note: $("review-note").value.trim(),
    ...changes,
  };
  state.reviewing = true;
  updateReviewControls();
  try {
    const report = await api(path, {method, body: JSON.stringify(body)});
    if (revision !== state.loadRevision) return;
    renderReport(report);
    await refreshHistory();
    if (revision !== state.loadRevision) return;
    message(`검토 기록을 v${report.version}에 저장했습니다.`);
  } catch (error) {
    if (revision !== state.loadRevision) return;
    if (error.status === 409) {
      await loadReport(reportId);
      // 충돌 처리 도중 사용자가 다른 보고서를 선택했다면 안내도 덮지 않는다.
      if (state.loadRevision !== revision + 1 || state.report?.id !== reportId) return;
    }
    message(error.message, true);
  } finally {
    state.reviewing = false;
    updateReviewControls();
  }
}

async function saveFindingReview() {
  if (!state.report || !state.selected) return;
  await sendReview(
    `/api/runs/${state.report.id}/findings/${state.selected}`,
    "PATCH",
    {confidence: $("confidence").value},
  );
}

async function saveReportReview(action) {
  if (!state.report) return;
  await sendReview(`/api/runs/${state.report.id}/review`, "POST", {action});
}

function bindEvents() {
  $("run-form").addEventListener("submit", startRun);
  $("save-finding").addEventListener("click", saveFindingReview);
  $("review-form").addEventListener("submit", event => {
    event.preventDefault();
    saveReportReview(event.submitter?.value || "hold");
  });
  $("demo-mode").addEventListener("click", () => setMode("demo"));
  $("live-mode").addEventListener("click", () => setMode("live"));
}

async function init() {
  bindEvents();
  $("run-button").disabled = true;
  try {
    state.config = await api("/api/config");
    setMode("demo");
    const history = await refreshHistory();
    const active = history.find(report => report.status === "running");
    const latest = active || history[0];
    if (latest) await loadReport(latest.id);
  } catch (error) {
    message("서버 연결 실패: " + error.message, true);
  }
}
init();
