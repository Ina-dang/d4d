"use strict";

/**
 * 결합 기획을 체험하는 독립 UI 시안이다.
 * 시안 자료·검토는 가상이며, 검색 화면의 실제 수집 패널만 API에 연결한다.
 */
const params = new URLSearchParams(window.location.search);
const embedded = params.get("embed") === "1";
const demonstration = params.get("demo") === "1";
const analysisAppUrl = window.location.pathname.startsWith("/storyboard/")
  ? "/app"
  : "http://127.0.0.1:8766/app";
const sourceOptions = [
  { id: "official", label: "정부·기관 공지" },
  { id: "press", label: "언론 보도" },
  { id: "official-sns", label: "공식 SNS" },
  { id: "public-sns", label: "일반 SNS" },
];
const languageOptions = [
  { id: "ko", label: "한국어" },
  { id: "zh-Hans", label: "중국어 간체" },
  { id: "zh-Hant", label: "중국어 번체" },
  { id: "en", label: "영어" },
  { id: "ja", label: "일본어" },
  { id: "hi", label: "힌디어" },
  { id: "ur", label: "우르두어" },
];
const defaultSourceTypes = ["official", "press"];
const defaultLanguages = ["ko", "en"];

function readSelections(query, key, options, defaults) {
  if (!query.has(key)) return [...defaults];
  const requested = query.get(key).split(",");
  return options
    .filter((option) => requested.includes(option.id))
    .map((option) => option.id);
}

let selectedSourceTypes = readSelections(
  params,
  "sources",
  sourceOptions,
  defaultSourceTypes,
);
let selectedLanguages = readSelections(
  params,
  "languages",
  languageOptions,
  defaultLanguages,
);
// 시연 주제: 수집·주장 추출·fusion.py 판정 결과를 미리 만들어 둔 두 가지 (fusion-data/<id>.json, issues/<id>.json)
const topics = [
  {
    id: "taiwan-strait",
    label: "대만해협",
    keyword: "대만해협 군사훈련",
    period: "최근 5년",
    question:
      "대만해협 일대 군사훈련 관련, 중국·대만과 주변국의 발표·보도는 어디서 일치하고 어디서 갈리는가?",
    countries: ["중국", "대만", "일본", "한국", "미국"],
  },
  {
    id: "india-pakistan",
    label: "인도·파키스탄 분쟁",
    keyword: "인도 파키스탄 무력 충돌",
    period: "최근 5년",
    question:
      "인도·파키스탄 무력 충돌 관련, 양국 정부 발표와 각국 보도는 어디서 일치하고 어디서 갈리는가?",
    countries: ["인도", "파키스탄", "중국", "미국"],
  },
];
const readTopic = (query) =>
  topics.find((topic) => topic.id === query.get("topic")) || topics[0];
let selectedTopic = readTopic(params);
let question = params.get("q") || selectedTopic.question;
// 검색 화면에서 실제 수집을 마치면 run=<수집 id>로 Fusion 분석·보고서가 그 결과를 읽는다.
let runId = params.get("run");
const screens = [
  {
    id: "scope",
    title: "검색",
    icon: "search",
    label: "질문과 범위",
    caption: "질문·사건·기간·지역을 설정하고 분석 작업 공간으로 이동합니다.",
  },
  {
    id: "analysis",
    title: "Fusion 분석",
    icon: "network",
    label: "핵심 비교 화면",
    caption:
      "기관 배치도·출처 관계망·게시 타임라인을 함께 봅니다. 원문은 오른쪽 상세 패널에서 확인합니다.",
  },
  {
    id: "report",
    title: "보고서",
    icon: "file-text",
    label: "사람의 최종 검토",
    caption:
      "밝은 문서 지면과 오른쪽 근거·검토 도구를 함께 사용합니다. 별도 승인 페이지는 없습니다.",
  },
];
// 이전 여섯 화면의 링크도 통합된 분석 화면으로 연결한다.
const requestedScreen = params.get("screen");
const legacyAnalysis = ["sources", "perspectives", "claims", "evidence"];
let selectedScreen = screens.find(
  (screen) =>
    screen.id ===
    (legacyAnalysis.includes(requestedScreen) ? "analysis" : requestedScreen),
);
if (!selectedScreen && params.get("view") !== "board") selectedScreen = screens[0];
let activeSource = ["S1", "S2", "S3", "S4"].includes(params.get("source"))
  ? params.get("source")
  : "S2";
let activeClaim = ["aligned", "conflict", "perspective", "regional"].includes(
  params.get("claim"),
)
  ? params.get("claim")
  : requestedScreen === "perspectives"
    ? "perspective"
    : "conflict";
const app = document.getElementById("app");
const sources = [
  {
    id: "S1",
    place: "중국",
    institution: "가상 발사 운용기관",
    language: "중국어 간체",
    type: "기관 공지",
    group: "가상 원출처 A",
    published: "13:10 UTC",
    scope: "시험 구역 L1",
  },
  {
    id: "S2",
    place: "대만",
    institution: "가상 항공 관제기관",
    language: "중국어 번체",
    type: "기관 공지",
    group: "가상 원출처 B",
    published: "13:20 UTC",
    scope: "시험 구역 L1 · 관할 항로",
  },
  {
    id: "S3",
    place: "일본",
    institution: "가상 운항기관",
    language: "일본어",
    type: "운항 안내",
    group: "가상 원출처 C",
    published: "13:25 UTC",
    scope: "해당 기관 운항 항로",
  },
  {
    id: "S4",
    place: "중국",
    institution: "S1 공지의 영문 번역",
    language: "영어",
    type: "번역본",
    group: "가상 원출처 A",
    published: "13:30 UTC",
    scope: "S1과 동일",
  },
];

