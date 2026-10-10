const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");

function harness() {
  const nodes = [], requests = [];
  const report = {status: "draft", version: 1,
    sections: {key_judgment: [{text: "<script>悪意</script>", claim_ids: ["a-c1"]}],
      common_facts: [], conflicting_candidates: [], source_interpretations: [],
      analysis_limits: [{text: "사람 검토 필요", claim_ids: []}]},
    evidence: [{claim_id: "a-c1", document_id: "a", source_name: "자료 A", reliability: 0.6,
      label: "관점 차이", translated_quote: "번역", original_quote: "原文", url: "javascript:alert(1)"}],
    warnings: ["같은 실행의 입력과 대조됨"]};
  const state = {report, fail: false};
  function element(tag) {
    const node = {tag, children: [], attrs: {}, handlers: {}, textContent: "",
      append(...items) { this.children.push(...items); },
      replaceChildren(...items) { this.children = items; },
      setAttribute(k, v) { this.attrs[k] = v; },
      addEventListener(k, fn) { this.handlers[k] = fn; }};
    nodes.push(node);
    return node;
  }
  const parent = element("div");
  const context = vm.createContext({JSON, encodeURIComponent,
    document: {createElement: element},
    fetch: async (url, options) => {
      requests.push({url, body: options?.body ? JSON.parse(options.body) : null});
      if (url.endsWith("report-input")) return {ok: true, json: async () => ({
        verification_input_sha256: "a".repeat(64), local_function_configured: true})};
      return {ok: !state.fail, json: async () => state.fail ? {detail: "현재 입력에 없는 주장 ID"} : state.report};
    }});
  vm.runInContext(readFileSync(join(__dirname, "../docs/reliability-report-live.js"), "utf8"), context);
  context.attachReliabilityReport(parent, "abc");
  const button = text => nodes.find(n => n.tag === "button" && n.textContent.includes(text));
  return {nodes, requests, button, state};
}

test("로컬 함수 호출 → 초안·원문·점수 표시 → 명시적 승인 요청", async () => {
  const app = harness();
  await app.button("로컬 신뢰도").handlers.click();
  assert.ok(app.requests.some(r => r.url.endsWith("/verify-report")));
  assert.ok(app.nodes.some(n => /초안 · 사람 검토 필요/.test(n.textContent)));
  assert.ok(app.nodes.some(n => /신뢰도 0.6/.test(n.textContent)));
  assert.ok(app.nodes.some(n => n.textContent.includes("<script>悪意</script>")));
  assert.ok(!app.nodes.some(n => n.tag === "a" && /^javascript:/i.test(n.href || "")));
  assert.ok(!app.requests.some(r => r.url.endsWith("/review")), "생성 직후 자동 승인 금지");
  app.nodes.find(n => n.attrs["aria-label"] === "검토자").value = "검토자";
  app.nodes.find(n => n.tag === "textarea").value = "원문·번역 확인";
  app.state.report = {...app.state.report, status: "approved", version: 2};
  await app.button("검토 후 승인").handlers.click();
  const submitted = app.requests.find(r => r.url.endsWith("/review"));
  assert.deepEqual(submitted.body, {action: "approve", reviewer: "검토자", note: "원문·번역 확인", version: 1});
  assert.ok(app.nodes.some(n => /승인됨.*버전 2/.test(n.textContent)));
});

test("반환 JSON 파일을 입력 해시와 함께 전달하고 잘못된 실행 응답은 오류로 표시", async () => {
  const app = harness();
  await new Promise(resolve => setImmediate(resolve));
  const file = app.nodes.find(n => n.type === "file");
  file.files = [{size: 100, text: async () => JSON.stringify({claims: [{claim_id: "old-c1"}]})}];
  app.state.fail = true;
  await app.button("반환 JSON").handlers.click();
  const sent = app.requests.find(r => r.url.endsWith("/report"));
  assert.equal(sent.body.verification_input_sha256, "a".repeat(64));
  assert.equal(sent.body.reliability_result.claims[0].claim_id, "old-c1");
  assert.ok(app.nodes.some(n => n.attrs.role === "alert" && /현재 입력에 없는/.test(n.textContent)));
  assert.ok(!app.nodes.some(n => /초안 · 사람 검토 필요/.test(n.textContent)));
});

test("잘못된 JSON 파일은 모델 API에 전송하지 않는다", async () => {
  const app = harness();
  app.nodes.find(n => n.type === "file").files = [{size: 100, text: async () => "invalid json"}];
  await app.button("반환 JSON").handlers.click();
  assert.ok(!app.requests.some(r => r.body !== null));
  assert.ok(app.nodes.some(n => n.attrs.role === "alert"));
});

test("비교 제안은 기본 선택하지 않으며 사람이 반영·제외 여부를 보낸다", async () => {
  const app = harness();
  app.state.report.proposed_comparisons = [{item_id: "common_facts:0", section: "common_facts",
    text: "검토 대기 비교", claim_ids: ["a-c1", "b-c1"]}];
  await app.button("로컬 신뢰도").handlers.click();
  const choice = app.nodes.find(n => n.type === "checkbox");
  assert.equal(choice.checked, false);
  const section = app.nodes.find(n => n.tag === "section" && n.children.some(c => /공통 사실 주장/.test(c.textContent)));
  assert.ok(section.children.some(n => /공통 내용 후보.*검토 대기 비교/.test(n.textContent)));
  assert.ok(section.children.some(n => /신뢰도 0.6: 번역/.test(n.textContent)));
  assert.ok(!section.children.some(n => /찾지 못했습니다/.test(n.textContent)));
  app.nodes.find(n => n.attrs["aria-label"] === "검토자").value = "검토자";
  app.nodes.find(n => n.tag === "textarea").value = "두 인용 대조";
  await app.button("검토 후 승인").handlers.click();
  assert.deepEqual(app.requests.find(r => r.url.endsWith("/review")).body.comparison_decisions,
    {"common_facts:0": false});
});
