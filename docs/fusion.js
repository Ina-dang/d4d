"use strict";

/**
 * Fusion 분석 화면 (storyboard.js가 FusionScreen.html()로 뼈대를 넣고 FusionScreen.mount()로 그린다).
 *
 * 두 데이터는 서로 다른 출처라 연결하지 않는다.
 *  - 수집 문서(fusion-data/sources.json, frame 수집기 결과를 make_sources.py로 변환): 기관 소재지 지도, 수집 문서 요약 카드,
 *    오른쪽 출처 근거 패널. 지도 ↔ 출처 근거 ↔ 요약 카드가 "선택한 국가·문서" 상태를 함께 따른다.
 *  - 주요 이슈(issues/taiwan-strait.json, Wikipedia 조회수 급증일): 독립 패널. 수집 문서와 엮지 않는다.
 * CSP(script-src·connect-src 'self') 때문에 외부 라이브러리 없이 그리고, 지도 윤곽은 geo/east-asia-land.json을 쓴다.
 */
const FusionScreen = (() => {
  const DAY_MS = 86400000;
  // 국가 코드 → [경도, 위도, 이름]. 기관 소재지는 국가 수도 기준 개략 위치.
  const COUNTRIES = {
    CN: [116.40, 39.90, "중국"], TW: [121.56, 25.03, "대만"], HK: [114.17, 22.32, "홍콩"], JP: [139.69, 35.69, "일본"],
    KR: [126.98, 37.57, "한국"], KP: [125.75, 39.03, "북한"], IN: [77.21, 28.61, "인도"], PK: [73.05, 33.68, "파키스탄"],
    PH: [120.98, 14.60, "필리핀"], VN: [105.85, 21.03, "베트남"], SG: [103.82, 1.35, "싱가포르"], MY: [101.69, 3.14, "말레이시아"],
    ID: [106.85, -6.21, "인도네시아"], TH: [100.50, 13.76, "태국"], AU: [149.13, -35.28, "호주"], RU: [37.62, 55.75, "러시아"],
    US: [-77.04, 38.90, "미국"], CA: [-75.70, 45.42, "캐나다"], GB: [-0.13, 51.51, "영국"], FR: [2.35, 48.86, "프랑스"], DE: [13.40, 52.52, "독일"],
  };
  const REGION = {lonMin: 40, lonMax: 180, latMin: -45, latMax: 70};  // 이 밖의 나라는 범위 계산에서 빼고 가장자리에 "(지도 밖)"
  const MIN_SPAN = {lon: 25, lat: 15};
  const PAD_DEG = 4;

  // ---------- 도우미 ----------
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]);
  const grade = r => r == null ? "산정 불가" : r >= 0.7 ? "높음" : r >= 0.4 ? "보통" : "낮음";
  const NO_COORD_NAMES = {GLOBAL: "국가 미상", INTL: "국가 미상"};  // SNS 등을 임의로 국적에 배정하지 않는다.
  const countryName = code => COUNTRIES[code]?.[2] || NO_COORD_NAMES[code] || code || "국가 미상";
  const inRegion = ([lon, lat]) => lon >= REGION.lonMin && lon <= REGION.lonMax && lat >= REGION.latMin && lat <= REGION.latMax;
  function haversineKm([lon1, lat1], [lon2, lat2]) {
    const rad = Math.PI / 180, dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
    return 2 * 6371 * Math.asin(Math.sqrt(a));
  }
  async function loadJson(path) {
    try {
      const response = await fetch(path, {cache: "no-store"});
      if (response.ok) return {data: await response.json()};
    } catch (error) { /* 없거나 읽기 실패 */ }
    return {data: null, missing: true};
  }
  const overlap = (a, b) => Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) *
    Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
  // 원출처 그룹 수 = 재인용이 아닌 문서 수 (재인용 추정 문서는 원출처를 확인하지 못해도 독립 근거로 세지 않는다)
  const groupCount = list => list.filter(s => s.relation !== "reprint").length;

  // ---------- 상태 ----------
  const state = {sources: [], event: null, question: "", missing: false, land: null, issues: null,
    country: null, sourceId: null, showDistance: true, othersOpen: false, observers: []};
  const byId = id => state.sources.find(s => s.id === id);
  const filtered = () => state.country ? state.sources.filter(s => s.country === state.country) : state.sources;

  // ---------- 뼈대 ----------
  function html(legacyHtml = "") {
    return `<div class="fusion-screen">
      <section class="fx-summary" aria-label="수집 문서 요약">
        <article class="fx-card"><h3>국가별 수집 문서</h3><div id="fx-by-country"></div></article>
        <article class="fx-card"><h3>출처 묶음</h3><div id="fx-groups"></div></article>
        <article class="fx-card"><h3 id="fx-reliability-title">신뢰 가중치</h3><div id="fx-reliability"></div></article>
      </section>
      <div class="fusion-layout">
      <div class="fusion-main">
        <section class="geo-workspace fx-map-panel" aria-labelledby="fx-map-title">
          <header class="panel-toolbar"><div><h2 id="fx-map-title">기관 소재지 · 출처 관계</h2><p class="fx-sub" id="fx-map-sub"></p></div>
            <div class="fx-tools"><strong class="fx-count" id="fx-count"></strong><label class="fx-distance"><input type="checkbox" id="fx-distance" checked> 거리 표시</label></div></header>
          <div class="geo-stage fx-stage" id="fx-map"><svg class="geo-base" aria-hidden="true"></svg>
            <div class="map-legend fx-legend"><span><i></i>같은 질문의 수집 근거</span><span><i class="dashed"></i>재인용</span><span>원 크기 = 문서 수</span></div></div>
          <p class="map-disclaimer">국가 수도 기준 개략 위치 · 선은 근거 연결이며 이동 경로가 아닙니다 · 나라를 누르면 오른쪽에 그 나라 문서가 나옵니다.</p>
        </section>
        <section class="fx-issues-panel" aria-labelledby="fx-issues-title">
          <header class="fx-issues-head"><h2 id="fx-issues-title" class="fx-section-title">주요 이슈</h2>
            <span class="fx-badge" id="fx-issues-badge">Wikipedia 관심도 기준 · 수집 문서와 별개</span></header>
          <ol class="fx-issues" id="fx-issues"></ol>
        </section>
        ${legacyHtml}
      </div>
      <aside class="evidence-inspector fx-evidence" id="fx-evidence" aria-labelledby="fx-evidence-title">
        <header class="panel-toolbar"><h2 id="fx-evidence-title">출처 근거</h2><button type="button" class="fx-drawer-close" aria-label="출처 근거 닫기">✕</button></header>
        <div class="fx-filter" id="fx-filter"></div>
        <div class="fx-tabs" id="fx-tabs" role="tablist" aria-label="문서 선택"></div>
        <div id="fx-evidence-body" aria-live="polite"></div>
      </aside>
      <button type="button" class="fx-drawer-toggle" aria-controls="fx-evidence" aria-expanded="false"><svg class="sidebar-icon" aria-hidden="true"><use href="sidebar-icons.svg#panel-right"></use></svg>출처 근거</button>
    </div></div>`;
  }

  // ---------- 지도: 데이터에 맞춰 범위를 자동으로 정한다 ----------
  const mercY = lat => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
  function fitProjection(points, width, height, pad) {
    let lons = points.map(p => p[0]), lats = points.map(p => p[1]);
    let [lon0, lon1, lat0, lat1] = [Math.min(...lons) - PAD_DEG, Math.max(...lons) + PAD_DEG, Math.min(...lats) - PAD_DEG, Math.max(...lats) + PAD_DEG];
    if (lon1 - lon0 < MIN_SPAN.lon) { const c = (lon0 + lon1) / 2; [lon0, lon1] = [c - MIN_SPAN.lon / 2, c + MIN_SPAN.lon / 2]; }
    if (lat1 - lat0 < MIN_SPAN.lat) { const c = (lat0 + lat1) / 2; [lat0, lat1] = [c - MIN_SPAN.lat / 2, c + MIN_SPAN.lat / 2]; }
    const x0 = lon0 * Math.PI / 180, x1 = lon1 * Math.PI / 180, y0 = mercY(lat0), y1 = mercY(lat1);
    const k = Math.min((width - 2 * pad) / (x1 - x0), (height - 2 * pad) / (y1 - y0));  // 남는 축은 더 넓게 보인다
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    return ([lon, lat]) => [width / 2 + (lon * Math.PI / 180 - cx) * k, height / 2 - (mercY(lat) - cy) * k];
  }

  function countryGroups() {
    const groups = new Map();
    for (const s of state.sources) {
      const code = s.country || "INTL";
      if (!groups.has(code)) groups.set(code, []);
      groups.get(code).push(s);
    }
    return [...groups].map(([code, docs]) => ({code, docs, ll: COUNTRIES[code] ? COUNTRIES[code].slice(0, 2) : null}));
  }

  function renderMap() {
    const stage = document.getElementById("fx-map");
    if (!stage) return;
    const width = stage.clientWidth, height = stage.clientHeight, margin = 16;
    const groups = countryGroups();
    const eventLL = state.event && state.event.lon != null ? [state.event.lon, state.event.lat] : null;
    const regional = groups.filter(g => g.ll && inRegion(g.ll)).map(g => g.ll);
    const project = fitProjection([...regional, ...(eventLL ? [eventLL] : [])].concat(regional.length || eventLL ? [] : [[120, 30]]), width, height, 40);
    const countries = groups.filter(g => g.ll).length;
    document.getElementById("fx-count").textContent = `${state.sources.length}문서 / ${groupCount(state.sources)}원출처 그룹`;
    const noCoord = groups.filter(g => !g.ll).map(g => `${countryName(g.code)} ${g.docs.length}건`);
    document.getElementById("fx-map-sub").textContent = `${countries}개국${noCoord.length ? ` + ${noCoord.join(", ")}` : ""} · 수집 문서${state.missing ? " · 이 주제의 분석 결과 없음" : ""}`;

    const svg = stage.querySelector("svg");
    stage.querySelectorAll(".fx-node-label, .fx-callout").forEach(el => el.remove());
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const line = pts => pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join("");
    let grid = "";
    for (let lon = -180; lon <= 180; lon += 10) grid += line([project([lon, -70]), project([lon, 75])]);
    for (let lat = -60; lat <= 70; lat += 10) grid += line([project([-180, lat]), project([180, lat])]);
    const land = state.land ? state.land.rings.map(r => line(r.map(project)) + "Z").join("") : "";

    // 노드: 나라별 원 하나 (크기 = 문서 수). 범위 밖 나라는 방향 쪽 가장자리, 좌표 없는 문서는 왼쪽 위.
    const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    const nodes = groups.map(g => {
      const r = (10 + 3.2 * Math.sqrt(g.docs.length)) * (width < 560 ? 0.72 : 1);  // 좁은 화면은 원을 작게
      let x, y, outside = false;
      if (g.ll && inRegion(g.ll)) [x, y] = project(g.ll);
      else if (g.ll) {  // 서반구는 동쪽(태평양 건너), 유럽·아프리카는 서쪽 가장자리
        outside = true;
        x = g.ll[0] < -30 ? width - margin - r : margin + r;
        y = clamp(project([g.ll[0] < -30 ? 179 : REGION.lonMin, g.ll[1]])[1], margin + r, height - margin - r);
      } else [x, y] = [margin + r + 10, margin + r + 10];
      return {...g, r, x: clamp(x, margin + r, width - margin - r), y: clamp(y, margin + r, height - margin - r), outside};
    });
    for (let it = 0; it < 150; it++) for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j], dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 0.01, need = a.r + b.r + 10;
      if (d < need) { const p = (need - d) / 2; a.x -= dx / d * p; a.y -= dy / d * p; b.x += dx / d * p; b.y += dy / d * p; }
    }
    const hub = eventLL ? (() => { const [x, y] = project(eventLL); return {x, y}; })() : null;
    const nodeOf = code => nodes.find(n => n.code === code);

    // 선: 나라 → 질문의 사건 위치(실선), 재인용 문서의 나라 → 원출처 문서의 나라(점선)
    const edges = [];
    if (hub) for (const n of nodes) edges.push({from: n, kind: "event"});
    for (const s of state.sources) {
      const origin = s.relation === "reprint" && s.origin ? byId(s.origin) : null;
      if (origin && origin.country !== s.country && nodeOf(origin.country)) edges.push({from: nodeOf(s.country), to: nodeOf(origin.country), kind: "reprint"});
    }
    const sel = state.country;
    const edgeSvg = edges.map(e => {
      const to = e.to || hub;
      let km = "";
      if (state.showDistance && e.kind === "event" && e.from.code === sel && e.from.ll && eventLL) {
        km = `<text class="fx-km" x="${(e.from.x + to.x) / 2}" y="${(e.from.y + to.y) / 2 - 6}">${Math.round(haversineKm(e.from.ll, eventLL)).toLocaleString()}km</text>`;
      }
      return `<g class="fx-edge${sel && e.from.code !== sel && e.to?.code !== sel ? " is-dim" : ""}${e.from.code === sel ? " is-active" : ""}"><path class="graph-line${e.kind === "reprint" ? " duplicate-line" : ""}" d="M${e.from.x} ${e.from.y}L${to.x} ${to.y}"/>${km}</g>`;
    }).join("");
    const hubSvg = hub ? `<g class="fx-hub"><circle cx="${hub.x}" cy="${hub.y}" r="7"/><text x="${hub.x}" y="${hub.y + 22}">${esc(state.event.label || "사건 위치")}</text></g>` : "";
    const nodeSvg = nodes.map(n => `<g class="fx-node${sel && n.code !== sel ? " is-dim" : ""}${n.code === sel ? " is-active" : ""}" data-country="${esc(n.code)}"><circle cx="${n.x}" cy="${n.y}" r="${n.r}"/><text x="${n.x}" y="${n.y}">${n.docs.length}</text></g>`).join("");
    svg.innerHTML = `<rect width="${width}" height="${height}" fill="#0c151e"/><path class="map-grid" d="${grid}"/><path class="land" d="${land}"/>${edgeSvg}${hubSvg}${nodeSvg}`;

    // 나라 이름 라벨(HTML 버튼): 원 오른쪽·왼쪽·위·아래 중 다른 원·라벨·범례와 덜 겹치는 곳
    const stageBox = stage.getBoundingClientRect();
    const rectOf = el => { const r = el.getBoundingClientRect(); return {x: r.left - stageBox.left, y: r.top - stageBox.top, w: r.width, h: r.height}; };
    const obstacles = nodes.map(n => ({x: n.x - n.r - 2, y: n.y - n.r - 2, w: 2 * n.r + 4, h: 2 * n.r + 4}));
    obstacles.push(rectOf(stage.querySelector(".fx-legend")));
    svg.querySelectorAll(".fx-hub text, .fx-km").forEach(t => obstacles.push(rectOf(t)));
    const placed = [];
    for (const n of [...nodes].sort((a, b) => b.docs.length - a.docs.length)) {
      const name = countryName(n.code);
      stage.insertAdjacentHTML("beforeend", `<button type="button" class="fx-node-label${n.code === sel ? " is-active" : ""}${sel && n.code !== sel ? " is-dim" : ""}" data-country="${esc(n.code)}">${esc(name)}${n.outside ? '<small>지도 밖</small>' : ""}</button>`);
      const el = [...stage.querySelectorAll(".fx-node-label")].pop();
      const w = el.offsetWidth, h = el.offsetHeight, g = 6;
      const cands = [[n.x + n.r + g, n.y - h / 2], [n.x - n.r - g - w, n.y - h / 2], [n.x - w / 2, n.y - n.r - g - h], [n.x - w / 2, n.y + n.r + g]];
      const cost = (x, y) => {
        const box = {x, y, w, h};
        let c = 0;
        for (const o of obstacles) c += overlap(box, o) * 5;
        for (const p of placed) c += overlap(box, p) * 10;
        return c + (Math.max(0, 4 - x) + Math.max(0, x + w - width + 4) + Math.max(0, 4 - y) + Math.max(0, y + h - height + 4)) * 1000;
      };
      let best = null;
      cands.forEach(([x, y], k) => { const c = cost(x, y) + k; if (!best || c < best.c) best = {x, y, c}; });
      // 어디에 둬도 다른 원·라벨을 크게 가리면 이름을 숨긴다 (선택한 나라는 항상 표시). 이름은 아래 국가별 막대에도 있다.
      if (best.c > w * h * 0.25 && n.code !== sel) { el.remove(); continue; }
      placed.push({x: best.x, y: best.y, w, h});
      Object.assign(el.style, {left: `${best.x}px`, top: `${best.y}px`});
    }

    // 선택한 나라: 문서 구성 콜아웃 (분류·문자)
    const active = nodeOf(sel);
    if (active) {
      const count = (key) => Object.entries(active.docs.reduce((m, s) => ({...m, [s[key]]: (m[s[key]] || 0) + 1}), {})).map(([k, v]) => `${k} ${v}`).join(" · ");
      stage.insertAdjacentHTML("beforeend", `<div class="fx-callout" role="status"><strong>${esc(countryName(sel))} · ${active.docs.length}건</strong><span>${esc(count("role"))}</span><span>${esc(count("script"))}</span></div>`);
      const el = stage.querySelector(".fx-callout"), w = el.offsetWidth, h = el.offsetHeight;
      const x = active.x + active.r + 14 + w < width ? active.x + active.r + 14 : active.x - active.r - 14 - w;
      Object.assign(el.style, {left: `${clamp(x, 6, width - w - 6)}px`, top: `${clamp(active.y + active.r + 10, 6, height - h - 6)}px`});
    }
  }

  // ---------- 수집 문서 요약 (압축형 3열, 화면 상단) ----------
  // 국가 순위: 문서 수 내림차순 → 동점이면 TIE_PRIORITY 순(사건 당사국 + 분석가 소속국) → 가나다순
  const TIE_PRIORITY = ["CN", "TW", "JP", "KR"];
  const TOP_COUNTRIES = 3;
  const TIER_NAMES = {"1": "제3국 관측기관", "2": "당사국 공식", "3": "언론"};
  const LABELS = ["값 일치", "개연성 있음", "판단 보류"];  // fusion.py assign_label 순서
  const rankCountries = groups => [...groups].sort((a, b) => {
    if (b.docs.length !== a.docs.length) return b.docs.length - a.docs.length;
    const pa = TIE_PRIORITY.indexOf(a.code), pb = TIE_PRIORITY.indexOf(b.code);
    if (pa !== pb) return (pa < 0 ? Infinity : pa) - (pb < 0 ? Infinity : pb);
    return countryName(a.code).localeCompare(countryName(b.code), "ko");
  });

  function renderSummary() {
    const list = state.sources;
    const byBox = document.getElementById("fx-by-country");
    if (!byBox) return;
    if (!list.length) {
      for (const id of ["fx-by-country", "fx-groups", "fx-reliability"]) document.getElementById(id).innerHTML = '<p class="fx-empty-row">수집 문서가 없습니다.</p>';
      return;
    }
    const ranked = rankCountries(countryGroups());
    const max = Math.max(1, ...ranked.map(g => g.docs.length));
    const row = g => `<li><button type="button" data-country="${esc(g.code)}" aria-pressed="${g.code === state.country}">
        <span class="fx-bar-name">${esc(countryName(g.code))}</span><span class="fx-bar-track"><i style="width:${g.docs.length / max * 100}%"></i></span><span class="fx-bar-num">${g.docs.length}</span></button></li>`;
    const top = ranked.slice(0, TOP_COUNTRIES), rest = ranked.slice(TOP_COUNTRIES);
    const restDocs = rest.reduce((n, g) => n + g.docs.length, 0);
    byBox.innerHTML = `<ul class="fx-bars">${top.map(row).join("")}</ul>
      ${rest.length ? `<button type="button" class="fx-others" aria-expanded="${state.othersOpen}" title="${esc(rest.map(g => `${countryName(g.code)} ${g.docs.length}건`).join(" · "))}">기타 ${rest.length}개국 · ${restDocs}건 <span aria-hidden="true">${state.othersOpen ? "▴" : "▾"}</span></button>
        ${state.othersOpen ? `<ul class="fx-bars">${rest.map(row).join("")}</ul>` : ""}` : ""}`;

    const reprints = list.filter(s => s.relation === "reprint");
    const shown = reprints.slice(0, 2), more = reprints.length - shown.length;
    document.getElementById("fx-groups").innerHTML = `<p class="fx-big">${groupCount(list)}<small>개 그룹</small></p>
      <p class="fx-note">문서 ${list.length}건 중 재인용 추정 ${reprints.length}건 · 독립성은 별도 확인</p>
      ${reprints.length ? `<p class="fx-ids">${shown.map(s => `<button type="button" data-source="${esc(s.id)}" title="${esc(`${s.agency || ""} · 원출처: ${s.origin_label || s.origin || "미상"}`)}">${esc(s.id)}</button>`).join(", ")}${more ? ` 외 <button type="button" data-source="${esc(reprints[2].id)}">${more}건</button>` : ""} 보기 &gt;</p>` : ""}`;

    // fusion.py 결과(문서별 claims·라벨)가 있으면 셋째 카드는 주장 판정 분포
    const claims = list.flatMap(s => s.claims || []);
    if (state.live) {
      const scores = list.map(s => s.reliability).filter(Number.isFinite);
      document.getElementById("fx-reliability-title").textContent = "대표 주장 · 신뢰도";
      document.getElementById("fx-reliability").innerHTML = `<p class="fx-big">${claims.length}<small>개 주장</small></p>
        <p class="fx-note">${scores.length ? `반환 점수 ${Math.min(...scores).toFixed(3)}–${Math.max(...scores).toFixed(3)} · ${scores.length}문서` : "신뢰도 계산을 마치면 점수가 표시됩니다."}</p>
        <p class="fx-note">내용의 공통·상충 여부는 보고서에서 검토합니다.</p>`;
      return;
    }
    if (claims.length) {
      const counts = LABELS.map(l => [l, claims.filter(c => c.label === l).length]);
      document.getElementById("fx-reliability-title").textContent = `주장 판정 · ${claims.length}건`;
      document.getElementById("fx-reliability").innerHTML = `<ul class="fx-labels">${counts.map(([l, n]) =>
        `<li><span class="fx-label" data-label="${esc(l)}">${esc(l)}</span><span class="fx-bar-track"><i style="width:${n / claims.length * 100}%"></i></span><span class="fx-bar-num">${n}</span></li>`).join("")}</ul>
`;
      return;
    }
    const rel = list.map(s => s.reliability).filter(r => typeof r === "number");
    const avg = rel.length ? rel.reduce((a, b) => a + b, 0) / rel.length : null;
    const tiers = Object.entries(list.reduce((m, s) => { const t = s.tier || "-"; (m[t] ||= []).push(s); return m; }, {})).sort();
    document.getElementById("fx-reliability").innerHTML = `<p class="fx-big">${avg == null ? "—" : avg.toFixed(2)}<small>${grade(avg)}</small></p>
      <p class="fx-note">문서별 출처 티어 가중치의 평균</p>
      <p class="fx-tiers">${tiers.map(([t, docs]) => `<span title="Tier ${esc(t)} · ${esc(TIER_NAMES[t] || docs[0].role || "")}"><strong>T${esc(t)}</strong> ${docs[0].reliability ?? "—"} · ${docs.length}건</span>`).join("")}</p>`;
  }

  // ---------- 주요 이슈 (Wikipedia, 수집 문서와 별개) ----------
  function renderIssues() {
    const box = document.getElementById("fx-issues");
    if (!box) return;
    const issue = state.issues;
    if (!issue || !issue.jump_days?.length) { box.innerHTML = '<li class="fx-empty-row">Wikipedia 이슈 자료가 없습니다.</li>'; return; }
    const median = issue.median_views || 1;
    const top = [...issue.jump_days].sort((a, b) => b.views - a.views).slice(0, 5);
    document.getElementById("fx-issues-title").textContent = `주요 이슈 · ${issue.topic}`;
    document.getElementById("fx-issues-badge").textContent = `Wikipedia 관심도 기준${issue.views_since ? ` · 조회수 ${issue.views_since}부터` : ""} · 수집 문서와 별개`;
    box.innerHTML = top.map((d, i) => {
      const ratio = d.views / median, head = d.articles?.[0];
      return `<li class="fx-issue">
        <span class="fx-issue-rank">${i + 1}</span>
        <div class="fx-issue-when"><strong>${esc(d.date)}</strong><span>평소의 ${ratio >= 10 ? Math.round(ratio) : ratio.toFixed(1)}배</span></div>
        <div class="fx-issue-main">
          <div class="fx-keywords">${(d.keywords || []).map(k => `<span>${esc(k)}</span>`).join("")}</div>
          ${head ? `<a href="${esc(head.url)}" target="_blank" rel="noopener noreferrer">${esc(head.title)}</a><small> — ${esc(head.source)}</small>` : ""}
        </div></li>`;
    }).join("");
  }

  // ---------- 출처 근거 패널 ----------
  function renderEvidence() {
    const tabs = document.getElementById("fx-tabs"), body = document.getElementById("fx-evidence-body"), filter = document.getElementById("fx-filter");
    if (!tabs || !body) return;
    const list = filtered();
    if (!list.some(s => s.id === state.sourceId)) state.sourceId = list[0]?.id || null;
    filter.innerHTML = state.country
      ? `<span><strong>${esc(countryName(state.country))}</strong> 문서 ${list.length}건</span><button type="button" class="fx-link" data-country="">전체 ${state.sources.length}건 보기</button>`
      : `<span>전체 문서 ${list.length}건 · 지도에서 나라를 고르면 좁혀집니다</span>`;
    tabs.innerHTML = list.map(s => `<button type="button" role="tab" data-source="${esc(s.id)}" aria-selected="${s.id === state.sourceId}">${esc(s.id)}</button>`).join("");
    const s = byId(state.sourceId);
    if (!s) { body.innerHTML = '<p class="fx-empty-row">표시할 문서가 없습니다.</p>'; return; }
    const lang = {간체: "zh", 번체: "zh", 일본어: "ja", 영문: "en", 한국어: "ko"}[s.script] || "";
    const related = list.filter(o => o.id !== s.id);
    body.innerHTML = `<p class="fx-ev-agency">${esc(s.agency || "출처 미상")} · ${esc(countryName(s.country))}</p>
      <h3 class="fx-ev-title">${esc(s.title || s.id)}</h3>
      ${s.url ? `<a class="fx-link" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">원문 열기 ↗</a>` : ""}
      <dl class="fx-meta">
        <div><dt>ID</dt><dd>${esc(s.id)}</dd></div>
        <div><dt>유형</dt><dd>${esc(s.type || "-")}</dd></div>
        <div><dt>게시 시각</dt><dd>${s.published_at ? esc(String(s.published_at).replace("T", " ").replace("Z", " UTC")) : "미상"}</dd></div>
        ${s.weight != null ? `<div><dt>출처 가중치</dt><dd>${Number(s.weight).toFixed(2)}</dd></div>` : ""}
        <div><dt>신뢰도</dt><dd>${s.reliability == null ? "계산 전 또는 미평가" : `${Number(s.reliability).toFixed(3)}${state.live ? "" : ` · ${grade(s.reliability)}`}`}${s.tier ? ` <small>Tier ${esc(s.tier)}</small>` : ""}</dd></div>
      </dl>
      ${s.relation === "reprint" ? `<p class="fx-flag">재인용 추정 · 원출처: ${esc(s.origin ? `${s.origin} ${byId(s.origin)?.agency || ""}` : s.origin_label || "미상")}</p>` : ""}
      ${s.needs_review ? '<p class="fx-flag">관련도 낮음 · 검토 필요 (수집기 표시)</p>' : ""}
      ${s.claims ? `<h4 class="fx-h4">추출된 주장 <small>${s.claims.length}건 · 한국어 번역</small></h4>
      <ol class="fx-claims">${s.claims.map(c => `<li>${c.label ? `<span class="fx-label" data-label="${esc(c.label)}">${esc(c.label)}</span>` : ""}<p>${esc(c.quote)}</p></li>`).join("")}</ol>`
      : `<h4 class="fx-h4">원문 <small>${esc(s.script || "")}</small></h4>
      <div class="fx-original"${lang ? ` lang="${lang}"` : ""}>${esc(s.original_text || "원문 없음")}</div>
      <h4 class="fx-h4">번역 및 요약</h4>
      <p class="fx-note">${s.translation_ko ? esc(s.translation_ko) : "번역 없음 · 수집 단계에서는 번역하지 않습니다."}</p>`}
      ${s.sim ? `<h4 class="fx-h4">문서 간 유사도</h4><p class="fx-note">같은 주장이라는 판정이 아닌, 문서 분석 근거의 의미 유사도입니다.</p><ol class="fx-related">${Object.entries(s.sim).sort((a, b) => (b[1] ?? -2) - (a[1] ?? -2)).map(([id, score]) => {
        const other = state.sources.find(item => item.doc_id === id);
        return `<li><button type="button" data-source="${esc(other?.id || "")}"><strong>${esc(other?.id || id)}</strong><span>${esc(other?.agency || "출처")}</span><small>${Number.isFinite(score) ? score.toFixed(3) : "미계산"}</small></button></li>`;
      }).join("")}</ol>` : ""}
      ${related.length ? `<h4 class="fx-h4">같은 ${state.country ? "나라" : "질문"}의 다른 문서 <small>${related.length}건</small></h4>
        <ol class="fx-related">${related.slice(0, 8).map(o => `<li><button type="button" data-source="${esc(o.id)}"><strong>${esc(o.id)}</strong><span>${esc(o.agency || countryName(o.country))}</span><small>${esc(o.title || "")}</small></button></li>`).join("")}</ol>` : ""}`;
  }

  // ---------- 연동 (수집 문서 쪽만) ----------
  function selectCountry(code, {openDrawer = false} = {}) {
    state.country = code || null;
    state.sourceId = null;
    renderMap(); renderSummary(); renderEvidence();
    if (openDrawer) setDrawer(true);
  }
  function selectSource(id, {openDrawer = false} = {}) {
    const s = byId(id);
    if (!s) return;
    if (state.country && s.country !== state.country) { state.country = null; renderMap(); renderSummary(); }
    state.sourceId = id;
    renderEvidence();
    if (openDrawer) setDrawer(true);
  }
  function setDrawer(open) {
    if (open && !window.matchMedia("(max-width: 1180px)").matches) return;
    document.getElementById("fx-evidence")?.classList.toggle("is-open", open);
    document.querySelector(".fx-drawer-toggle")?.setAttribute("aria-expanded", String(open));
  }


  // ---------- 검색 화면의 실제 수집 실행(run) 결과 ----------
  // 수집 문서: GET /api/collections/{id} (output.by_country), 판정된 주장: GET /api/collections/{id}/analysis/report (evidence).
  // 보고서가 아직 없으면 문서만 보여 주고, 주장·판정 칸은 비워 둔다. make_sources.py와 같은 변환 규칙이다.
  const ROLE = {party_official: "당사국 공식", neutral_observer: "제3국 관측기관", reputable_media: "언론"};
  const TYPE = {party_official: "당사국 공식 발표", neutral_observer: "제3국 관측 자료", reputable_media: "언론 보도"};
  const SCRIPT = {ja: "일본어", en: "영문", ko: "한국어", hi: "힌디어", ur: "우르두어"};
  const scriptOf = (lang, country) => lang === "zh" ? (["TW", "HK"].includes(country) ? "번체" : "간체") : SCRIPT[lang] || lang || "";
  const truthy = value => ["true", "1", "yes"].includes(String(value).trim().toLowerCase());
  function runSources(job, report, analysis) {
    const docs = Object.entries(job?.output?.by_country || {})
      .flatMap(([group, list]) => (Array.isArray(list) ? list : []).map(d => ({...d, country: d.country || group})));
    const evidence = report?.evidence || analysis?.claims || [];
    const analyzed = new Map((analysis?.docs || report?.docs || []).map(d => [d.id, d]));
    return docs.map((d, i) => {
      const claims = evidence.filter(c => c.document_id === d.doc_id);
      const quoted = [null, undefined, "", "None", "null"].includes(d.quoted_source) ? null : d.quoted_source;
      return {id: `S${i + 1}`, doc_id: d.doc_id, title: d.title || "", url: d.url, agency: d.source_name, country: d.country || "INTL",
        role: ROLE[d.source_category] || d.source_category, type: TYPE[d.source_category] || d.source_category,
        script: scriptOf(d.language, d.country), tier: d.tier == null ? null : String(d.tier), published_at: d.published_date,
        relation: truthy(d.is_reprint_likely) ? "reprint" : "event", origin_label: quoted,
        reliability: claims[0]?.reliability ?? null, weight: analyzed.get(d.doc_id)?.weight ?? d.credibility_weight ?? null,
        sim: analyzed.get(d.doc_id)?.sim || null,
        original_text: String(d.text_snippet || d.article_text || "").slice(0, 1600),
        ...(claims.length ? {claims: claims.map(c => ({id: c.claim_id, quote: c.translated_quote, label: c.label, reliability: c.reliability}))} : {})};
    });
  }
  async function loadTopicData(topic) {
    if (!topic.run) return loadJson(`fusion-data/${topic.id}.json`);
    const base = `/api/collections/${encodeURIComponent(topic.run)}`;
    const [job, report, analysis] = await Promise.all([loadJson(base), loadJson(`${base}/analysis/report`),
      loadJson(`${base}/analysis/download?format=verification`)]);
    if (!job.data) return {data: null, missing: true};
    return {data: {question: report.data?.question || job.data.input?.question || "", sources: runSources(job.data, report.data, analysis.data)}};
  }
  // 질문 → 미리 만든 주제(fusion-data/<id>.json, issues/<id>.json). 시연 검색과 실제 수집의 Wikipedia 이슈 선택에 쓴다.
  const TOPIC_PATTERNS = [["india-pakistan", /인도|파키스탄|카슈미르|india|pakistan|kashmir/i], ["taiwan-strait", /대만|타이완|taiwan/i]];
  const topicFor = question => TOPIC_PATTERNS.find(([, re]) => re.test(question || ""))?.[0] || null;
  const issueTopic = (topic, question) => topic.run ? topicFor(question) : topic.id;

  async function mount(topic) {
    state.observers.forEach(o => o.disconnect());
    state.observers = [];
    const root = document.querySelector(".fusion-screen");
    if (!root) return;
    const [sources, land] = await Promise.all([loadTopicData(topic), loadJson("geo/east-asia-land.json")]);
    const issueId = issueTopic(topic, sources.data?.question);
    const issues = issueId ? await loadJson(`issues/${issueId}.json`) : {data: null};
    if (!document.body.contains(root)) return;
    Object.assign(state, {live: Boolean(topic.run), sources: sources.data?.sources || [], event: sources.data?.event || null, question: sources.data?.question || "",
      missing: Boolean(sources.missing), issues: issues.data, land: land.data, country: null, sourceId: null});

    root.addEventListener("click", event => {
      const t = event.target.closest("[data-country], [data-source], .fx-drawer-toggle, .fx-drawer-close, .fx-others");
      if (!t) return;
      if (t.classList.contains("fx-others")) { state.othersOpen = !state.othersOpen; return renderSummary(); }
      if (t.classList.contains("fx-drawer-toggle")) return setDrawer(!document.getElementById("fx-evidence").classList.contains("is-open"));
      if (t.classList.contains("fx-drawer-close")) return setDrawer(false);
      if (t.dataset.country !== undefined) {
        const code = t.dataset.country;
        return selectCountry(code && code === state.country ? null : code, {openDrawer: Boolean(code) && Boolean(t.closest("#fx-map, .fx-summary"))});
      }
      selectSource(t.dataset.source, {openDrawer: Boolean(t.closest(".fx-summary"))});
    });
    document.getElementById("fx-distance").addEventListener("change", e => { state.showDistance = e.target.checked; renderMap(); });

    renderSummary(); renderIssues(); renderEvidence();
    if (topic.run) root.querySelector('.fx-issues-panel').hidden = true;
    const wanted = new URLSearchParams(location.search).get("source");
    if (wanted && byId(wanted)) selectSource(wanted);
    let last = -1;
    const stage = document.getElementById("fx-map");
    const observer = new ResizeObserver(() => { if (stage.clientWidth !== last) { last = stage.clientWidth; renderMap(); } });
    observer.observe(stage);
    state.observers.push(observer);
  }


  // ---------- 보고서 (storyboard.js reportScreen이 #report-live 자리를 두면 같은 sources.json으로 채운다) ----------
  // 판정 기준값과 문서별 신뢰도 숫자는 보고서에 쓰지 않는다. 문장은 데이터에서 세어 만든 것이며 해석은 분석가가 붙인다.
  const REPORT_PICK = 3;
  const REPORT_SECTIONS = {
    "값 일치": "여러 출처가 같은 내용을 말하는 것으로 분류된 주장입니다. 발표·보도의 일치이며 사실의 독립 확인은 아닙니다.",
    "개연성 있음": "다른 출처와 내용이 상당 부분 겹쳐 사실일 개연성이 있는 주장입니다. 같은 값으로 확인된 것은 아니며 입장 대립을 검증한 결과도 아닙니다.",
    "판단 보류": "다른 출처와 비교할 근거가 부족한 주장입니다. 추가 수집 또는 원문 확인 전까지 결론에 쓰지 않습니다.",
  };
  let reportText = "";
  const sourceLink = id => `<a href="?screen=analysis&source=${esc(id)}">[${esc(id)}]</a>`;
  // 라벨마다 신뢰도 높은 주장부터 REPORT_PICK개, 서로 다른 문서를 먼저 채우고 모자라면 같은 문서에서 더
  function pickClaims(list) {
    const seen = new Set(), sorted = [...list].sort((a, b) => (b.reliability ?? -1) - (a.reliability ?? -1));
    const first = sorted.filter(c => !seen.has(c.source.id) && seen.add(c.source.id));
    return [...first, ...sorted.filter(c => !first.includes(c))].slice(0, REPORT_PICK);
  }

  async function mountReport(topic) {
    const paper = document.getElementById("report-live");
    if (!paper) return;
    const {data} = await loadTopicData(topic);
    const question = data?.question || topic.question;
    if (!document.body.contains(paper)) return;
    const sources = data?.sources || [];
    const claims = sources.flatMap(s => (s.claims || []).map(c => ({...c, source: s})));
    if (!claims.length) {
      paper.innerHTML = '<p class="fx-empty-row">이 주제의 분석 결과가 아직 없습니다. fusion.py 결과를 make_from_result.py로 변환해 주세요.</p>';
      return;
    }
    const byLabel = Object.fromEntries(LABELS.map(l => [l, claims.filter(c => c.label === l)]));
    const n = l => byLabel[l].length;
    const countries = rankCountries([...sources.reduce((m, s) => m.set(s.country, [...(m.get(s.country) || []), s]), new Map())]
      .map(([code, docs]) => ({code, docs})));
    const countryLine = countries.map(g => `${countryName(g.code)} ${g.docs.length}`).join(" · ");
    const lead = (n("값 일치")
      ? `주장 ${claims.length}건 중 ${n("값 일치")}건만 여러 출처에서 같은 내용으로 확인됩니다.`
      : `주장 ${claims.length}건 중 여러 출처에서 같은 내용으로 확인된 주장은 없습니다.`)
      + ` ${n("개연성 있음")}건은 개연성이 있으나 같은 값으로 확인되지 않았고, ${n("판단 보류")}건은 비교 근거가 부족합니다.`;
    const section = label => {
      const list = byLabel[label], shown = pickClaims(list);
      if (!list.length) return `<section><h3>${esc(label)} <em>0건</em></h3><p>해당 주장이 없습니다.</p></section>`;
      const docs = new Set(list.map(c => c.source.id)).size;
      return `<section><h3>${esc(label)} <em class="${label === "판단 보류" ? "paper-alert" : ""}">${list.length}건 · ${docs}문서</em></h3>
        <p>${REPORT_SECTIONS[label]}</p>
        <ul class="report-claims">${shown.map(c => `<li>“${esc(c.quote.length > 140 ? c.quote.slice(0, 140) + "…" : c.quote)}” <small>${esc(countryName(c.source.country))}</small> ${sourceLink(c.source.id)}</li>`).join("")}</ul>
        ${list.length > shown.length ? `<p class="small muted">외 ${list.length - shown.length}건은 Fusion 분석 화면의 출처 근거에서 확인합니다.</p>` : ""}</section>`;
    };
    const noAgency = sources.filter(s => !s.agency).length, noDate = sources.filter(s => !s.published_at).length;
    const noCountry = sources.filter(s => !COUNTRIES[s.country]).length;
    const limits = [
      noAgency && `${noAgency}문서는 기관명·제목·원문 링크가 없어 출처를 사람이 다시 확인해야 합니다.`,
      noDate && `${noDate}문서는 게시일이 없어 시간 순서를 비교하지 않았습니다.`,
      noCountry && `${noCountry}문서는 국가가 지정되지 않아 국가별 비교에서 한 묶음으로 다뤘습니다.`,
      "판정은 문서 간 유사도와 출처 가중치로 자동 분류한 결과이며, 문장 단위로 입장 대립을 검증하지 않았습니다.",
      "주장 문장은 한국어 번역본이며 원문 대조는 하지 않았습니다.",
    ].filter(Boolean);
    paper.innerHTML = `<h2 id="document-title">${esc(topic.label)}<br>다국어 수집 주장 비교</h2>
      <p class="paper-subtitle">${esc(countryLine)} / 문서 ${sources.length}건 · 주장 ${claims.length}건</p>
      <p class="paper-subtitle">질문: ${esc(question)}</p>
      <div class="paper-abstract"><strong>핵심 판단</strong><p>${esc(lead)}</p></div>
      ${LABELS.map(section).join("")}
      <section class="paper-limits"><h3>분석의 한계</h3><p>${limits.map(esc).join(" ")}</p></section>`;

    const reviewHead = document.getElementById("report-review-head");
    if (reviewHead) reviewHead.textContent = `판단 보류 ${n("판단 보류")}건을 확인하세요.`;
    const evidence = document.getElementById("report-live-evidence");
    const perDoc = s => LABELS.map(l => [l, (s.claims || []).filter(c => c.label === l).length]).filter(([, k]) => k).map(([l, k]) => `${l} ${k}`).join(" · ");
    if (evidence) evidence.innerHTML = `<h3>주장 판정 · ${claims.length}건</h3>
      <ul class="fx-labels">${LABELS.map(l => `<li><span class="fx-label" data-label="${esc(l)}">${esc(l)}</span><span class="fx-bar-track"><i style="width:${n(l) / claims.length * 100}%"></i></span><span class="fx-bar-num">${n(l)}</span></li>`).join("")}</ul>
      <h3 class="section-rule">국가별 문서</h3><p class="small muted">${esc(countryLine)}</p>
      <h3 class="section-rule">문서별 주장</h3><div class="report-source-list">${sources.map(s => `<a href="?screen=analysis&source=${esc(s.id)}"><span class="source-id">${esc(s.id)}</span><span>${esc(countryName(s.country))}<small>${esc(perDoc(s))}</small></span><span>↗</span></a>`).join("")}</div>`;

    reportText = [`겹눈 보고서 / ${topic.label} 다국어 수집 주장 비교`, `질문: ${question}`, `${countryLine} / 문서 ${sources.length}건 · 주장 ${claims.length}건`, `핵심 판단: ${lead}`,
      ...LABELS.flatMap(l => [`\n[${l}] ${n(l)}건`, ...pickClaims(byLabel[l]).map(c => `- ${c.quote} (${countryName(c.source.country)}, ${c.source.id})`)]),
      "\n[분석의 한계]", ...limits.map(t => `- ${t}`)].join("\n");
  }

  return {html, mount, selectSource, mountReport, reportText: () => reportText, runSources, topicFor};
})();