// 문자열을 DOM으로 출력하기 전 이스케이프한다. 입력 문구는 HTML로 실행하지 않는다.
function escapeHtml(value) {
  return String(value).replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[character],
  );
}

// 주제·질문(기본 질문과 다를 때만)·출처·언어를 URL에 싣는다.
function setCollectionParams(query) {
  query.set("topic", selectedTopic.id);
  if (runId) query.set("run", runId);
  else query.delete("run");
  if (question !== selectedTopic.question) query.set("q", question);
  else query.delete("q");
  query.set("sources", selectedSourceTypes.join(","));
  query.set("languages", selectedLanguages.join(","));
}

function screenUrl(id, embed = false, extra = {}) {
  const query = new URLSearchParams({ screen: id, ...extra });
  setCollectionParams(query);
  if (embed) query.set("embed", "1");
  return "storyboard.html?" + query.toString();
}

function brand() {
  return '<a class="brand" href="storyboard.html" aria-label="겹눈 스토리보드"><img src="logo-gyeopnun.png" width="56" height="40" alt=""><span class="brand-copy"><strong>겹눈</strong><small>다국어 근거 분석</small></span></a>';
}

// 아이콘은 로컬 Lucide 스프라이트를 사용해 별도 라이브러리·외부 호출 없이 표시한다.
function sidebarIcon(name) {
  return `<svg class="sidebar-icon" aria-hidden="true" focusable="false"><use href="sidebar-icons.svg#${name}"></use></svg>`;
}

function board() {
  app.innerHTML = `
    <header class="masthead">
      ${brand()}
      <a class="button primary" href="${screenUrl("scope")}">직접 둘러보기 ↗</a>
    </header>
    <main id="main" class="board">
      <section class="board-hero">
        <div>
          <h1>다국어 출처 비교 시안</h1>
          <p>검색 조건, 출처 비교, 보고서 검토를 세 화면에서 체험합니다.</p>
        </div>
        <aside class="board-key">
          <strong>화면 시안과 실제 기능을 구분합니다.</strong>
          <p>이 보드: 가상 자료로 클릭 체험</p>
          <p>실제 MVP: <a href="${analysisAppUrl}">분석 앱에서 확인 ↗</a></p>
        </aside>
      </section>
      <div class="notice">아래 미리보기는 가상 자료입니다. 검색 화면의 ‘실제 검색·수집’에서 사용자 질문으로 원문을 수집할 수 있습니다. 분석·승인 시안은 가상 자료를 사용합니다.</div>
      <div class="board-flow" aria-label="세 화면의 시연 순서"><span>01 검색</span><span aria-hidden="true">→</span><span>02 Fusion 분석 <small>출처 · 원문 · 비교 포함</small></span><span aria-hidden="true">→</span><span>03 보고서 · 승인</span></div>
      <div class="story-grid">
        ${screens
          .map(
            (screen, index) => `
          <article class="story" >
            <header class="story-head">
              <span class="number">0${index + 1}</span>
              <h2>${screen.title}</h2>
              <a href="${screenUrl(screen.id)}" aria-label="${screen.title} 화면 체험">체험 ↗</a>
            </header>
            <div class="story-frame">
              <iframe src="${screenUrl(screen.id, true)}" title="${screen.title} 시안" tabindex="-1" loading="lazy"></iframe>
            </div>
            <div class="story-caption"><p>${screen.caption}</p></div>
          </article>
        `,
          )
          .join("")}
      </div>
      <footer class="board-footer">
        <p>겹눈 / 3화면 통합안 · 2026-10-09</p>
        <p>일치 ≠ 진실 · 관점 차이 ≠ 오류 · 언어 ≠ 국가 · 승인 ≠ 진위 보증</p>
      </footer>
    </main>`;
  // 실제 iframe을 축소해 모든 미리보기가 같은 화면 구현을 사용하도록 한다.
  const observer = new ResizeObserver((entries) => {
    entries.forEach((entry) => {
      entry.target.querySelector("iframe").style.transform =
        `scale(${entry.contentRect.width / 1180})`;
    });
  });
  document
    .querySelectorAll(".story-frame")
    .forEach((frame) => observer.observe(frame));
}

function title(description, { compactSummary = false } = {}) {
  return `
    <header class="screen-title">
      <div><h1>${description}</h1>
        <p>주제를 고르면 Fusion 분석과 보고서가 그 주제의 결과로 바뀝니다.</p>
      </div>
    </header>${selectedScreen.id === "scope" ? "" : collectionSummaryHtml({ compact: compactSummary })}`;
}

// compact: 수집 출처 · 검색 언어 · 조건 변경을 한 줄로 (Fusion 분석 화면). 기본형은 보고서 화면 등에서 그대로 쓴다.
function collectionSummaryHtml({ compact = false } = {}) {
  const sourceLabels = sourceOptions
    .filter((option) => selectedSourceTypes.includes(option.id))
    .map((option) => option.label);
  const languageLabels = languageOptions
    .filter((option) => selectedLanguages.includes(option.id))
    .map((option) => option.label);
  if (compact)
    return `<div class="collection-summary is-compact" aria-label="선택한 수집 조건">
    <p><span>${runId ? "실제 수집" : "주제"}</span> <strong>${escapeHtml(runId ? runId.slice(0, 8) : selectedTopic.label)}</strong></p>
    <p><span>수집 출처</span> <strong>${sourceLabels.join(" · ") || "미선택"}</strong></p>
    <p><span>검색 언어</span> <strong>${languageLabels.join(" · ") || "미선택"}</strong></p>
    <a class="text-link" href="${screenUrl("scope", embedded)}" title="설정 시안 · 아래 가상 자료는 선택 조건으로 검색·필터링한 결과가 아닙니다.">조건 변경</a>
  </div>`;
  return `<div class="collection-summary" aria-label="선택한 수집 조건">
    <div><span>수집 출처</span><strong>${sourceLabels.join(" · ") || "미선택"}</strong></div>
    <div><span>검색 언어</span><strong>${languageLabels.join(" · ") || "미선택"}</strong></div>
    <a class="text-link" href="${screenUrl("scope", embedded)}">조건 변경</a>
    <p>설정 시안 · 아래 가상 자료는 선택 조건으로 검색·필터링한 결과가 아닙니다.</p>
  </div>`;
}

