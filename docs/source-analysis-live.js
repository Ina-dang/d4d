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
  status.textContent = "주장·번역과 문서 간 유사도 분석 중… 문서 수에 따라 시간이 걸립니다.";
  result.append(status);
  try {
    const response = await fetch(`/api/collections/${encodeURIComponent(rid)}/analysis`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "원문 분석에 실패했습니다.");
    status.textContent = `문서 ${data.docs.length}개 · 주장 ${data.claims.length}개 분석 완료`;
    const note = document.createElement("p");
    note.textContent = "score는 Tavily 검색 관련도, sim은 추출 주장 기준 문서 간 의미 유사도입니다. 최종 신뢰도·사실 일치율이 아닙니다.";
    const preview = document.createElement("pre");
    preview.className = "live-json";
    preview.textContent = JSON.stringify(data, null, 2);
    const link = document.createElement("a");
    link.href = `/api/collections/${encodeURIComponent(rid)}/analysis/download`;
    link.textContent = "주장·유사도 JSON 내려받기";
    result.append(note, link, preview);
  } catch (error) {
    status.textContent = error.message || "원문 분석에 실패했습니다.";
    status.setAttribute("role", "alert");
  } finally {
    button.disabled = false;
  }
});
