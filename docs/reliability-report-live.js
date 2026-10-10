"use strict";

function attachReliabilityReport(parent, rid) {
  const box = document.createElement("section");
  const heading = document.createElement("h3");
  heading.textContent = "신뢰도 검증 · 근거 보고서";
  const file = document.createElement("input");
  file.type = "file";
  file.accept = ".json,application/json";
  file.setAttribute("aria-label", "신뢰도 함수의 반환 JSON");
  const uploaded = document.createElement("button");
  uploaded.type = "button";
  uploaded.textContent = "반환 JSON으로 보고서 작성";
  const local = document.createElement("button");
  local.type = "button";
  local.textContent = "로컬 신뢰도 함수 실행 · 보고서 작성";
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  const output = document.createElement("section");
  const endpoint = `/api/collections/${encodeURIComponent(rid)}/analysis`;
  box.append(heading, local, file, uploaded, status, output);
  parent.append(box);
  let busy = false, inputHash;

  function render(report) {
    output.replaceChildren();
    const comparisons = [];
    const evidence = new Map(report.evidence.map(claim => [claim.claim_id, claim]));
    const state = document.createElement("p");
    state.textContent = `보고서 ${report.status === "approved" ? "승인됨" : report.status === "held" ? "검토 보류" : "초안 · 사람 검토 필요"} · 버전 ${report.version}`;
    output.append(state);
    const titles = {key_judgment: "핵심 판단", common_facts: "공통 사실 주장",
      conflicting_candidates: "상충 후보", source_interpretations: "출처별 해석", analysis_limits: "분석의 한계"};
    Object.entries(titles).forEach(([key, title]) => {
      const section = document.createElement("section"), header = document.createElement("h4");
      header.textContent = title;
      section.append(header);
      const proposed = (report.proposed_comparisons || []).filter(item => item.section === key);
      if (!report.sections[key].length && !proposed.length) {
        const empty = document.createElement("p");
        empty.textContent = key === "common_facts" ? "현재 근거 문장에서는 같은 내용을 담은 주장 쌍을 찾지 못했습니다."
          : key === "conflicting_candidates" ? "현재 근거 문장에서는 같은 대상·시점·조건에서 충돌하는 주장 쌍을 찾지 못했습니다."
          : "판단할 근거가 충분하지 않습니다.";
        section.append(empty);
      }
      report.sections[key].forEach(item => {
        const text = document.createElement("p");
        text.textContent = `${item.text} ${item.claim_ids.map(id => `[${id}]`).join(" ")}`;
        section.append(text);
      });
      proposed.forEach(item => {
        const text = document.createElement("p");
        const label = key === "common_facts" ? "공통 내용 후보 · 원문 대조 전" : "상충 후보 · 판단 보류";
        text.textContent = `${label}: ${item.text} ${item.claim_ids.map(id => `[${id}]`).join(" ")}`;
        section.append(text);
        item.claim_ids.forEach(id => {
          const claim = evidence.get(id);
          if (!claim) return;
          const quote = document.createElement("p");
          quote.textContent = `[${id}] ${claim.source_name || claim.document_id} · 신뢰도 ${claim.reliability ?? "미평가"}: ${claim.translated_quote}`;
          section.append(quote);
        });
        const row = document.createElement("label"), choice = document.createElement("input");
        choice.type = "checkbox";
        choice.checked = false;
        const prompt = document.createElement("span");
        prompt.textContent = " 원문 대조 후 이 비교를 보고서에 반영";
        row.append(choice, prompt);
        section.append(row);
        comparisons.push({id: item.item_id, choice});
      });
      output.append(section);
    });
    const sources = document.createElement("details"), label = document.createElement("summary");
    label.textContent = "원문 인용 · 번역 · 반환 신뢰도";
    sources.append(label);
    report.evidence.forEach(claim => {
      const row = document.createElement("p");
      row.textContent = `${claim.claim_id} · ${claim.source_name || claim.title || claim.document_id} · 신뢰도 ${claim.reliability ?? "미평가"} · ${claim.label || "미평가"}\n번역: ${claim.translated_quote}\n원문: ${claim.original_quote}`;
      sources.append(row);
      if (/^https?:\/\//i.test(claim.url || "")) {
        const link = document.createElement("a");
        link.href = claim.url;
        link.textContent = "원문 열기";
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        sources.append(link);
      }
    });
    output.append(sources);
    report.warnings.forEach(message => {
      const warning = document.createElement("p");
      warning.textContent = message;
      output.append(warning);
    });
    if (report.excluded_statements?.length) {
      const held = document.createElement("details"), title = document.createElement("summary");
      title.textContent = `근거 검토에서 보류·제외한 문장 ${report.excluded_statements.length}개`;
      held.append(title);
      report.excluded_statements.forEach(item => {
        const text = document.createElement("p");
        text.textContent = `${item.text} · 보류 이유: ${item.reason}`;
        held.append(text);
      });
      output.append(held);
    }
    ["md", "json"].forEach(format => {
      const link = document.createElement("a");
      link.href = `${endpoint}/report/download?format=${format}`;
      link.textContent = `보고서 ${format.toUpperCase()} 내려받기 `;
      output.append(link);
    });
    const reviewer = document.createElement("input"), note = document.createElement("textarea");
    reviewer.placeholder = "검토자";
    reviewer.setAttribute("aria-label", "검토자");
    note.placeholder = "원문·번역·신뢰도 점수를 검토한 의견";
    note.setAttribute("aria-label", "검토 의견");
    output.append(reviewer, note);
    [["approve", "검토 후 승인"], ["hold", "검토 보류"], ["reopen", "초안으로 되돌리기"]].forEach(([action, title]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = title;
      button.addEventListener("click", () => {
        const body = {action, reviewer: reviewer.value || "", note: note.value || "", version: report.version};
        if (comparisons.length) body.comparison_decisions = Object.fromEntries(comparisons.map(item => [item.id, item.choice.checked]));
        return send(`${endpoint}/report/review`, body);
      });
      output.append(button);
    });
  }

  async function send(url, body) {
    if (busy) return;
    busy = true;
    local.disabled = uploaded.disabled = true;
    status.textContent = "처리 중입니다. 원문 근거와 반환 점수를 연결합니다.";
    status.setAttribute("role", "status");
    try {
      const response = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body || {})});
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "반환 JSON의 형식·점수를 확인하세요.");
      render(value);
      status.textContent = "처리가 완료됐습니다. 근거와 내용을 확인하세요.";
    } catch (error) {
      status.textContent = error.message;
      status.setAttribute("role", "alert");
    } finally {
      busy = false;
      local.disabled = uploaded.disabled = false;
    }
  }
  uploaded.addEventListener("click", async () => {
    try {
      if (!file.files?.length) throw new Error("신뢰도 함수가 반환한 JSON 파일을 선택하세요.");
      if (file.files[0].size > 2_000_000) throw new Error("반환 JSON은 2MB 이하로 선택하세요.");
      const reliabilityResult = JSON.parse(await file.files[0].text());
      await send(`${endpoint}/report`, {reliability_result: reliabilityResult,
        verification_input_sha256: inputHash || null});
    } catch (error) {
      status.textContent = error.message;
      status.setAttribute("role", "alert");
    }
  });
  local.addEventListener("click", () => send(`${endpoint}/verify-report`));
  fetch(`${endpoint}/report-input`).then(response => response.ok ? response.json() : null).then(value => {
    inputHash = value?.verification_input_sha256;
    if (value && !value.local_function_configured) {
      status.textContent = "로컬 함수의 파일·이름을 서버에 설정하면 자동 실행할 수 있습니다. 반환 JSON 파일로도 이어갈 수 있습니다.";
    }
  }).catch(() => { /* 생성 요청에서 서버가 현재 입력을 재검사한다. */ });
}
