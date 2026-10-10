"use strict";

document.addEventListener("click", async event => {
  const button = event.target.closest("[data-source-analysis]");
  if (!button || button.disabled) return;
  const result = button.parentElement.querySelector("[data-analysis-result]");
  const rid = button.dataset.sourceAnalysis;
  button.disabled = true;
  result.replaceChildren();
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  const card = document.createElement("div");
  card.className = "live-progress";
  const steps = document.createElement("ol");
  steps.className = "live-progress-steps";
  const stepNodes = ["주장 추출·번역", "유사도 계산", "결과 저장"].map(label => {
    const node = document.createElement("li");
    node.textContent = label;
    steps.append(node);
    return node;
  });
  const bar = document.createElement("progress");
  bar.max = 100;
  bar.setAttribute("aria-label", "원문 분석 진행률");
  const detail = document.createElement("p");
  const timing = document.createElement("small");
  const started = Date.now();
  let live = true, polling = false, receivedChars = 0;
  const controller = new AbortController();
  function elapsed() {
    const seconds = Math.floor((Date.now() - started) / 1000);
    timing.textContent = `경과 ${Math.floor(seconds / 60)}분 ${seconds % 60}초 · 현재 단계 완료 기준` +
      (receivedChars ? ` · LLM 응답 ${receivedChars}자 수신 중` : "");
  }
  function update(data) {
    const labels = {preparing: "분석 준비 중", extracting: "주장 추출·번역 중",
      comparing: data.similarity_target === "user_question" ? "질문 관련도 계산 중" : "문서 간 유사도 비교 중", saving: "결과 저장 중"};
    status.textContent = labels[data.stage] || "분석 중";
    detail.textContent = data.detail || "분석 모델과 원문을 준비합니다.";
    receivedChars = data.received_chars || 0;
    const percent = Number.isFinite(data.stage_percent) ? data.stage_percent : data.percent;
    if (Number.isFinite(percent)) {
      bar.value = percent;
      status.textContent += ` · ${percent}% (${data.stage_completed ?? data.completed}/${data.stage_total ?? data.total})`;
    } else bar.removeAttribute("value");
    elapsed();
    const current = {preparing: 0, extracting: 0, comparing: 1, saving: 2}[data.stage] ?? 0;
    stepNodes.forEach((node, index) => {
      node.className = index < current ? "done" : index === current ? "active" : "";
    });
  }
  update({stage: "preparing"});
  elapsed();
  card.append(status, steps, bar, detail, timing);
  result.append(card);
  const timer = setInterval(async () => {
    if (result.isConnected === false) {
      live = false;
      clearInterval(timer);
      controller.abort();
      return;
    }
    elapsed();
    if (polling || !live) return;
    polling = true;
    try {
      const response = await fetch(`/api/collections/${encodeURIComponent(rid)}/analysis/status`,
        {signal: controller.signal});
      if (response.ok) {
        const data = await response.json();
        if (live && data.status === "running") update(data);
      }
    } catch (_) { /* 분석 POST는 계속 대기하고 다음 조회에서 재시도한다. */ }
    finally { polling = false; }
  }, 1000);
  try {
    const response = await fetch(`/api/collections/${encodeURIComponent(rid)}/analysis`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "원문 분석에 실패했습니다.");
    status.textContent = `문서 ${data.docs.length}개 · 주장 ${data.claims.length}개 분석 완료`;
    if (data.verification_selection) {
      status.textContent += ` · 검증 전달 대표 주장 ${data.verification_selection.exported_claim_count}개`;
    }
    bar.value = 100;
    stepNodes.forEach(node => { node.className = "done"; });
    detail.textContent = "결과를 확인하고 JSON으로 내려받을 수 있습니다.";
    if (Array.isArray(data.warnings) && data.warnings.length) {
      const warningBox = document.createElement("section");
      const heading = document.createElement("p");
      heading.textContent = `확인할 분석 경고 ${data.warnings.length}건`;
      const list = document.createElement("ul");
      data.warnings.forEach(message => {
        const item = document.createElement("li");
        item.textContent = message;
        list.append(item);
      });
      warningBox.append(heading, list);
      result.append(warningBox);
    }
    const note = document.createElement("p");
    note.textContent = data.similarity_target === "user_question"
      ? "sim은 사용자 질문과 각 snippet의 임베딩 관련도입니다. snippet에서 주장이 없으면 원문에서 보완한 근거 문장을 사용합니다. 문서마다 숫자 하나이며 최종 신뢰도·사실 일치율이 아닙니다."
      : data.analysis_scope?.startsWith("text_snippet")
      ? "snippet 범위의 주장을 분석하고 필요한 문서는 원문 근거로 보완했습니다. sim은 다른 문서 ID별 분석 근거의 유사도 딕셔너리이며 최종 신뢰도·사실 일치율이 아닙니다. 질문 관련도는 상세 기록의 question_relevance에 있습니다."
      : "score는 Tavily 검색 관련도, sim은 추출 주장 기준 문서 간 의미 유사도입니다. 최종 신뢰도·사실 일치율이 아닙니다.";
    const preview = document.createElement("pre");
    preview.className = "live-json";
    preview.textContent = JSON.stringify(data, null, 2);
    const link = document.createElement("a");
    link.href = `/api/collections/${encodeURIComponent(rid)}/analysis/download?format=verification`;
    link.textContent = "신뢰도 함수 입력 JSON 내려받기";
    result.append(note, link, preview);
    if (typeof attachReliabilityReport === "function") attachReliabilityReport(result, rid);
    if (data.timings) {
      const measured = document.createElement("p");
      const labels = {extraction: "추출", meaning_check: "의미 검증", embedding: "임베딩",
        reextraction: "재추출", similarity: "유사도"};
      const phases = Object.entries(data.timings.phases || {}).map(([key, phase]) =>
        `${labels[key] || key} ${phase.seconds}초`).join(" · ");
      measured.textContent = `실측 시간 · ${phases} · LLM ${data.timings.llm_calls}회 / 임베딩 ${data.timings.embedding_calls || 0}회 / 캐시 ${data.timings.cache_hits}회`;
      card.append(measured);
    }
  } catch (error) {
    status.textContent = error.message || "원문 분석에 실패했습니다.";
    status.setAttribute("role", "alert");
    card.className += " failed";
    if (!Number.isFinite(bar.value)) bar.value = 0;
    // 준비 단계 실패도 움직이는 막대를 멈추고 다시 실행할 수 있게 한다.
    bar.value = Math.min(bar.value, 99);
    detail.textContent = "분석을 다시 실행할 수 있습니다.";
  } finally {
    live = false;
    receivedChars = 0;
    clearInterval(timer);
    controller.abort();
    elapsed();
    button.disabled = false;
  }
});
