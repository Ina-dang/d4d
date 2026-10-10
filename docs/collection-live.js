"use strict";

(() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g,
    char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
  const labels = {generating_queries: "LLM 검색어 생성 중", collecting: "Tavily 원문 수집 중",
    completed: "수집 완료", interrupted: "수집 중단"};

  function buildRequest(form) {
    return {question: form.elements.namedItem("question").value.trim(),
      languages: [...form.querySelectorAll('input[name="live-language"]:checked')]
        .map(input => input.value === "zh-Hans" ? "zh" : input.value),
      event_date: form.elements.namedItem("date").value || null,
      max_docs_per_country: Number(form.elements.namedItem("count").value), days_back: 30};
  }

  function safeLink(value) {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) ? escape(url.href) : "";
    } catch { return ""; }
  }

  function renderJob(job) {
    const failed = job.status === "failed";
    let html = `<p role="status"><strong>${failed ? "수집 실패" : escape(labels[job.stage] || job.stage)}</strong></p>`;
    if (job.status === "running") {
      const queryStage = job.stage === "generating_queries";
      html += loadingProgress(queryStage ? "검색어 생성 진행 상태" : "원문 수집 진행 상태",
        queryStage ? "선택한 언어별 검색어를 만들고 있습니다. 생성이 끝나면 원문 수집을 시작합니다."
          : "요청한 검색·수집 작업이 진행 중입니다.");
    }
    if (job.error) html += `<p role="alert">${escape(job.error)}</p>`;
    if (job.collection_request) {
      html += `<h3>LLM이 생성한 검색어</h3>${job.collection_request.queries.map(item =>
        `<p><strong>${escape(item.language)}</strong> · ${escape(item.query)}</p>` +
        (item.search_query && item.search_query !== item.query ?
          `<p>실제 검색: ${escape(item.search_query)}</p>` : "")).join("")}
        <details data-collection-request><summary>수집기에 전달한 실제 요청</summary><pre class="live-json">${escape(JSON.stringify(job.collection_request, null, 2))}</pre></details>`;
    }
    if (job.output) {
      html += `<h3>실제 수집 결과 · ${escape(job.output.total_count)}건</h3>`;
      const filtering = job.output.filtering;
      if (filtering) {
        const reasons = {language_not_selected: "선택하지 않은 언어", language_uncertain: "언어 판별 불확실",
          body_unavailable: "본문 확보 실패", topic_anchors_missing: "당사자·장소 불일치",
          security_topic_missing: "안보 주제 근거 없음", topic_anchors_not_connected: "주제 연결 근거 없음",
          topic_context_missing: "주제 검사 조건 없음", topic_background_only: "배경 언급만 있는 기사"};
        html += `<p>본문 판별 · 선택 언어: ${escape((filtering.selected_languages || []).join(", "))}</p>`;
        if (filtering.language_counts) html += `<p>언어별 수집 · ${Object.entries(filtering.language_counts.retained || {})
          .map(([language, count]) => `${escape(language)}: ${escape(count)}건`).join(" · ")}</p>`;
        if (filtering.body_recovery?.attempted) html += `<p>본문 재수집: ${escape(filtering.body_recovery.attempted)}건 시도 · ${escape(filtering.body_recovery.recovered)}건 확보</p>`;
        const counts = Object.entries(filtering.rejected_counts || {});
        if (counts.length) html += `<p>제외 결과 · ${counts.map(([reason, count]) =>
          `${escape(reasons[reason] || reason)}: ${escape(count)}건`).join(" · ")}</p>`;
      }
      if (!job.output.total_count) html += "<p>검색 요청은 완료됐지만 수집 조건에 맞는 문서가 없습니다.</p>";
      for (const [country, documents] of Object.entries(job.output.by_country || {})) {
        html += `<details ${documents.length ? "open" : ""}><summary>${escape(country)} · ${documents.length}건</summary>`;
        html += documents.map(doc => {
          const href = safeLink(doc.url);
          return `<article class="live-document"><h4>${href ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${escape(doc.title)}</a>` : escape(doc.title)}</h4>
            <p>${escape(doc.source_name)} · ${escape(doc.language)} · ${escape(doc.published_date || "발행일 미확인")}</p>
            <details><summary>수집 원문 미리보기</summary><p class="live-text">${escape((doc.article_text || "").slice(0, 1200))}</p></details></article>`;
        }).join("") + "</details>";
      }
      html += "<p class='demo-note'>이 단계는 원문 수집 결과입니다. 주장 비교·통계·보고서는 후속 단계에서 처리합니다.</p>";
    }
    if (job.status === "completed" && job.output?.total_count) {
      html += `<section><button type="button" class="button" data-source-analysis="${escape(job.id)}">주장·유사도 분석</button><div data-analysis-result></div></section>`;
    }
    if (job.status !== "running") html += `<p><a href="/api/collections/${encodeURIComponent(job.id)}/download">요청·원문 결과 JSON 내려받기</a></p>`;
    return html;
  }

  function requestError(data) {
    if (typeof data.detail === "string") return data.detail;
  function loadingProgress(label, detail) {
    return `<div class="live-progress"><progress max="100" aria-label="${escape(label)}"></progress>
      <p>${escape(detail)}</p><small>처리 결과를 기다리고 있습니다.</small></div>`;
  }

    if (Array.isArray(data.detail)) {
      const fields = {question: "질문", languages: "검색 언어", event_date: "사건 날짜",
        max_docs_per_country: "국가당 최대 문서 수", days_back: "검색 기간",
        min_score: "최소 검색 관련도", strict_min_score: "검색 관련도 필터"};
      const messages = data.detail.filter(error => error && typeof error === "object").map(error => {
        const field = Array.isArray(error.loc) ? error.loc.find(part => part in fields) : null;
        let reason = typeof error.msg === "string" ? error.msg : "입력값을 확인하세요.";
        if (error.type === "less_than_equal" && error.ctx?.le !== undefined) {
          reason = `${error.ctx.le} 이하로 입력하세요.`;
        } else if (error.type === "greater_than_equal" && error.ctx?.ge !== undefined) {
          reason = `${error.ctx.ge} 이상으로 입력하세요.`;
        } else if (error.type === "string_too_short" && error.ctx?.min_length !== undefined) {
          reason = `${error.ctx.min_length}자 이상 입력하세요.`;
        } else if (error.type === "string_too_long" && error.ctx?.max_length !== undefined) {
          reason = `${error.ctx.max_length}자 이하로 입력하세요.`;
        }
        return `${fields[field] || "입력값"}: ${reason}`;
      });
      if (messages.length) return messages.join("\n");
    }
    return "입력 또는 연결 상태를 확인하세요.";
  }

  function mount(root) {
    if (!root || root.dataset.bound) return;
    root.dataset.bound = "true";
    const form = root.querySelector("form");
    const button = form.querySelector('button[type="submit"]');
    const result = root.querySelector("[data-live-result]");
    const config = root.querySelector("[data-live-config]");
    let running = false;
    async function request(url, options) {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!response.ok) throw new Error(requestError(data));
      return data;
    }
    async function poll(id) {
      running = true;
      button.disabled = true;
      try {
        while (root.isConnected) {
          const job = await request("/api/collections/" + encodeURIComponent(id));
          const requestOpen = result.querySelector("[data-collection-request]")?.open;
          result.innerHTML = renderJob(job);
          const requestDetails = result.querySelector("[data-collection-request]");
          if (requestDetails && requestOpen !== undefined) requestDetails.open = requestOpen;
          if (job.status !== "running") break;
          await new Promise(resolve => setTimeout(resolve, 1500));
        }
      } catch (error) { result.textContent = error.message; }
      finally { running = false; button.disabled = false; }
    }
    request("/api/config").then(data => {
      config.textContent = `${data.ollama_model} · CPU 로컬 검색어 생성 / Tavily ${data.collection_ready ? "키 설정됨" : "키 설정 필요"}`;
    }).catch(() => { config.textContent = "실제 수집은 기본 FastAPI 실행 주소에서 이용하세요."; });
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (running) return;
      const body = buildRequest(form);
      if (!body.languages.length) { result.textContent = "검색 언어를 하나 이상 선택하세요."; return; }
      running = true;
      button.disabled = true;
      result.textContent = "실제 검색·수집 요청을 시작합니다.";
      try {
        const job = await request("/api/collections", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
        try { sessionStorage.setItem("gyeopnun-collection", job.id); } catch { /* 저장 불가 환경에서도 수집한다. */ }
        await poll(job.id);
      } catch (error) { result.textContent = error.message; }
      finally { running = false; button.disabled = false; }
    });
    try { const last = sessionStorage.getItem("gyeopnun-collection"); if (last) poll(last); } catch { /* 선택적 화면 복원 */ }
  }
  const api = {buildRequest, renderJob, mount};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else window.CollectionLive = api;
})();
      result.innerHTML = loadingProgress("검색·수집 준비 상태", "실제 검색·수집 요청을 시작합니다.");
