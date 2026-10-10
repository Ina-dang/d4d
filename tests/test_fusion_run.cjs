"use strict";

// 검색 화면의 실제 수집 결과(run)를 Fusion 분석 출처로 바꾸는 규칙과, 수집 완료 화면의 Fusion 연결 링크를 확인한다.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const docs = path.join(__dirname, "..", "docs");
const FusionScreen = vm.runInNewContext(fs.readFileSync(path.join(docs, "fusion.js"), "utf8") + ";FusionScreen", {});
const CollectionLive = require(path.join(docs, "collection-live.js"));

test("수집 문서에 보고서의 판정 주장을 문서 id로 붙인다", () => {
  const job = {output: {by_country: {
    CN: [{doc_id: "d1", title: "공지", source_name: "중국 국방부", language: "zh", source_category: "party_official", tier: 2, credibility_weight: 0.85}],
    US: [{doc_id: "d2", title: "보도", source_name: "Reuters", country: "GLOBAL", language: "en", is_reprint_likely: "True", quoted_source: "None"}],
  }}};
  const report = {docs: [{id: "d1", weight: 0.85}], evidence: [
    {claim_id: "d1-c1", document_id: "d1", translated_quote: "훈련 시작", label: "값 일치", reliability: 0.72}]};
  const [a, b] = FusionScreen.runSources(job, report);
  assert.equal(a.country, "CN");
  assert.equal(a.script, "간체");
  assert.equal(a.role, "당사국 공식");
  assert.equal(a.reliability, 0.72);
  assert.deepEqual(a.claims.map(c => c.label), ["값 일치"]);
  assert.equal(b.country, "GLOBAL", "문서의 출처 국가가 수집 그룹보다 우선");
  assert.equal(b.relation, "reprint");
  assert.equal(b.origin_label, null);
  assert.equal(b.claims, undefined, "판정 주장이 없는 문서는 claims를 두지 않는다");
});

test("보고서가 없으면 문서만 돌려준다", () => {
  const sources = FusionScreen.runSources({output: {by_country: {KR: [{doc_id: "k1", title: "기사"}]}}}, null);
  assert.equal(sources.length, 1);
  assert.equal(sources[0].claims, undefined);
});

test("수집이 끝나면 같은 수집 id로 Fusion 분석 링크를 보여 준다", () => {
  const html = CollectionLive.renderJob({id: "abc 1", status: "completed", stage: "completed", output: {total_count: 1, by_country: {}}});
  assert.match(html, /href="storyboard\.html\?screen=analysis&run=abc%201"/);
  const running = CollectionLive.renderJob({id: "abc", status: "running", stage: "collecting"});
  assert.doesNotMatch(running, /screen=analysis/);
});