function collectionOptionsHtml(name, legend, options, selected) {
  return `<fieldset class="collection-options"><legend>${legend}</legend>
    <div class="scope-options">${options
      .map(
        (option) => `<label>
      <input type="checkbox" name="${name}" value="${option.id}" ${selected.includes(option.id) ? "checked" : ""}>
      <span>${option.label}</span></label>`,
      )
      .join("")}</div></fieldset>`;
}

function liveCollectionHtml() {
  const liveLanguages = [...languageOptions];
  return `<section id="live-collection" class="live-collection" aria-label="실제 검색·수집">
    <header class="scenario-page-head"><p class="small muted">검색 · 다국어 근거 분석</p>
      <h1>어떤 발표와 주장을 비교할까요?</h1>
      <p>질문을 입력하면 원문을 모으고, 주장을 비교해 근거가 담긴 보고서를 만듭니다.</p></header>
    <p class="small muted" data-live-config>실행 설정 확인 중</p>
    <form>
      <div class="field"><label for="live-question">사용자 질문</label>
        <textarea id="live-question" name="question" rows="3" required minlength="8" maxlength="1200"
          placeholder="예: 중국 대만 해협 충돌에 관한 양측 발표와 주요 보도를 비교하고 일치·상충·미확인 주장을 출처와 함께 정리해줘"></textarea></div>
      <fieldset class="collection-options"><legend>검색 언어</legend><div class="scope-options">
        ${liveLanguages.map((option) => `<label><input type="checkbox" name="live-language" value="${option.id}" ${selectedLanguages.includes(option.id) ? "checked" : ""}><span>${option.label}</span></label>`).join("")}
      </div></fieldset>
      <div class="scope-row">
        <div class="field"><label for="live-date">사건 날짜 · 선택</label><input id="live-date" name="date" type="date"></div>
        <div class="field"><label for="live-count">국가당 최대 문서 수</label><input id="live-count" name="count" type="number" min="1" max="20" value="20" required></div>
      </div>
      <p class="demo-note">공식 기관·언론·SNS에서 최근 30일 자료를 검색합니다. 중국·홍콩·대만은 합산 한도를 적용하며, 20건 설정 시 각각 최대 7·6·7건입니다. 사건 날짜는 검색어에 포함됩니다.</p>
      <div class="live-actions">
        <button class="button primary" type="submit">보고서 생성</button>
      </div>
      <p data-live-message role="status"></p>
    </form>
    <div data-scenario-status></div><div data-scenario-downloads></div>
    <p class="scenario-connection" data-scenario-connection role="status"></p>
    <div class="live-result" data-scenario-content></div>
  </section>`;
}

function sourcesHtml() {
  return `
    <div class="screen-content">
      <div class="selection" aria-label="출처 지역 필터">
        ${["전체", "중국", "대만", "일본"].map((place) => `<button type="button" data-source-filter="${place}" aria-pressed="${place === "전체"}">${place}</button>`).join("")}
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>근거</th><th>주장 주체 / 기관 소재지</th><th>원문 언어</th><th>게시 / 수집 · UTC</th><th>원출처</th><th>원문</th></tr></thead>
        <tbody>${sources
          .map(
            (source) => `<tr data-source-place="${source.place}">
          <td class="source-id">${source.id}</td>
          <td><strong>${source.institution}</strong><small>${source.place} · ${source.type}</small></td>
          <td>${source.language}<small>${source.scope}</small></td>
          <td>${source.published}<small>수집 13:40 UTC · 가상 시각</small></td>
          <td>${source.group}<small>${source.id === "S4" ? "S1의 번역본 · 추가 독립 근거 아님" : "독립성은 별도 검토"}</small></td>
          <td><button class="text-link" type="button" data-evidence="${source.id}">원문 보기 ↗</button></td>
        </tr>`,
          )
          .join("")}</tbody>
      </table></div>
      <div class="split section-rule">
        <div><h3>시간도 세 종류로 나눕니다.</h3>
          <div class="time-ruler" aria-label="가상 사건 시각과 게시·수집 시각 예시">
            <span class="t1">공지 게시<br>13:10 UTC</span><span class="t2">자료 수집<br>13:40 UTC</span><span class="t3">예정된 사건 시작<br>14:00 UTC</span>
          </div></div>
        <aside class="inspector"><h3>4문서 ≠ 독립 근거 4개</h3><p class="small muted">S1과 S4는 같은 원출처입니다. 서로 다른 원출처 그룹도 독립성을 자동 보증하지 않습니다.</p></aside>
      </div>
    </div>`;
}

