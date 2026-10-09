"use strict";

// 브라우저·추가 패키지 없이 조회 순서만 검증한다. 실제 DOM 배치는 브라우저에서 확인한다.
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function makeHarness() {
  const pending = new Map();
  const rendered = [];
  const messages = [];
  const timers = [];
  const controls = new Map();
  const context = vm.createContext({
    document: {
      getElementById(id) {
        if (!controls.has(id)) controls.set(id, {addEventListener() {}});
        return controls.get(id);
      },
    },
    fetch(url) {
      return new Promise(resolve => pending.set(url, resolve));
    },
    setTimeout(callback) { timers.push(callback); return timers.length; },
    clearTimeout() {},
    rendered,
    messages,
  });
  const source = readFileSync(join(__dirname, "../app/static/app.js"), "utf8");
  // 시작 시 설정 조회만 건너뛰고 실제 앱의 조회 함수를 그대로 실행한다.
  vm.runInContext(source.replace(/\ninit\(\);\s*$/, "\n"), context);
  vm.runInContext(`
    renderReport = report => {state.report = report; rendered.push(report.id);};
    refreshHistory = async () => [];
    message = (...args) => messages.push(args);
    setBusy = () => {};
  `, context);
  return {
    rendered, messages, timers,
    load(id) { return vm.runInContext(`loadReport(${JSON.stringify(id)})`, context); },
    resolve(id, status = "draft", ok = true) {
      pending.get(`/api/runs/${id}`)({ok, status: ok ? 200 : 500,
        json: async () => ok ? {id, status} : {detail: "이전 요청 오류"}});
    },
  };
}

test("늦은 이전 보고서 응답은 최근 선택을 덮지 않는다", async () => {
  const app = makeHarness();
  const older = app.load("A");
  const newer = app.load("B");
  app.resolve("B");
  await newer;
  app.resolve("A", "running");
  await older;
  assert.deepEqual(app.rendered, ["B"]);
  assert.equal(app.timers.length, 0);
});

test("이전 조회의 오류는 최신 화면의 안내를 덮지 않는다", async () => {
  const app = makeHarness();
  const older = app.load("A");
  const newer = app.load("B");
  app.resolve("B");
  await newer;
  app.resolve("A", "failed", false);
  await older;
  assert.equal(app.messages.length, 1);
  assert.equal(app.messages[0][1], false);
});

test("현재 분석이 진행 중이면 다음 조회를 예약한다", async () => {
  const app = makeHarness();
  const current = app.load("A");
  app.resolve("A", "running");
  await current;
  assert.deepEqual(app.rendered, ["A"]);
  assert.equal(app.timers.length, 1);
});

test("현재 조회 실패는 오류 안내를 표시한다", async () => {
  const app = makeHarness();
  const current = app.load("A");
  app.resolve("A", "failed", false);
  await current;
  assert.equal(app.rendered.length, 0);
  assert.equal(app.messages.length, 1);
  assert.equal(app.messages[0][1], true);
});

test("앱과 시안의 이름·로고·파비콘은 겹눈으로 일치한다", () => {
  const actualHtml = readFileSync(join(__dirname, "../app/static/index.html"), "utf8");
  const storyboardHtml = readFileSync(join(__dirname, "../docs/storyboard.html"), "utf8");
  const storyboardScript = readFileSync(join(__dirname, "../docs/storyboard.js"), "utf8");
  for (const html of [actualHtml, storyboardHtml]) {
    assert.match(html, /<title>겹눈/);
    assert.match(html, /rel="icon"[^>]*favicon-gyeopnun\.png/);
  }
  assert.match(actualHtml, /<strong>겹눈<\/strong>/);
  assert.match(storyboardScript, /class="brand-mark" src="logo-gyeopnun\.png"/);
  assert.match(storyboardScript, /<strong>겹눈<\/strong>/);
  assert.doesNotMatch(actualHtml + storyboardHtml + storyboardScript, /SKYTRACE|>ST<|skytrace-/);
});

test("앱과 시안은 동일한 투명 PNG와 정사각 파비콘을 사용한다", () => {
  for (const name of ["logo-gyeopnun.png", "favicon-gyeopnun.png"]) {
    const actual = readFileSync(join(__dirname, "../app/static", name));
    const storyboard = readFileSync(join(__dirname, "../docs", name));
    assert.deepEqual(actual, storyboard);
    assert.equal(actual.subarray(1, 4).toString(), "PNG");
    // PNG 색상 유형 6은 RGB와 알파 채널을 함께 보관한다.
    assert.equal(actual[25], 6);
    if (name.startsWith("favicon")) {
      assert.equal(actual.readUInt32BE(16), 64);
      assert.equal(actual.readUInt32BE(20), 64);
    }
  }
});
