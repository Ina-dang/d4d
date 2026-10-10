"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const vm = require("node:vm");

test("선택 언어와 사용자 문장이 실제 수집 요청으로 전달된다", () => {
  const {buildRequest} = require("../docs/collection-live.js");
  const fields = {
    question: {value: "  인도·파키스탄 양측 주장을 출처와 함께 비교해줘  "},
    date: {value: "2026-10-01"}, count: {value: "2"},
  };
  const form = {elements: {namedItem: name => fields[name]},
    querySelectorAll: () => [{value: "zh-Hans"}, {value: "hi"}, {value: "ur"}]};
  assert.deepEqual(buildRequest(form), {question: "인도·파키스탄 양측 주장을 출처와 함께 비교해줘",
    languages: ["zh", "hi", "ur"], event_date: "2026-10-01", max_docs_per_country: 2, days_back: 30});
});

test("수집된 원문과 오류는 HTML로 실행되지 않고 안전한 출처 링크만 표시된다", () => {
  const {renderJob} = require("../docs/collection-live.js");
  const rendered = renderJob({id: "abc", status: "completed", stage: "completed", error: "",
    collection_request: {event: "<script>bad()</script>", queries: [{language: "en", query: "Taiwan Strait"}]},
    output: {total_count: 1, by_country: {US: [{title: "<img onerror='bad()'>",
      source_name: "Reuters", url: "javascript:bad()", language: "en", article_text: "<script>bad()</script>"}]}}});
  assert.ok(rendered.includes("Taiwan Strait"));
  assert.ok(rendered.includes("&lt;script&gt;"));
  assert.ok(!rendered.includes("<script>"));
  assert.ok(!rendered.includes('href="javascript:'));
  const failed = renderJob({id: "abc", status: "failed", stage: "collecting", error: "<img onerror='bad()'>"});
  assert.ok(failed.includes("&lt;img"));
  assert.ok(!failed.includes("수집 완료"));
});

test("본문 필터의 선택 언어와 제외 사유를 보여준다", () => {
  const {renderJob} = require("../docs/collection-live.js");
  const rendered = renderJob({id: "abc", status: "completed", stage: "completed", error: "",
    output: {total_count: 0, by_country: {}, filtering: {selected_languages: ["en", "hi", "ur"],
      rejected_counts: {language_not_selected: 2, security_topic_missing: 1}}}});
  assert.ok(rendered.includes("본문 판별"));
  assert.ok(rendered.includes("en, hi, ur"));
  assert.ok(rendered.includes("선택하지 않은 언어: 2건"));
  assert.ok(rendered.includes("안보 주제 근거 없음: 1건"));
});

test("실제 검색어와 언어별 수집 수·본문 복구 결과를 표시한다", () => {
  const {renderJob} = require("../docs/collection-live.js");
  const rendered = renderJob({id: "abc", status: "completed", stage: "completed", error: "",
    collection_request: {queries: [{language: "ur", query: "full analysis plan", search_query: "short event query"}]},
    output: {total_count: 2, by_country: {}, filtering: {selected_languages: ["ur"],
      body_recovery: {attempted: 2, recovered: 1, failed: 1}, language_counts: {retained: {ur: 2}}}}});
  assert.ok(rendered.includes("실제 검색: short event query"));
  assert.ok(rendered.includes("ur: 2건"));
  assert.ok(rendered.includes("본문 재수집: 2건 시도 · 1건 확보"));
});

test("서버의 422 응답은 거절된 필드와 사유를 화면에 표시한다", async t => {
  const {mount} = require("../docs/collection-live.js");
  const fields = {
    question: {value: "인도 파키스탄 충돌에 관한 내용이 궁금해"},
    date: {value: ""}, count: {value: "21"},
  };
  const button = {disabled: false};
  const result = {textContent: ""};
  const config = {textContent: ""};
  let submit;
  const form = {
    elements: {namedItem: name => fields[name]},
    querySelectorAll: () => [{value: "en"}],
    querySelector: () => button,
    addEventListener: (_event, handler) => { submit = handler; },
  };
  const root = {
    dataset: {},
    querySelector: selector => ({form, "[data-live-result]": result,
      "[data-live-config]": config})[selector],
  };
  t.mock.method(globalThis, "fetch", async url => ({
    ok: url === "/api/config", status: url === "/api/config" ? 200 : 422,
    json: async () => url === "/api/config"
      ? {ollama_model: "gemma4:e2b", collection_ready: true}
      : {detail: [{type: "less_than_equal", loc: ["body", "max_docs_per_country"],
        msg: "Input should be less than or equal to 20", input: 21, ctx: {le: 20}}]},
  }));
  mount(root);
  await submit({preventDefault() {}});
  assert.match(result.textContent, /국가당 최대 문서 수/);
  assert.match(result.textContent, /20/);
  assert.equal(button.disabled, false);
});

test("실제 요청의 펼침·접힘 상태는 상태 조회 중 유지되고 새 수집에서 초기화된다", async () => {
  const timers = [];
  const button = {disabled: false};
  const config = {textContent: ""};
  let submit, detail, html = "", polls = 0;
  // innerHTML/textContent 교체는 기존 details 노드를 제거하는 DOM 동작을 재현한다.
  const result = {
    set innerHTML(value) {
      html = value;
      const match = value.match(/<details([^>]*)><summary>수집기에 전달한 실제 요청/);
      detail = match ? {open: /\bopen\b/.test(match[1])} : null;
    },
    set textContent(_value) { html = ""; detail = null; },
    querySelector(selector) {
      return selector === "[data-collection-request]" && html.includes("data-collection-request") ? detail : null;
    },
  };
  const fields = {question: {value: "인도 파키스탄 충돌 양측 입장 비교"}, date: {value: ""}, count: {value: "2"}};
  const form = {
    elements: {namedItem: name => fields[name]},
    querySelectorAll: () => [{value: "en"}], querySelector: () => button,
    addEventListener: (_event, handler) => { submit = handler; },
  };
  const root = {dataset: {}, isConnected: true,
    querySelector: selector => ({form, "[data-live-result]": result, "[data-live-config]": config})[selector]};
  const context = vm.createContext({window: {}, URL,
    sessionStorage: {getItem: () => "old", setItem() {}},
    setTimeout(callback) { timers.push(callback); },
    fetch: async (url, options) => ({ok: true, json: async () => {
      if (url === "/api/config") return {ollama_model: "local", collection_ready: true};
      if (options?.method === "POST") return {id: "new"};
      const id = url.endsWith("/old") ? "old" : "new";
      const status = id === "old" && ++polls < 3 ? "running" : "completed";
      return {id, status, stage: status === "running" ? "collecting" : "completed",
        collection_request: {queries: [{language: "en", query: id}]}};
    }}),
  });
  vm.runInContext(readFileSync(join(__dirname, "../docs/collection-live.js"), "utf8"), context);
  context.window.CollectionLive.mount(root);
  const flush = () => new Promise(resolve => setImmediate(resolve));
  await flush();
  assert.equal(detail.open, false);
  detail.open = true;
  timers.shift()();
  await flush();
  assert.equal(detail.open, true, "주기적 상태 조회로 펼친 요청이 닫히면 안 된다");
  detail.open = false;
  timers.shift()();
  await flush();
  assert.equal(detail.open, false, "사용자가 닫으면 완료 갱신 후에도 닫혀 있어야 한다");
  detail.open = true;
  await submit({preventDefault() {}});
  assert.equal(detail.open, false, "새 수집은 이전 수집의 펼침 상태를 이어받지 않는다");
  assert.equal(button.disabled, false);
});