function perspectivesHtml() {
  return `
    <div class="screen-content">
      <div class="table-wrap"><table class="compare-table">
        <thead><tr><th>비교 항목</th><th>중국 소재 · 가상 운용기관</th><th>대만 소재 · 가상 관제기관</th><th>일본 소재 · 가상 운항기관</th></tr></thead>
        <tbody>
          <tr><td class="row-name">공통 사실 주장<br><span class="tag">같은 사건</span></td>
            <td><div class="metric">14:00</div>시험 통제 시작 · UTC<small>S1 · 22:00 베이징시간</small></td>
            <td><div class="metric">14:00</div>시험 통제 시작 · UTC<small>S2 · 22:00 UTC+8</small></td>
            <td><div class="metric">14:00</div>시험 통제 시작 · UTC<small>S3 · 23:00 일본시간</small></td></tr>
          <tr><td class="row-name">기관별 해석<br><span class="tag">관점 차이</span></td>
            <td>발사 기술 검증을 위한 시험<small>S1의 목적 설명</small></td>
            <td>주변 공역 안전에 유의할 필요<small>S2의 주의 권고</small></td>
            <td>별도 평가 문장 미기재<small>S3에는 우회 시행 보고만 있음</small></td></tr>
          <tr><td class="row-name">지역별 상황<br><span class="tag">대상이 다름</span></td>
            <td>시험 구역 진입 제한<small>시험 구역 L1에 관한 공지</small></td>
            <td>관할 항로의 지연은 미확인<small>지연이 없다는 뜻은 아님</small></td>
            <td>해당 기관의 1개 항로 우회 보고<small>다른 지역 전체로 일반화 금지</small></td></tr>
        </tbody>
      </table></div>
      <div class="compare-legend"><span>기관 소재지 ≠ 국가 전체의 입장</span><span>보도 언어 ≠ 주장 주체</span></div>
      <p class="demo-note section-rule">목적 설명과 안전 우려는 함께 성립할 수 있습니다. 지역별 운항 영향도 대상이 다르면 직접 모순이 아닙니다.</p>
    </div>`;
}

const relations = {
  aligned: {
    title: "통제 시작 시각",
    status: "값 일치",
    confidence: "중간",
    sources: [
      "S1 · 중국 소재 운용기관",
      "S2 · 대만 소재 관제기관",
      "S3 · 일본 소재 운항기관",
    ],
    values: [
      "22:00 · UTC+8 → 14:00 UTC",
      "22:00 · UTC+8 → 14:00 UTC",
      "23:00 · UTC+9 → 14:00 UTC",
    ],
    basis: "같은 날짜 · 통제구역 L1 · 예정된 시작 시각",
    reason:
      "원문에 명시된 시간대를 맞추면 값이 일치합니다. 발표 내용의 일치이지 실제 통제 시행의 독립 확인은 아닙니다.",
    limit:
      "S4 영문 번역본은 S1과 같은 원출처이므로 추가 독립 근거로 세지 않습니다.",
  },
  conflict: {
    title: "통제 종료 시각",
    status: "상충 후보",
    confidence: "낮음",
    sources: ["S1 · 중국 소재 운용기관", "S2 · 대만 소재 관제기관"],
    values: ["22:40 · UTC+8 → 14:40 UTC", "22:20 · UTC+8 → 14:20 UTC"],
    basis: "같은 날짜 · 통제구역 L1 · 예정된 종료 시각",
    reason:
      "같은 비교 범위에서 발표된 종료 시각이 다릅니다. 수정 공지·구역 정의·추출 오류를 확인하기 전에는 어느 쪽이 틀렸다고 단정하지 않습니다.",
    limit:
      "두 발표의 차이는 보이지만 올바른 종료 시각을 결정할 독립 근거는 미확보입니다.",
  },
  perspective: {
    title: "시험 목적과 안전 평가",
    status: "관점 차이",
    confidence: "내용 검증 보류",
    sources: ["S1 · 중국 소재 운용기관", "S2 · 대만 소재 관제기관"],
    values: ["발사 기술 검증을 위한 시험", "주변 공역 안전에 유의할 필요"],
    basis: "같은 사건 · 목적 설명과 안전 권고는 다른 명제",
    reason:
      "서로 다른 해석을 병렬로 보존합니다. 기술 검증 목적과 안전 우려는 함께 성립할 수 있으므로 직접 모순으로 판정하지 않습니다.",
    limit:
      "해당 입장을 발표했다는 근거와 실제 목적·위험을 입증하는 근거는 구분해야 합니다.",
  },
  regional: {
    title: "지역별 항공 영향",
    status: "지역별 차이",
    confidence: "지역별로 별도 검토",
    sources: ["S2 · 대만 소재 관제기관", "S3 · 일본 소재 운항기관"],
    values: ["관할 항로의 지연은 미확인", "해당 기관의 1개 항로 우회 보고"],
    basis: "같은 사건 · 관할 항로와 운항 항로는 다른 대상",
    reason:
      "지역과 운항 대상이 다르므로 하나의 일치·상충 판단으로 합치지 않습니다. 우회 사실이 다른 지역의 지연을 입증하지도 않습니다.",
    limit:
      "미확인을 영향 없음으로 바꾸지 않습니다. 지역별 실제 영향은 별도의 관측 근거가 필요합니다.",
  },
};

function relationHtml(key) {
  const relation = relations[key];
  return `<div class="relation-head"><h2>${relation.title}</h2><span class="tag ${key === "conflict" ? "alert" : "accent"}">${relation.status}</span></div>
    <div class="claim-values">${relation.sources.map((source, index) => `<button type="button" data-evidence="${source.split(" ·")[0]}" class="claim-value"><span>${source}</span><strong>${relation.values[index]}</strong></button>`).join("")}</div>
    <div class="judgment"><div><p>${relation.reason}</p><small>비교 조건: ${relation.basis}</small></div><aside><span class="muted small">근거 충족도</span><strong>${relation.confidence}</strong><p>${relation.limit}</p></aside></div>`;
}

