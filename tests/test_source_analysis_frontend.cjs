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
        percent: 50, completed: 2, total: 4, detail: "문서 2쌍 비교 중"})},
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
  assert.ok(app.nodes.some(n => /문서 2쌍 비교 중/.test(n.textContent)));
  app.release({ok: true, json: async () => ({docs: [], claims: [], warnings: []})});
  await pending;
  assert.equal(bar.value, 100);
  assert.equal(app.intervals.size, 0);
  assert.equal(app.button.disabled, false);
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
});
