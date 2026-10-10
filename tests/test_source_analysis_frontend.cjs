"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const vm = require("node:vm");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");

test("검색어 생성 중에는 비율을 꾸미지 않는 로딩 막대를 표시한다", () => {
  const {renderJob} = require("../docs/collection-live.js");
  const running = renderJob({id: "abc", status: "running", stage: "generating_queries"});
  assert.ok(running.includes("<progress"));
  assert.ok(running.includes("검색어 생성 진행 상태"));
  assert.ok(!/<progress[^>]*\bvalue=/.test(running));
  assert.ok(!renderJob({id: "abc", status: "failed", stage: "generating_queries"}).includes("<progress"));
});

test("검색어 생성 단계 완료율과 실제 응답 수신량을 표시한다", () => {
  const {renderJob} = require("../docs/collection-live.js");
  const html = renderJob({id: "abc", status: "running", stage: "generating_queries",
    progress: {percent: 25, completed: 1, total: 4, received_chars: 82, detail: "zh 검색어 번역 중"}});
  assert.ok(html.includes('value="25"'));
  assert.ok(html.includes("25% (1/4단계 완료)"));
  assert.ok(html.includes("82자 수신 중"));
});

function harness() {
  const nodes = [], intervals = new Map();
  function element(tag) {
    const node = {tag, children: [], attrs: {}, dataset: {}, textContent: "",
      append(...items) { this.children.push(...items); },
      replaceChildren(...items) { this.children = items; },
      setAttribute(name, value) { this.attrs[name] = value; },
      removeAttribute(name) { delete this.attrs[name]; },
    };
    nodes.push(node);
    return node;
  }
  const result = element("div");
  const button = {disabled: false, dataset: {sourceAnalysis: "abc"},
    parentElement: {querySelector: () => result}};
  let click, release;
  const post = new Promise(resolve => { release = resolve; });
  const context = vm.createContext({AbortController, Date, encodeURIComponent, JSON,
    document: {addEventListener(_event, fn) { click = fn; }, createElement: element},
    setInterval(fn) { intervals.set(1, fn); return 1; },
    clearInterval(id) { intervals.delete(id); },
    fetch: async (_url, options) => options?.method === "POST" ? post : {
      ok: true, json: async () => ({status: "running", stage: "comparing",
        percent: 1.4, completed: 3, total: 217, stage_percent: 50,
        stage_completed: 2, stage_total: 4, received_chars: 82, detail: "문서 2쌍 비교 중"})},
  });
  vm.runInContext(readFileSync(join(__dirname, "../docs/source-analysis-live.js"), "utf8"), context);
  return {nodes, intervals, button, release, result,
    click: () => click({target: {closest: () => button}})};
}

test("분석 중 실제 진행률과 단계를 표시하고 완료 시 타이머를 해제한다", async () => {
  const app = harness();
  const pending = app.click();
  const bar = app.nodes.find(n => n.tag === "progress");
  assert.ok(bar, "대기 중 진행 막대가 있어야 한다");
  assert.equal(app.button.disabled, true);
  assert.equal(app.intervals.size, 1);
  await app.intervals.get(1)();
  assert.equal(bar.value, 50);
  assert.ok(app.nodes.some(n => /2\/4/.test(n.textContent)));
  assert.ok(app.nodes.some(n => /82자 수신 중/.test(n.textContent)));
  assert.ok(app.nodes.some(n => /문서 2쌍 비교 중/.test(n.textContent)));
  app.release({ok: true, json: async () => ({docs: [], claims: [],
    warnings: ["d0: 인용·번역을 1회 재추출 후 검증했습니다."],
    timings: {phases: {similarity: {seconds: 12.3}}, llm_calls: 3, cache_hits: 2}})});
  await pending;
  assert.equal(bar.value, 100);
  assert.equal(app.intervals.size, 0);
  assert.equal(app.button.disabled, false);
  assert.ok(app.nodes.some(n => n.textContent === "확인할 분석 경고 1건"));
  assert.ok(app.nodes.some(n => /1회 재추출 후 검증/.test(n.textContent)));
  assert.ok(app.nodes.some(n => /유사도 12.3초/.test(n.textContent)));
  assert.ok(!app.nodes.some(n => /수신 중/.test(n.textContent)));
});

test("분석 실패 시 완료로 표시하지 않고 오류와 재시도 상태를 보여준다", async () => {
  const app = harness();
  const pending = app.click();
  await app.intervals.get(1)?.();
  app.release({ok: false, json: async () => ({detail: "인용 검사 실패"})});
  await pending;
  const bar = app.nodes.find(n => n.tag === "progress");
  assert.ok(bar && bar.value < 100);
  assert.ok(app.nodes.some(n => n.attrs.role === "alert" && /인용 검사 실패/.test(n.textContent)));
  assert.equal(app.intervals.size, 0);
  assert.equal(app.button.disabled, false);
  assert.ok(!app.nodes.some(n => /수신 중/.test(n.textContent)));
});

test("snippet 결과는 신뢰도 함수 입력 다운로드와 임베딩 실측을 표시한다", async () => {
  const app = harness();
  const pending = app.click();
  app.release({ok: true, json: async () => ({docs: [], claims: [],
    analysis_scope: "text_snippet", warnings: [],
    timings: {phases: {embedding: {seconds: 1.2}}, llm_calls: 4,
      embedding_calls: 1, cache_hits: 0}})});
  await pending;
  assert.ok(app.nodes.some(n => n.tag === "a" &&
    n.href === "/api/collections/abc/analysis/download?format=verification"));
  assert.ok(app.nodes.some(n => /snippet 범위/.test(n.textContent)));
  assert.ok(app.nodes.some(n => /임베딩 1.2초/.test(n.textContent)));
});

test("질문 관련도 결과는 sim 숫자의 의미를 화면에 표시한다", async () => {
  const app = harness();
  const pending = app.click();
  app.release({ok: true, json: async () => ({
    docs: [{id: "doc_a", country: "CN", weight: 0.5, sim: 0.63}], claims: [],
    analysis_scope: "text_snippet", similarity_target: "user_question", warnings: []})});
  await pending;
  assert.ok(app.nodes.some(n => /사용자 질문.*snippet.*관련도/.test(n.textContent)));
  assert.ok(app.nodes.some(n => /문서마다 숫자 하나/.test(n.textContent)));
  assert.ok(app.nodes.some(n => n.tag === "a" &&
    n.href === "/api/collections/abc/analysis/download?format=verification"));
});

test("전체 분석 주장과 검증 전달 대표 주장 개수를 구분한다", async () => {
  const app = harness();
  const pending = app.click();
  app.release({ok: true, json: async () => ({docs: [{id: "a"}, {id: "b"}],
    claims: [{claim_id: "a-c1"}, {claim_id: "a-c2"}], warnings: [],
    verification_selection: {exported_claim_count: 1}})});
  await pending;
  assert.ok(app.nodes.some(n => /문서 2개 · 주장 2개 분석 완료.*대표 주장 1개/.test(n.textContent)));
});