// 게시·수집·예정 사건 시각을 분리한다. 타임라인은 자동 감시나 관측 결과를 뜻하지 않는다.
function timelineHtml() {
  return `<section class="timeline-workspace" aria-labelledby="timeline-title">
    <header class="panel-toolbar"><h2 id="timeline-title">발표에서 수집까지</h2><span class="small muted">2026-10-10 · UTC · 가상 시각</span></header>
    <div class="timeline-axis"><span>13:10</span><span>13:20</span><span>13:30</span><span>13:40</span><span>13:50</span><span>14:00</span></div>
    <div class="timeline-lanes">
      ${sources.map((source, index) => `<div class="timeline-lane"><span>${source.id} · ${source.language}</span><div class="lane-track"><button type="button" data-evidence="${source.id}" class="timeline-point" style="left:${[0, 20, 30, 40][index]}%" aria-label="${source.id} ${source.published} 게시 근거 확인"><i></i><small>${source.published.replace(" UTC", "")}</small></button><span class="collection-tick" style="left:60%" aria-hidden="true"></span></div></div>`).join("")}
    </div><div class="timeline-foot"><span>● 출처별 게시 시각</span><span>│ 13:40 수집</span><span>14:00 예정 시작 · 관측 아님</span></div>
  </section>`;
}

// Fusion 분석: 수집 조건 한 줄 · 수집 문서 요약 · 기관 소재지 지도 · 주요 이슈(Wikipedia) · 출처 근거는 fusion.js(FusionScreen)가 그린다.
function analysisScreen() {
  if (!demonstration) return window.ScenarioLive.shellHtml("analysis");
  return `${collectionSummaryHtml({ compact: true })}${FusionScreen.html()}`;
}

const quotes = {
  S1: {
    language: "중국어 간체",
    institution: "가상 발사 운용기관 · 중국 소재",
    original:
      "模拟公告：2026-10-10，L1区域限制开始时间为北京时间22:00，结束时间为北京时间22:40。本次试验用于验证运载技术。",
    translation:
      "가상 공지: 2026-10-10 L1 구역의 통제는 베이징시간 22:00에 시작해 22:40에 종료된다. 이번 시험은 발사 기술 검증을 위한 것이다.",
    local: "22:40 · 베이징시간",
    normalized: "14:40 UTC",
    perspective: "발사 기술 검증을 위한 시험",
    regional: "시험 구역 L1의 진입 제한 공지",
    regionalState: "공지된 제한 · 실제 시행 관측과 별개",
  },
  S2: {
    language: "중국어 번체",
    institution: "가상 항공 관제기관 · 대만 소재",
    original:
      "模擬公告：2026-10-10，L1區域限制自22:00至22:20（UTC+8）。建議留意周邊空域安全；本轄區航線延誤尚未確認。",
    translation:
      "가상 공지: 2026-10-10 L1 구역의 통제는 22:00부터 22:20까지다(UTC+8). 주변 공역 안전에 유의할 것을 권고하며, 관할 항로의 지연은 아직 확인되지 않았다.",
    local: "22:20 · UTC+8",
    normalized: "14:20 UTC",
    perspective: "주변 공역 안전에 유의할 필요",
    regional: "관할 항로의 지연은 미확인",
    regionalState: "미확인 · 지연이 없다는 뜻은 아님",
  },
  S3: {
    language: "일본어",
    institution: "가상 운항기관 · 일본 소재",
    original:
      "架空の通知：2026-10-10、L1区域の制限開始は23:00 JSTです。当機関が運航する1路線で迂回を実施しました。",
    translation:
      "가상 안내: 2026-10-10 L1 구역의 통제 시작은 23:00 JST다. 해당 기관이 운항하는 한 개 항로에서 우회를 시행했다.",
    local: "23:00 · JST",
    normalized: "14:00 UTC",
    perspective: "별도 평가 문장 미기재",
    regional: "해당 기관이 운항하는 1개 항로의 우회 시행 보고",
    regionalState: "기관의 시행 보고 · 독립 관측 검증은 별도",
  },
  S4: {
    language: "영어",
    institution: "S1 공지의 영문 번역 · 같은 원출처",
    original:
      "Synthetic translation: on 2026-10-10 restrictions in area L1 start at 22:00 Beijing time and end at 22:40 Beijing time. The test is intended to validate launch technology.",
    translation:
      "가상 번역: 2026-10-10 L1 구역의 통제는 베이징시간 22:00에 시작해 22:40에 끝난다. 시험은 발사 기술 검증을 목적으로 한다.",
    local: "22:40 · 베이징시간",
    normalized: "14:40 UTC",
    perspective: "S1의 기술 검증 목적 설명 번역",
    regional: "S1의 시험 구역 진입 제한 공지 번역",
    regionalState: "번역본 · 새 독립 근거 아님",
  },
};

