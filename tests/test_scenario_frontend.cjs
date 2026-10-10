"use strict";
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {progressHtml, artifactsHtml, reportDownloadHtml} = require('../docs/scenario-live.js');

const job = {
  id: 'example', status: 'running', stage: 'collecting', elapsed_seconds: 63, percent: 20,
  input: {question: '대만해협 양측 발표'},
  steps: [{id: 'queries', label: '검색어', status: 'completed'}, {id: 'collecting', label: '원문 수집', status: 'running'},
    {id: 'report', label: '보고서', status: 'pending'}],
  artifacts: {queries: '/api/collections/example/download?format=queries'}, progress: {},
};

test('보고서 근거는 반환된 라벨로 표시하고 없는 라벨을 점수에서 만들지 않는다', () => {
  const context = vm.createContext({window: {ScenarioLive: {reportDownloadHtml: () => ''}}});
  vm.runInContext(fs.readFileSync(require.resolve('../docs/scenario-report.js'), 'utf8'), context);
  const root = {innerHTML: '', querySelectorAll: () => [], querySelector: () => ({addEventListener() {}})};
  const labels = ['값 일치', '개연성 있음', '판단 보류', null, '<script>새 라벨</script>'];
  const report = {status: 'draft', version: 1, question: '질문', sections: {},
    evidence: labels.map((label, i) => ({claim_id: `d${i}-c1`, document_id: `d${i}`, label,
      reliability: 0.9876, translated_quote: '번역', original_quote: '원문'}))};
  context.window.ScenarioReport.mount(root, 'example', report);
  for (const label of labels.slice(0, 3)) assert.ok(root.innerHTML.includes(`data-label="${label}"`));
  assert.match(root.innerHTML, /라벨 미제공/);
  assert.match(root.innerHTML, /&lt;script&gt;새 라벨/);
  assert.doesNotMatch(root.innerHTML, /0\.9876|<script>/);
  assert.equal(report.evidence[3].label, null);
});

test('보고서와 Fusion 대기 화면은 선행 순서와 실제 진행 상태를 안내한다', () => {
  const report = progressHtml(job, 'report'), fusion = progressHtml(job, 'analysis');
  assert.match(report, /검색·수집 → 주장·유사도 분석 → 신뢰도 계산/);
  assert.match(fusion, /원문 수집 후 문서가 먼저 표시/);
  assert.match(report, /1 \/ 6단계 완료/);
  assert.match(report, /남은 시간 계산 중/);
  assert.doesNotMatch(report, /예상 남은 시간 약/);
  const estimated = progressHtml({...job, estimated_remaining_seconds: 125, estimate_samples: 2});
  assert.match(estimated, /약 3분 · 이전 2회 실측 기준/);
});

test('준비된 산출물만 다운로드 링크이며 미완료 결과는 비활성이다', () => {
  const html = artifactsHtml(job);
  assert.match(html, /href="\/api\/collections\/example\/download\?format=queries"/);
  assert.equal((html.match(/<a /g) || []).length, 1);
  assert.equal((html.match(/aria-disabled="true"/g) || []).length, 5);
  assert.match(html, /data-report-format disabled/);
  assert.match(html, /주장·번역 JSON/);
});

test('보고서 형식은 PDF가 기본이며 원문 JSON과 다운로드가 분리된다', () => {
  const html = artifactsHtml({...job, artifacts: {collection: '/raw', report_json: '/report'}});
  assert.match(html, /value="pdf" selected/);
  assert.match(html, /value="md"/);
  assert.match(html, /value="json"/);
  assert.match(html, /report\/download\?format=pdf/);
  assert.match(html, /href="\/raw" download>수집 원문\(JSON\) 저장/);
  assert.doesNotMatch(reportDownloadHtml('bad"id'), /bad"id/);
});

test('완료·실패 상태는 로딩을 멈추며 실패만 이어서 실행할 수 있다', () => {
  const completed = progressHtml({...job, status: 'completed', artifacts: {report_json: '/report'}, counts: {articles: 15, claims: 15}});
  assert.match(completed, /문서 15개 · 대표 주장 15개/);
  assert.match(completed, /보고서 확인/);
  assert.doesNotMatch(completed, /activity-dot|data-scenario-stop/);
  const failed = progressHtml({...job, status: 'failed', error: '<script>bad()</script>'});
  assert.match(failed, /data-scenario-resume/);
  assert.match(failed, /&lt;script&gt;/);
  assert.doesNotMatch(failed, /<script>|activity-dot/);
});

test('보고서 파일이 없거나 생성 중이면 보고서 완료를 알리지 않는다', () => {
  assert.doesNotMatch(progressHtml({...job, status: 'completed'}), /초안이 준비되었습니다/);
  assert.doesNotMatch(progressHtml({...job, stage: 'report'}), /초안이 준비되었습니다/);
  assert.match(progressHtml({...job, status: 'completed', artifacts: {report_json: '/report'}}), /초안이 준비되었습니다/);
});

test('새 질문 화면은 이전 완료 실행을 복원하지 않고 실제 진행 중 실행만 이어받는다', async () => {
  for (const active of [null, job]) {
    const calls = [], status = {innerHTML: ''}, content = {innerHTML: ''};
    const context = vm.createContext({window: {}, URL, setTimeout() {}, clearTimeout() {},
      document: {activeElement: null, querySelectorAll: () => [], addEventListener() {}},
      localStorage: {getItem: () => 'old-completed', setItem() {}},
      fetch: async url => {calls.push(url); return {ok: true, json: async () => active};},
    });
    vm.runInContext(fs.readFileSync(require.resolve('../docs/scenario-live.js'), 'utf8'), context);
    const root = {dataset: {}, isConnected: true, addEventListener() {}, querySelector: selector =>
      selector === '[data-scenario-status]' ? status : selector === '[data-scenario-content]' ? content : null};
    context.window.ScenarioLive.mount(root, 'scope');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls[0], '/api/scenarios/active');
    assert.ok(!calls.some(url => url.includes('old-completed')));
    assert.doesNotMatch(status.innerHTML, /초안이 준비되었습니다/);
    if (active) assert.match(status.innerHTML, /원문 수집 중/);
    else assert.equal(status.innerHTML, '');
  }
});

