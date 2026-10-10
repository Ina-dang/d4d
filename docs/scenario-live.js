"use strict";

// 실행은 서버가 소유한다. 페이지 전환·새로고침은 이 조회기만 교체한다.
(() => {
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const files = {queries: "검색어 JSON", analysis: "주장·번역 JSON",
    verification: "유사도·검증 입력 JSON", reliability: "신뢰도 결과 JSON"};
  const busy = job => ["running", "cancelling"].includes(job?.status);
  const duration = seconds => seconds < 60 ? `${Math.max(1, Math.ceil(seconds))}초` : `${Math.ceil(seconds / 60)}분`;
  const elapsedText = seconds => seconds < 60 ? `${Math.max(0, Math.floor(seconds))}초`
    : `${Math.floor(seconds / 60)}분 ${Math.floor(seconds % 60)}초`;
  const memory = {id: null, job: null, timer: null, epoch: 0, requestPending: false, startPending: false,
    screen: "scope", root: null, collection: null, rendered: "", onSelect: null, formDraft: null, networkError: "", downloadFormat: "pdf"};
  const key = "gyeopnun-scenario";
  const store = (name, value) => { try { localStorage.setItem(name, value); } catch { /* URL 복원 유지 */ } };
  const stored = name => { try { return localStorage.getItem(name); } catch { return null; } };

  async function request(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) {
      const detail = typeof data.detail === "string" ? data.detail
        : Array.isArray(data.detail) ? data.detail.map(e => e.msg).join(" · ") : "연결 상태를 확인하세요.";
      const error = new Error(detail); error.status = response.status; throw error;
    }
    return data;
  }

  function progressHtml(job, screen = "scope") {
    if (!job && screen === "scope") return "";
    if (!job) return `<div class="workflow-empty"><h2>${screen === "report" ? "보고서를 준비할 질문이 필요합니다." : "분석할 질문을 입력해 주세요."}</h2>
      <p>질문을 실행하면 검색부터 보고서까지 자동으로 이어집니다.</p><a class="button" href="?screen=scope">질문 입력으로 이동</a></div>`;
    const running = busy(job), completed = job.status === "completed" && Boolean(job.artifacts?.report_json);
    const current = job.steps?.find(step => step.id === job.stage);
    const heading = completed ? "보고서 초안이 준비되었습니다." : job.status === "completed" ? "보고서 결과를 확인하고 있습니다."
      : job.status === "cancelling" ? "작업을 중단하고 있습니다."
      : running ? `${current?.label || "작업 준비"} 중` : "작업이 중단되었습니다.";
    const remaining = job.estimated_remaining_seconds;
    const estimate = running ? Number.isFinite(remaining)
      ? `예상 남은 시간 약 ${duration(remaining)} · 이전 ${job.estimate_samples}회 실측 기준`
      : job.estimate ? "이전 실측보다 오래 걸리고 있습니다. 완료된 단계는 저장되어 있습니다."
      : "남은 시간 계산 중 · 첫 실행은 PC와 수집량에 따라 달라집니다." : "";
    const hint = screen === "report" ? "검색·수집 → 주장·유사도 분석 → 신뢰도 계산을 마치면 보고서가 표시됩니다."
      : screen === "analysis" ? "원문 수집 후 문서가 먼저 표시되고, 주장·유사도와 신뢰도가 차례로 추가됩니다."
      : "다른 메뉴나 브라우저 탭을 확인해도 계속 진행됩니다. 이 PC의 서버는 켜 두세요.";
    return `<section class="workflow-progress" aria-label="전체 처리 진행 상태" aria-busy="${running}">
      <div class="workflow-status"><h2>${running ? '<span class="activity-dot" aria-hidden="true"></span>' : ""}${esc(heading)}</h2>
        <span>${completed ? "6 / 6단계 완료" : `${(job.steps || []).filter(s => s.status === "completed").length} / 6단계 완료`}</span></div>
      <ol class="workflow-steps">${(job.steps || []).map((s, i) => `<li class="${esc(s.status)}" ${s.status === "running" ? 'aria-current="step"' : ""}>
        <span>${s.status === "completed" ? "✓" : i + 1}</span>${esc(s.label)}</li>`).join("")}</ol>
      <progress max="100" value="${Number(job.percent) || 0}" aria-label="전체 단계 진행률"></progress>
      <div class="workflow-timing"><span>경과 ${elapsedText(job.elapsed_seconds || 0)}${estimate ? ` · ${esc(estimate)}` : ""}</span>
        ${running ? '<button class="text-link" type="button" data-scenario-stop>작업 중단</button>' : ["failed", "cancelled", "interrupted"].includes(job.status)
          ? '<button class="button" type="button" data-scenario-resume>완료한 단계부터 다시 실행</button>' : ""}</div>
      <p class="workflow-detail">${esc(running ? String(job.progress?.detail || "완료되는 순서대로 결과를 저장합니다.").replace(/text_snippet|snippet/g, '발췌 본문').replace(/doc_[a-z0-9]+: /g, '') : completed
        ? `문서 ${job.counts?.articles ?? "—"}개 · 대표 주장 ${job.counts?.claims ?? "—"}개. 보고서를 확인한 뒤 저장하세요.` : job.error)}</p>
      ${running ? `<p class="small muted">${esc(hint)}</p>` : completed && screen !== "report"
        ? `<a class="button" href="?screen=report&run=${encodeURIComponent(job.id)}">보고서 확인 →</a>` : ""}</section>`;
  }

  function reportDownloadHtml(rid, ready = true, prefix = "main") {
    const endpoint = `/api/collections/${encodeURIComponent(rid)}/analysis/report/download`;
    return `<div class="report-export" data-report-export data-report-endpoint="${esc(endpoint)}">
      <label for="${prefix}-report-format">보고서</label>
      <select id="${prefix}-report-format" aria-label="보고서 저장 형식" data-report-format ${ready ? "" : "disabled"}>
        ${["pdf", "md", "json"].map(format => `<option value="${format}" ${format === memory.downloadFormat ? "selected" : ""}>${format.toUpperCase()}</option>`).join("")}</select>
      ${ready ? `<a class="button" href="${endpoint}?format=${memory.downloadFormat}" download data-report-download>보고서 다운로드 ↓</a>`
        : '<span class="button artifact-pending" aria-disabled="true">보고서 준비 중</span>'}</div>`;
  }

  function artifactsHtml(job) {
    return `<section class="artifact-downloads" aria-label="단계별 결과 저장"><div class="artifact-primary">
      ${reportDownloadHtml(job?.id, Boolean(job?.artifacts?.report_json))}
      ${job?.artifacts?.collection ? `<a class="button original-download" href="${esc(job.artifacts.collection)}" download>수집 원문(JSON) 저장 ↓</a>`
        : '<span class="button artifact-pending" aria-disabled="true">수집 원문(JSON) 준비 중</span>'}</div>
      <details class="intermediate-downloads"><summary>중간 결과 JSON 저장</summary><div>${Object.entries(files).map(([id, label]) =>
      job?.artifacts?.[id] ? `<a class="artifact-link" href="${esc(job.artifacts[id])}" download>${label} ↓</a>`
        : `<span class="artifact-pending" aria-disabled="true">${label}</span>`).join("")}</div></details></section>`;
  }

  function shellHtml(screen) {
    return `<header class="scenario-page-head"><p class="small muted">${screen === "report" ? "보고서 · 확인 및 저장" : "Fusion 분석"}</p>
      <h1 data-scenario-question>질문부터 근거까지, 한 흐름으로</h1></header>
      <div data-scenario-status></div><div data-scenario-downloads></div>
      <p class="scenario-connection" data-scenario-connection role="status"></p><div data-scenario-content></div>`;
  }

  function updateNavigation() {
    const job = memory.job;
    document.querySelectorAll(".screen-nav a").forEach(link => {
      let marker = link.querySelector(".nav-progress");
      if (!marker) { marker = document.createElement("span"); marker.className = "nav-progress"; link.append(marker); }
      const screen = new URL(link.href).searchParams.get("screen");
      const available = screen === "scope" ? job?.artifacts?.collection : screen === "analysis" ? job?.artifacts?.verification : job?.artifacts?.report_json;
      marker.classList.toggle("is-loading", busy(job) && !available);
      marker.textContent = available ? "✓" : busy(job) ? "" : "";
      marker.setAttribute("aria-label", available ? "준비됨" : busy(job) ? "처리 중" : "");
    });
  }

  function update() {
    const root = memory.root;
    if (!root?.isConnected) return;
    const job = memory.job;
    const status = root.querySelector("[data-scenario-status]");
    const downloads = root.querySelector("[data-scenario-downloads]");
    // 폼과 보고서의 검토 선택은 상태 조회로 다시 그리지 않는다.
    if (status) {
      const focusedAction = document.activeElement?.hasAttribute('data-scenario-stop') ? '[data-scenario-stop]'
        : document.activeElement?.hasAttribute('data-scenario-resume') ? '[data-scenario-resume]' : null;
      status.innerHTML = progressHtml(job, memory.screen);
      if (focusedAction) status.querySelector(focusedAction)?.focus();
    }
    if (downloads) {
      const html = job ? artifactsHtml(job) : "";
      const signature = JSON.stringify([job?.id, job?.artifacts, memory.downloadFormat]);
      if (downloads.dataset.signature !== signature) {
        const open = downloads.querySelector('details')?.open;
        downloads.innerHTML = html;
        if (open) downloads.querySelector('details').open = true;
        downloads.dataset.signature = signature;
      }
    }
    const connection = root.querySelector("[data-scenario-connection]");
    if (connection) connection.textContent = memory.networkError;
    const title = root.querySelector("[data-scenario-question]");
    if (title && job) title.textContent = job.input.question;
    const submit = root.querySelector('[type="submit"]');
    if (memory.screen === "scope" && submit) {
      submit.disabled = busy(job) || memory.startPending;
      submit.textContent = busy(job) ? "보고서 생성 중…" : "보고서 생성";
      const note = root.querySelector("[data-live-message]");
      if (note && job) note.textContent = busy(job) ? "작업 중에도 Fusion 분석과 보고서 페이지로 이동할 수 있습니다." : "";
    }
    updateNavigation();
    updateContent().catch(error => {
      if (root === memory.root && connection) connection.textContent = `결과를 불러오지 못했습니다: ${error.message}`;
    });
  }

  async function updateContent() {
    const {root, job, screen, id, epoch} = memory;
    const content = root?.querySelector("[data-scenario-content]");
    if (!content) return;
    if (!job) { content.innerHTML = ""; return; }
    const signature = `${id}:${screen}:${Object.keys(job.artifacts || {}).join(",")}`;
    if (memory.rendered === signature) return;
    memory.rendered = signature;
    const stillHere = () => memory.epoch === epoch && memory.root === root && root.isConnected;
    try {
      if (screen === "report") {
        if (job.artifacts.report_json) {
          const report = await request(`/api/collections/${encodeURIComponent(id)}/analysis/report`);
          if (stillHere()) window.ScenarioReport.mount(content, id, report);
        } else {
          content.innerHTML = `<div class="workflow-wait"><h2>보고서가 이곳에 표시됩니다.</h2><p>핵심 판단 · 공통 사실 주장 · 상충 후보 · 출처별 해석 · 분석의 한계</p>
            <p class="small muted">앞 단계가 끝나면 자동으로 작성합니다. 이 페이지에서 기다리거나 다른 메뉴를 둘러보세요.</p></div>`;
        }
      } else if (screen === "analysis") {
        if (job.artifacts.collection) {
          content.innerHTML = FusionScreen.html();
          await FusionScreen.mount({run: id, id: "", label: "수집 결과", question: job.input.question});
        } else content.innerHTML = '<div class="workflow-wait"><h2>원문을 수집한 뒤 분석이 시작됩니다.</h2><p>수집된 문서와 출처, 대표 주장과 문서 간 유사도를 순서대로 확인할 수 있습니다.</p></div>';
      } else if (job.artifacts.queries || job.artifacts.collection) {
        const collection = await request(`/api/collections/${encodeURIComponent(id)}`);
        if (!stillHere()) return;
        memory.collection = collection;
        const queries = collection.collection_request?.queries || [];
        const docs = Object.values(collection.output?.by_country || {}).flat();
        content.innerHTML = `<details class="collected-queries"><summary>생성된 검색어 · ${queries.length}개 언어</summary>
          ${queries.map(q => `<p><strong>${esc(q.language)}</strong> ${esc(q.search_query || q.query)}</p>`).join("")}</details>
          ${collection.output ? `<div class="collection-result-head"><h2>수집한 원문 ${docs.length}개</h2><a class="text-link" href="?screen=analysis&run=${encodeURIComponent(id)}">Fusion 분석에서 보기 →</a></div>
          <div class="collected-documents">${docs.map(d => `<article><p class="small muted">${esc(d.country)} · ${esc(d.source_name)} · ${esc(d.language)}</p>
            <h3>${esc(d.title)}</h3><details><summary>본문 미리보기</summary><p>${esc((d.text_snippet || d.article_text || "").slice(0, 1200))}</p></details></article>`).join("")}</div>` : ""}`;
      } else content.innerHTML = "";
    } catch (error) { if (stillHere()) memory.rendered = ""; throw error; }
  }

  function select(job) {
    if (memory.id !== job.id) { memory.epoch++; memory.rendered = ""; }
    memory.id = job.id; memory.job = job; memory.networkError = "";
    store(key, job.id);
    const form = memory.root?.querySelector('#live-collection form');
    if (form && !memory.formDraft) {
      form.elements.namedItem('question').value = job.input.question;
      form.elements.namedItem('count').value = job.input.max_docs_per_country;
      form.elements.namedItem('date').value = job.input.event_date || '';
      form.querySelectorAll('[name="live-language"]').forEach(input => {
        input.checked = job.input.languages.includes(input.value === 'zh-Hans' ? 'zh' : input.value);
      });
    }
    memory.onSelect?.(job.id, job.input);
    update();
  }

  async function refresh() {
    if (memory.requestPending) return;
    memory.requestPending = true;
    const epoch = memory.epoch, id = memory.id;
    try {
      const job = id ? await request(`/api/scenarios/${encodeURIComponent(id)}`) : await request('/api/scenarios/active');
      if (epoch !== memory.epoch) return;
      if (job) select(job);
      else update();
    } catch (error) {
      if (epoch !== memory.epoch) return;
      memory.networkError = error.status === 404 ? "이 작업의 진행 기록이 없습니다. 검색 화면에서 새 보고서를 생성할 수 있습니다."
        : "서버 연결을 다시 확인하고 있습니다. 연결이 복구되면 진행 상태를 이어서 표시합니다.";
      update();
    } finally {
      memory.requestPending = false;
      clearTimeout(memory.timer);
      if (busy(memory.job) || memory.networkError || !memory.id) memory.timer = setTimeout(refresh, 1800);
    }
  }

  function mount(root, screen, {id = null, onSelect} = {}) {
    memory.root = root; memory.screen = screen; memory.onSelect = onSelect; memory.rendered = "";
    // run 없는 질문 화면은 새 입력이다. 마지막 완료 실행을 현재 질문에 붙이지 않는다.
    if (!id && screen === "scope") {
      if (memory.id) memory.formDraft = null;
      memory.id = null; memory.job = null; memory.networkError = ""; memory.epoch++;
      store(key, "");
    }
    if (id && id !== memory.id) { memory.id = id; memory.job = null; memory.epoch++; }
    if (!memory.id && screen !== "scope") memory.id = stored(key);
    if (!root.dataset.scenarioBound) {
      root.dataset.scenarioBound = "true";
      root.addEventListener("change", event => {
        if (!event.target.matches('[data-report-format]')) return;
        const format = event.target.value;
        if (!["pdf", "md", "json"].includes(format)) return;
        memory.downloadFormat = format;
        root.querySelectorAll('[data-report-export]').forEach(control => {
          control.querySelector('select').value = format;
          const link = control.querySelector('[data-report-download]');
          if (link) link.href = `${control.dataset.reportEndpoint}?format=${format}`;
        });
      });
      root.addEventListener("click", async event => {
      const button = event.target.closest("[data-scenario-stop], [data-scenario-resume]");
      if (!button || !memory.id || button.disabled) return;
      button.disabled = true;
      try {
        const action = button.hasAttribute("data-scenario-stop") ? "cancel" : "resume";
        select(await request(`/api/scenarios/${encodeURIComponent(memory.id)}/${action}`, {method: "POST"}));
        refresh();
      } catch (error) { memory.networkError = error.message; update(); }
      });
    }
    if (screen === "scope") bindForm(root);
    update(); refresh();
  }

  function bindForm(root) {
    const form = root.querySelector("#live-collection form");
    if (!form) return;
    const config = root.querySelector("[data-live-config]");
    const draft = memory.formDraft || memory.job?.input;
    if (draft) {
      form.elements.namedItem("question").value = draft.question || "";
      form.elements.namedItem("date").value = draft.event_date || "";
      form.elements.namedItem("count").value = draft.max_docs_per_country || 20;
      form.querySelectorAll('[name="live-language"]').forEach(input => {
        input.checked = draft.languages?.includes(input.value === "zh-Hans" ? "zh" : input.value);
      });
    }
    form.addEventListener("input", () => {
      memory.formDraft = window.CollectionLive.buildRequest(form);
      if (memory.job && !busy(memory.job)) {
        memory.id = null; memory.job = null; memory.collection = null; memory.rendered = ""; memory.epoch++;
        store(key, "");
        memory.onSelect?.(null, memory.formDraft);
        update();
      }
    });
    request('/api/config').then(value => {
      if (root.isConnected) config.textContent = value.scenario_ready ? "검색부터 보고서 작성까지 자동으로 진행합니다." : "실행에 필요한 서버 설정을 확인해 주세요.";
    }).catch(() => { if (root.isConnected) config.textContent = "서버 연결을 확인해 주세요."; });
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (busy(memory.job) || memory.startPending) return;
      const body = window.CollectionLive.buildRequest(form);
      const message = root.querySelector('[data-live-message]');
      if (!body.languages.length) { message.textContent = "검색 언어를 하나 이상 선택해 주세요."; return; }
      memory.formDraft = body; memory.startPending = true; memory.epoch++;
      memory.id = null; memory.job = null; memory.rendered = "";
      update(); message.textContent = "작업을 시작합니다…";
      try {
        const job = await request('/api/scenarios', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
        memory.rendered = ""; select(job); refresh();
      } catch (error) { message.textContent = error.message; }
      finally { memory.startPending = false; const button = form.querySelector('[type="submit"]'); if (button) button.disabled = busy(memory.job); }
    });
  }

  const api = {mount, shellHtml, progressHtml, artifactsHtml, reportDownloadHtml};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else {
    window.ScenarioLive = api;
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  }
})();