function quoteHtml(id, kind = activeClaim) {
  const quote = quotes[id];
  const source = sources.find((source) => source.id === id);
  const included =
    relations[kind].sources.some((name) => name.startsWith(id + " ·")) ||
    id === "S4";
  const isStart = kind === "aligned";
  const local = isStart
    ? id === "S3"
      ? "23:00 · JST"
      : "22:00 · UTC+8"
    : quote.local;
  const extracted = !included
    ? "현재 비교 항목의 직접 주장 미기재"
    : kind === "perspective" || kind === "regional"
      ? quote[kind]
      : local;
  const compared = !included
    ? "이 출처의 전체 원문은 아래에서 확인"
    : kind === "perspective"
      ? "기관별 입장 병렬 보존"
      : kind === "regional"
        ? "다른 지역·항로는 별도 판단"
        : isStart
          ? "14:00 UTC"
          : quote.normalized;
  return `<div class="source-identity"><span class="eyebrow">${id} / ${quote.language}</span><h3>${source.institution}</h3><p>${source.place} 소재 · ${source.type}</p></div>
    <dl class="facts source-metadata"><div><dt>게시 / 수집 · 가상 UTC</dt><dd>${source.published} / 13:40</dd></div><div><dt>원출처 그룹</dt><dd>${source.group}${id === "S4" ? " · S1의 번역" : " · 독립성 별도 검토"}</dd></div></dl>
    <div class="extraction-block"><span class="small muted">선택한 비교 항목 · ${relations[kind].title}</span><strong>${extracted}</strong><p>${compared}</p></div>
    <details class="quote-section" open><summary>원문 인용 · 문단 P1</summary><blockquote lang="${id === "S3" ? "ja" : id === "S4" ? "en" : "zh"}">${quote.original}</blockquote></details>
    <details class="quote-section" open><summary>한국어 번역</summary><blockquote>${quote.translation}</blockquote></details>
    <p class="inspector-caution">${id === "S4" ? "S1과 같은 원출처입니다. 다른 언어라는 이유로 독립 근거를 추가하지 않습니다." : "인용의 존재는 내용의 진실성을 보증하지 않습니다. 원문과 번역·추출 정확성도 별도로 검토합니다."}</p>`;
}

function reportScreen() {
  if (!demonstration) return window.ScenarioLive.shellHtml("report");
  return `${collectionSummaryHtml({ compact: true })}
    <div class="report-workbench">
      <section class="document-column">
        <div class="document-toolbar"><span>REPORT / L1-001</span><span>수집 데이터 · 인쇄형 지면</span><button type="button" class="text-link" id="download-sample">보고서 내려받기 ↓</button></div>
        <article class="report-paper" aria-labelledby="document-title">
          <header class="paper-masthead"><span>겹눈<br><small>INTELLIGENCE BRIEF</small></span><span>APAC / L1-001<br>${new Date().toISOString().slice(0, 10)}</span></header>
          <div id="report-live"><p class="small muted">보고서를 불러오는 중…</p></div>
          <footer class="paper-footer"><span>fusion.py 결과 기반 / 실제 승인 미연동</span><span>01</span></footer>
        </article>
      </section>
      <aside class="report-tools">
        <header class="panel-toolbar"><h2>분석가 작업 도구</h2></header>
        <div class="report-tool-tabs" aria-label="보고서 도구 선택"><button type="button" data-report-tool="review" aria-pressed="false">검토 · 승인</button><button type="button" data-report-tool="evidence" aria-pressed="true">근거 시각화</button></div>
        <section id="report-review-panel" hidden>
          <p><span id="report-state" class="tag accent">검토 대기 · v1</span></p>
          <h3 id="report-review-head">판단 보류 항목을 확인하세요.</h3><p class="small muted">승인은 보고서 검토 기록이지 사실의 진위 보증이 아닙니다.</p>
          <form id="review-form">
            <div class="field"><label for="reviewer">검토자 · 자기 기입 / 인증 아님</label><input id="reviewer" value="시안 검토자" required></div>
            <div class="field"><label for="review-note">검토 의견 / 보류 사유</label><textarea id="review-note" rows="4" required minlength="3" placeholder="확인한 근거와 남은 한계를 적어 주세요."></textarea></div>
            <div class="review-buttons"><button class="button primary" type="submit" value="approve">승인 체험</button><button class="button" type="submit" value="hold">보류 체험</button></div>
          </form>
          <button class="text-link" id="revise-sample" type="button" style="margin-top:15px">항목 수정 → 초안 복귀 체험</button>
          <p id="review-feedback" class="feedback" role="status"></p><h3 class="section-rule">검토 기록</h3>
          <div id="sample-audit" class="audit"><p>새로고침하면 초기화됩니다. 실제 DB 저장·사용자 인증은 연결하지 않았습니다.</p></div>
        </section><section class="report-evidence-panel" id="report-evidence-panel"><div id="report-live-evidence"></div></section>
      </aside>
    </div>`;
}

function prototype() {
  if (embedded) document.body.classList.add("embed");
  app.innerHTML = `<div class="prototype-shell">
      <aside class="workspace-sidebar">
        <a class="sidebar-brand" href="storyboard.html" aria-label="겹눈 스토리보드">
          <img class="brand-mark" src="logo-gyeopnun.png" width="56" height="40" alt="">
          <span><strong>겹눈</strong><small>다국어 근거 분석</small></span>
        </a>
        <details class="screen-navigation" open>
          <summary>메뉴 <span>${selectedScreen.title}</span></summary>
          <nav class="screen-nav" aria-label="분석 메뉴">
            ${screens.map((screen) => `<a href="${screenUrl(screen.id, embedded)}" ${screen.id === selectedScreen.id ? 'aria-current="step"' : ""}>${sidebarIcon(screen.icon)}<span>${screen.title}</span></a>`).join("")}
          </nav>
        </details>
        <div class="sidebar-footer">
          <span class="sidebar-avatar" aria-hidden="true">${sidebarIcon("user-round")}</span><span>로컬 작업 공간<small>완료한 결과는 자동 저장</small></span>
        </div>
      </aside>
    <header class="prototype-header"><span id="header-context">다국어 근거 분석</span><span class="small muted">질문부터 보고서까지</span></header>
    <p class="prototype-notice" ${demonstration ? "" : "hidden"}>시연 데이터입니다.</p>
    <div class="prototype-body">
      <main id="main" class="screen"></main>
    </div></div>`;
  bindNavigation();
  renderScreen();
}