test('완료된 실행에서 질문을 고치면 기존 결과와 실행 ID를 화면에서 분리한다', async () => {
  const handlers = {}, selected = [], status = {}, content = {}, config = {}, message = {};
  const fields = {question: {value: '이전 질문'}, count: {value: 20}, date: {value: ''}};
  const form = {elements: {namedItem: name => fields[name]}, querySelectorAll: () => [],
    addEventListener: (name, fn) => {handlers[name] = fn;}};
  const done = {...job, status: 'completed', input: {...job.input, languages: ['ko']}, artifacts: {report_json: '/report'}};
  const root = {dataset: {}, isConnected: true, addEventListener() {}, querySelector: selector => ({
    '#live-collection form': form, '[data-scenario-status]': status, '[data-scenario-content]': content,
    '[data-live-config]': config, '[data-live-message]': message,
  })[selector] || null};
  const context = vm.createContext({window: {CollectionLive: {buildRequest: () => ({question: '새 질문', languages: ['ko']})}},
    URL, setTimeout() {}, clearTimeout() {},
    document: {activeElement: null, querySelectorAll: () => [], addEventListener() {}},
    localStorage: {getItem: () => job.id, setItem() {}},
    fetch: async url => ({ok: true, json: async () => url === '/api/config' ? {scenario_ready: true} : done}),
  });
  vm.runInContext(fs.readFileSync(require.resolve('../docs/scenario-live.js'), 'utf8'), context);
  context.window.ScenarioLive.mount(root, 'scope', {id: job.id, onSelect: id => selected.push(id)});
  await new Promise(resolve => setImmediate(resolve));
  assert.match(status.innerHTML, /보고서 초안이 준비되었습니다/);
  handlers.input();
  assert.equal(status.innerHTML, '');
  assert.equal(content.innerHTML, '');
  assert.equal(selected.at(-1), null);
});

test('페이지를 벗어나도 클라이언트는 후속 실행이나 취소를 보내지 않는다', async () => {
  const callbacks = {}, calls = [], timers = [];
  const context = vm.createContext({window: {}, URL, Date, setTimeout: callback => {timers.push(callback); return timers.length;}, clearTimeout() {},
    document: {activeElement: null, querySelectorAll: () => [], addEventListener: (name, callback) => {callbacks[name] = callback;}},
    localStorage: {getItem: () => 'example', setItem() {}},
    fetch: async (url, options) => { calls.push([url, options]); return {ok: true, json: async () => job}; },
  });
  vm.runInContext(fs.readFileSync(require.resolve('../docs/scenario-live.js'), 'utf8'), context);
  const root = {dataset: {}, isConnected: true, querySelector: () => null, addEventListener() {}};
  context.window.ScenarioLive.mount(root, 'analysis');
  await new Promise(resolve => setImmediate(resolve));
  root.isConnected = false;
  timers.shift()();
  await new Promise(resolve => setImmediate(resolve));
  const reportRoot = {dataset: {}, isConnected: true, querySelector: () => null, addEventListener() {}};
  context.window.ScenarioLive.mount(reportRoot, 'report');
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(calls.length >= 3);
  assert.ok(calls.every(([url, options]) => url === '/api/scenarios/example' && !options));
  assert.ok(!callbacks.beforeunload, '페이지 종료 이벤트에서 작업을 취소하면 안 된다');
});
