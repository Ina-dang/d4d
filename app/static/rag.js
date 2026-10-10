"use strict";
const $ = (id) => document.getElementById(id);
let lastResult = null;
let busy = false;
const splitValues = (value) => value.split(",").map((s) => s.trim()).filter(Boolean);

async function api(path, method = "GET", body) {
  const response = await fetch(path, {method, headers: {"Content-Type": "application/json"},
    body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "입력 형식을 확인하세요.");
  return data;
}
async function action(work) {
  if (busy) return;
  busy = true;
  document.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  $("message").textContent = "처리 중…";
  try { await work(); } catch (error) { $("message").textContent = error.message; }
  finally {
    busy = false;
    document.querySelectorAll("button").forEach((button) => { button.disabled = false; });
    $("download").disabled = !lastResult;
  }
}
async function refreshEvents(selected = $("events").value) {
  const events = await api("/api/rag/events");
  $("events").replaceChildren();
  if (!events.length) $("events").append(new Option("사건을 등록하세요", ""));
  for (const event of events) $("events").append(new Option(
    `${event.is_demo ? "[가상] " : ""}${event.label} · ${event.document_count}문서`, event.event_id));
  if (events.some((event) => event.event_id === selected)) $("events").value = selected;
}
function eventPath() {
  if (!$("events").value) throw new Error("사건을 먼저 등록하거나 선택하세요.");
  return "/api/rag/events/" + encodeURIComponent($("events").value);
}
async function importPayload(payload) {
  const path = eventPath();
  const result = await api(path + "/import", "POST", payload);
  if (result.query_variants.length) $("queries").value = result.query_variants.join("\n");
  await refreshEvents();
  $("message").textContent = `${result.ingested_documents}문서 · ${result.indexed_chunks}청크 저장 완료`;
}
function addText(parent, tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  parent.append(element);
  return element;
}
function render(result) {
  lastResult = result;
  $("results").replaceChildren();
  $("warnings").replaceChildren();
  const statuses = {evidence_found: "원문 근거 발견", empty_event: "저장된 자료 없음",
    no_eligible_documents: "조건에 맞는 자료 없음", no_match: "문자열이 일치하는 근거 없음"};
  $("summary").textContent = `${statuses[result.status]} · 전체 ${result.total_documents}문서 / 검색 대상 ${result.eligible_documents}문서 / 결과 ${result.evidence.length}개 / 중복 억제 ${result.duplicates_suppressed}문서`;
  for (const hit of result.evidence) {
    const card = document.createElement("article");
    addText(card, "h3", `${hit.is_demo ? "[가상] " : ""}${hit.title}`);
    if (hit.url) {
      const link = addText(card, "a", "원문 출처 열기");
      link.href = hit.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    }
    addText(card, "p", `${hit.source_country} · ${hit.language} · 게시일 ${hit.published_date || "미확인"} · 사건일 ${hit.event_date || "미확인"} · 본문 ${hit.content_kind}`, "meta");
    addText(card, "blockquote", hit.quote);
    addText(card, "p", `문서 ${hit.doc_id} / 문단 ${hit.paragraph_id || "미확인"} / 청크 ${hit.chunk_id} / 문자 ${hit.start_char}–${hit.end_char}`, "meta");
    addText(card, "p", `검색 점수 ${hit.retrieval_score} · Tavily ${hit.tavily_score ?? "없음"} · 출처 등급 ${hit.source_tier ?? "미정"} · 정책 가중치 ${hit.credibility_weight ?? "미정"} · LLM 관련도 ${hit.llm_relevance ?? "미평가"}`, "meta");
    $("results").append(card);
  }
  for (const warning of result.warnings) addText($("warnings"), "li", warning);
  $("download").disabled = false;
}
$("event-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const id = $("event-id").value.trim();
    await api("/api/rag/events/" + encodeURIComponent(id), "PUT", {label: $("event-label").value,
      description: $("event-description").value});
    await refreshEvents(id);
    $("message").textContent = "사건을 등록했습니다. 이 사건의 수집 JSON을 넣으세요.";
  });
});
$("import").addEventListener("click", () => action(async () => {
  const file = $("upload").files[0];
  if (!file) throw new Error("수집 JSON 파일을 선택하세요.");
  if (file.size > 20000000) throw new Error("파일은 20MB 이하로 나누어 넣으세요.");
  await importPayload(JSON.parse(await file.text()));
}));
$("collection-import").addEventListener("click", () => action(async () => {
  const id = $("collection-id").value.trim();
  if (!/^[a-f0-9]{32}$/.test(id)) throw new Error("수집 화면에서 받은 작업 ID를 입력하세요.");
  await importPayload(await api("/api/collections/" + id));
}));
$("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    eventPath();
    const result = await api("/api/rag/search", "POST", {event_id: $("events").value,
      question: $("question").value,
      query_variants: $("queries").value.split("\n").map((q) => q.trim()).filter(Boolean),
      countries: splitValues($("countries").value), languages: splitValues($("languages").value),
      published_start: $("published-start").value || null, published_end: $("published-end").value || null,
      include_demo: $("include-demo").checked, include_snippets: $("include-snippets").checked});
    render(result); $("message").textContent = "검색을 마쳤습니다.";
  });
});
$("demo").addEventListener("click", () => action(async () => {
  const fixture = await api("/static/rag-demo.json");
  await api("/api/rag/events/demo-strait", "PUT", fixture.event);
  await refreshEvents("demo-strait");
  await importPayload({documents: fixture.documents});
  $("question").value = "가상 대만해협 자료에서 항공기 수가 확인됐는가?";
  $("queries").value = "Taiwan Strait aircraft number\n대만해협 항공기 수\n台湾海峡 飞机 数量";
  $("include-demo").checked = true;
  $("countries").value = ""; $("languages").value = "";
  $("published-start").value = ""; $("published-end").value = "";
  render(await api("/api/rag/search", "POST", {event_id: "demo-strait", question: $("question").value,
    query_variants: $("queries").value.split("\n"), include_demo: true}));
  $("message").textContent = "가상 자료 시연입니다. 실제 사건의 근거가 아닙니다.";
}));
$("download").addEventListener("click", () => {
  if (!lastResult) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(lastResult, null, 2)], {type: "application/json"}));
  const link = document.createElement("a"); link.href = url; link.download = "rag-evidence.json";
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$("events").addEventListener("change", () => {
  lastResult = null; $("download").disabled = true;
  $("results").replaceChildren(); $("warnings").replaceChildren();
  $("summary").textContent = "선택한 사건에서 다시 검색하세요.";
});
action(async () => { await refreshEvents(); $("message").textContent = ""; });