// 공통 프레임은 유지하고 본문만 바꿔 메뉴 전환 때 재로딩·위치 이동을 막는다.
function renderScreen() {
  const next = screens[screens.indexOf(selectedScreen) + 1];
  const renderers = {
    scope: liveCollectionHtml,
    analysis: analysisScreen,
    report: reportScreen,
  };
  const main = document.getElementById("main");
  main.className = `screen screen-${selectedScreen.id}`;
  main.innerHTML = `${renderers[selectedScreen.id]()}${
    selectedScreen.id === "scope" || !demonstration
      ? ""
      : `
    <footer class="screen-footer">
      <a class="button ${next ? "primary" : ""}" href="${next ? screenUrl(next.id, embedded) : "storyboard.html"}">${next ? "다음: " + next.title + " →" : "전체 흐름으로 돌아가기 ↗"}</a>
    </footer>`
  }`;
  main.scrollTop = 0;
  if (window.matchMedia("(max-width: 760px)").matches)
    document.querySelector(".screen-navigation").open = false;
  document.getElementById("header-context").textContent =
    {
      scope: "검색 / 질문 · 수집 조건",
      analysis: "검토 / 다국어 근거 분석",
      report: "보고서 / 확인 및 저장",
    }[selectedScreen.id] || "APAC / Evidence workspace";
  document.querySelector(".screen-navigation > summary span").textContent =
    selectedScreen.title;
  document.querySelectorAll(".screen-nav a").forEach((link) => {
    if (new URL(link.href).searchParams.get("screen") === selectedScreen.id)
      link.setAttribute("aria-current", "step");
    else link.removeAttribute("aria-current");
  });
  syncCollectionLinks();
  bindPrototypeEvents();
}

// 새 탭·새로고침·앞뒤 이동에서도 선택 조건을 유지하도록 내부 링크에 함께 싣는다.
function syncCollectionLinks() {
  document.querySelectorAll("#app a[href]").forEach((link) => {
    const url = new URL(link.href);
    if (
      url.origin !== window.location.origin ||
      url.pathname !== window.location.pathname ||
      !url.searchParams.has("screen")
    )
      return;
    setCollectionParams(url.searchParams);
    link.href = url.href;
  });
}

function navigateScreen(url, pushHistory) {
  const query = url.searchParams;
  const requested = query.get("screen");
  const screen = screens.find(
    (item) =>
      item.id === (legacyAnalysis.includes(requested) ? "analysis" : requested),
  );
  if (!screen) return false;
  selectedSourceTypes = readSelections(
    query,
    "sources",
    sourceOptions,
    defaultSourceTypes,
  );
  selectedLanguages = readSelections(
    query,
    "languages",
    languageOptions,
    defaultLanguages,
  );
  selectedTopic = readTopic(query);
  question = query.get("q") || selectedTopic.question;
  runId = query.get("run");
  selectedScreen = screen;
  if (["S1", "S2", "S3", "S4"].includes(query.get("source")))
    activeSource = query.get("source");
  if (
    ["aligned", "conflict", "perspective", "regional"].includes(
      query.get("claim"),
    )
  )
    activeClaim = query.get("claim");
  if (pushHistory) window.history.pushState(null, "", url.href);
  renderScreen();
  return true;
}

// 셸의 이벤트는 한 번만 등록한다. 교체되는 본문의 이벤트와 분리해 중복 실행을 막는다.
function bindNavigation() {
  // 좁은 화면에서는 메뉴를 접고, 넓은 화면에서는 왼쪽 메뉴를 항상 펼친다.
  const navigation = document.querySelector(".screen-navigation");
  const narrowScreen = window.matchMedia("(max-width: 760px)");
  function syncNavigation() {
    navigation.open = !narrowScreen.matches;
  }
  syncNavigation();
  narrowScreen.addEventListener("change", syncNavigation);
  app.addEventListener("click", (event) => {
    const link = event.target.closest("a[href]");
    if (
      !link ||
      event.defaultPrevented ||
      event.button !== 0 ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey ||
      link.target ||
      link.hasAttribute("download") ||
      (link.getAttribute("href") || "").startsWith("#")
    )
      return;
    const url = new URL(link.href);
    if (
      url.origin !== window.location.origin ||
      url.pathname !== window.location.pathname
    )
      return;
    if (!url.searchParams.has("screen")) return;
    // 같은 메뉴를 다시 누르면 본문·입력값·스크롤을 그대로 둔다.
    if (
      url.href === window.location.href ||
      (link.closest(".screen-nav") &&
        url.searchParams.get("screen") === selectedScreen.id)
    ) {
      event.preventDefault();
      return;
    }
    if (navigateScreen(url, true)) event.preventDefault();
  });
  window.addEventListener("popstate", () => {
    if (!navigateScreen(new URL(window.location.href), false))
      window.location.reload();
  });
}

