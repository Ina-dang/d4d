"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");

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