// 화면 체험에 필요한 상태만 사용한다. 실제 검토 워크플로·수집기는 이 파일에 만들지 않는다.
function bindPrototypeEvents() {
  if (!demonstration) {
    window.ScenarioLive.mount(document.getElementById("main"), selectedScreen.id, {id: runId,
      onSelect: (id, input) => {
        runId = id;
        question = input.question;
        selectedLanguages = input.languages.map(lang => lang === "zh" ? "zh-Hans" : lang);
        const url = new URL(window.location.href);
        if (id) url.searchParams.set("run", id);
        else url.searchParams.delete("run");
        url.searchParams.set("q", question);
        window.history.replaceState(null, "", url.href);
        syncCollectionLinks();
      }});
    return;
  }
  const liveCollection = document.getElementById("live-collection");
  // 시연: 질문이 미리 만든 주제(대만해협·인도·파키스탄)면 실제 수집 대신 그 캐시 결과로 Fusion 분석을 연다.
  // capture 단계에서 막아 CollectionLive의 submit(API 호출)까지 가지 않는다. 다른 질문은 그대로 실제 수집한다.
  liveCollection?.addEventListener(
    "submit",
    (event) => {
      const form = event.target;
      const typed = form.elements.namedItem("question").value.trim();
      const topic = topics.find(
        (item) => item.id === FusionScreen.topicFor(typed),
      );
      if (!topic) return;
      event.preventDefault();
      event.stopPropagation();
      selectedTopic = topic;
      question = typed;
      runId = null;
      selectedLanguages = [
        ...form.querySelectorAll('input[name="live-language"]:checked'),
      ].map((input) => input.value);
      navigateScreen(
        new URL(screenUrl("analysis", embedded), window.location.href),
        true,
      );
    },
    true,
  );
  window.CollectionLive?.mount(liveCollection);
  document.querySelectorAll("[data-source-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      document
        .querySelectorAll("[data-source-filter]")
        .forEach((item) =>
          item.setAttribute("aria-pressed", String(item === button)),
        );
      document.querySelectorAll("[data-source-place]").forEach((row) => {
        row.hidden =
          button.dataset.sourceFilter !== "전체" &&
          row.dataset.sourcePlace !== button.dataset.sourceFilter;
      });
    });
  });
  document.querySelectorAll("[data-claim]").forEach((button) => {
    button.addEventListener("click", () => {
      activeClaim = button.dataset.claim;
      document
        .querySelectorAll("[data-claim]")
        .forEach((item) =>
          item.setAttribute("aria-pressed", String(item === button)),
        );
      document.getElementById("claim-detail").innerHTML =
        relationHtml(activeClaim);
      const detail = document.getElementById("quote-detail");
      if (detail) detail.innerHTML = quoteHtml(activeSource);
    });
  });
  function selectQuote(id) {
    activeSource = id;
    document
      .querySelectorAll("[data-quote], [data-map-source]")
      .forEach((button) => {
        button.setAttribute(
          "aria-pressed",
          String((button.dataset.quote || button.dataset.mapSource) === id),
        );
      });
    document.getElementById("quote-detail").innerHTML = quoteHtml(id);
  }
  // 지도, 타임라인, 주장 카드가 모두 동일한 상세 패널을 갱신한다.
  document.getElementById("main").onclick = (event) => {
    const button = event.target.closest("[data-evidence]");
    if (button && document.querySelector(".fusion-screen"))
      return FusionScreen.selectSource(button.dataset.evidence, {
        openDrawer: true,
      });
    if (!button || !document.getElementById("quote-detail")) return;
    selectQuote(button.dataset.evidence);
    if (window.matchMedia("(max-width: 760px)").matches) {
      document
        .querySelector(".evidence-inspector")
        .scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };
  document.querySelectorAll("[data-quote]").forEach((button) => {
    button.addEventListener("click", () => selectQuote(button.dataset.quote));
  });
  const topic = {
    id: selectedTopic.id,
    label: runId ? "검색·수집 결과" : selectedTopic.label,
    question,
    run: runId,
  };
  if (document.querySelector(".fusion-screen")) FusionScreen.mount(topic);
  if (document.getElementById("report-live")) FusionScreen.mountReport(topic);
  document.querySelectorAll("[data-report-tool]").forEach((button) => {
    button.addEventListener("click", () => {
      document
        .querySelectorAll("[data-report-tool]")
        .forEach((item) =>
          item.setAttribute("aria-pressed", String(item === button)),
        );
      document.getElementById("report-review-panel").hidden =
        button.dataset.reportTool !== "review";
      document.getElementById("report-evidence-panel").hidden =
        button.dataset.reportTool !== "evidence";
    });
  });
  let version = 1;
  document
    .getElementById("review-form")
    ?.addEventListener("submit", (event) => {
      event.preventDefault();
      const reviewer = document.getElementById("reviewer").value.trim();
      const note = document.getElementById("review-note").value.trim();
      if (!reviewer || note.length < 3) {
        document.getElementById("review-feedback").textContent =
          "검토자와 구체적인 의견을 입력해 주세요.";
        return;
      }
      const action =
        event.submitter?.value === "approve" ? "승인 체험" : "보류 체험";
      version += 1;
      document.getElementById("report-state").textContent =
        action + " · v" + version;
      document.getElementById("review-feedback").textContent =
        "이 화면에서만 반영했습니다. 실제 승인·DB 저장은 수행하지 않습니다.";
      document
        .getElementById("sample-audit")
        .insertAdjacentHTML(
          "afterbegin",
          `<p>v${version} · ${escapeHtml(reviewer)} · ${action}<br>${escapeHtml(note)}</p>`,
        );
    });
  document.getElementById("revise-sample")?.addEventListener("click", () => {
    version += 1;
    document.getElementById("report-state").textContent =
      "검토 대기 · v" + version;
    document.getElementById("review-feedback").textContent =
      "항목 수정 후 초안으로 돌아가는 상태를 체험했습니다. 실제 자료는 변경하지 않았습니다.";
    document
      .getElementById("sample-audit")
      .insertAdjacentHTML(
        "afterbegin",
        `<p>v${version} · 항목 수정 체험 → 재승인 필요</p>`,
      );
  });
  document.getElementById("download-sample")?.addEventListener("click", () => {
    const text =
      FusionScreen.reportText() || "보고서를 아직 불러오지 못했습니다.";
    const url = URL.createObjectURL(
      new Blob([text], { type: "text/plain;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "겹눈-보고서.txt";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
}

if (selectedScreen) prototype();
else board();
