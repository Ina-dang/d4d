"use strict";

window.ScenarioReport = (() => {
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const titles = {key_judgment: "핵심 판단", common_facts: "공통 사실 주장", conflicting_candidates: "상충 후보",
    source_interpretations: "출처별 해석", analysis_limits: "분석의 한계"};
  const drafts = new Map();
  const statusLabel = value => ({draft: "확인 대기", approved: "확인·저장 완료", held: "검토 보류"}[value] || value);

  function mount(root, rid, report) {
    const endpoint = `/api/collections/${encodeURIComponent(rid)}/analysis/report`;
    const sources = new Map(report.evidence.map((claim, index) => [claim.claim_id, {claim, label: `S${index + 1}`} ]));
    const refs = ids => ids.map(id => `<a class="report-ref" href="#evidence-${esc(id)}">[${esc(sources.get(id)?.label || id)}]</a>`).join(" ");
    const proposals = report.proposed_comparisons || [];
    root.innerHTML = `<div class="scenario-report-workbench"><article class="report-paper scenario-paper">
      <header class="paper-masthead"><span>겹눈 · 근거·신뢰도 보고서</span><span>${esc(statusLabel(report.status))} · v${report.version}</span></header>
      <h2>${esc(report.question)}</h2><p class="paper-subtitle">문서 ${report.docs?.length || new Set(report.evidence.map(c => c.document_id)).size}개 · 대표 주장 ${report.evidence.length}개</p>
      ${Object.entries(titles).map(([key, title]) => {
        const items = report.sections[key] || [], pending = proposals.filter(p => p.section === key);
        return `<section><h3>${title}</h3>${items.map(item => `<p>${esc(item.text)} ${refs(item.claim_ids)}</p>`).join("")}
          ${pending.map(item => `<div class="report-candidate"><p class="candidate-label">검토할 ${key === "common_facts" ? "공통 내용" : "상충"} 후보</p>
            <p>${esc(item.text)} ${refs(item.claim_ids)}</p></div>`).join("")}
          ${!items.length && !pending.length ? `<p class="report-empty">${key === "common_facts" ? "현재 근거에서는 공통 내용이 확인된 주장 쌍을 찾지 못했습니다."
            : key === "conflicting_candidates" ? "같은 대상·시점·조건에서 충돌하는 주장 쌍을 찾지 못했습니다." : "판단할 근거가 충분하지 않습니다."}</p>` : ""}</section>`;
      }).join("")}
      <section><h3>근거 문장과 신뢰도</h3>
      <div class="report-label-legend" aria-label="신뢰도 라벨 종류"><span>판정 라벨</span>
        ${["값 일치", "개연성 있음", "판단 보류"].map(label => `<span class="reliability-pill" data-label="${label}">${label}</span>`).join("")}</div>
      ${report.evidence.map(claim => {
        const source = sources.get(claim.claim_id);
        const url = /^https?:\/\//i.test(claim.url || "") ? claim.url : "";
        return `<details class="report-evidence" id="evidence-${esc(claim.claim_id)}"><summary><span class="report-source-name">[${source.label}] ${esc(claim.source_name || claim.document_id)}</span>
          <span class="reliability-pill" data-label="${esc(claim.label || "")}">${esc(claim.label || "라벨 미제공")}</span></summary>
          <p>${esc(claim.title || "")}</p><p><strong>번역</strong><br>${esc(claim.translated_quote)}</p><p lang="${esc(claim.language || "")}"><strong>원문</strong><br>${esc(claim.original_quote)}</p>
          ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">원문 열기 ↗</a>` : ""}</details>`;
      }).join("")}<p class="report-score-note">라벨은 신뢰도 함수의 판정입니다. 내용의 사실 여부를 확정하지 않으며 원문과 함께 검토해야 합니다.</p></section>
      <details class="report-process-notes"><summary>처리 기록과 추가 한계 ${report.warnings?.length || 0}건</summary>
        <ul>${(report.warnings || []).map(w => `<li>${esc(w)}</li>`).join("")}</ul></details>
      </article><aside class="scenario-review"><h2>확인 및 저장</h2>
        <p class="small muted">초안은 자동 저장됩니다. 원문과 비교 후보를 확인한 뒤 검토 기록을 남겨 주세요.</p>
        <form data-scenario-review>
          ${proposals.length ? `<fieldset><legend>비교 후보 ${proposals.length}건</legend><p class="small muted">각 후보를 보고서에 반영할지 선택해 주세요.</p>
            ${proposals.map((item, i) => `<div class="comparison-choice"><p>${i + 1}. ${esc(item.text)}</p>
              <label><input type="radio" name="comparison-${i}" value="include" required> 반영</label>
              <label><input type="radio" name="comparison-${i}" value="exclude" required> 제외</label></div>`).join("")}</fieldset>` : ""}
          <div class="field"><label for="scenario-reviewer">검토자</label><input id="scenario-reviewer" name="reviewer" required maxlength="80" autocomplete="name"></div>
          <div class="field"><label for="scenario-review-note">검토 의견</label><textarea id="scenario-review-note" name="note" required maxlength="2000" rows="3" placeholder="확인한 근거와 남은 의문을 적어 주세요."></textarea></div>
          <div class="review-buttons"><button class="button primary" type="submit" value="approve">확인 및 저장</button>
            <button class="button" type="submit" value="hold" formnovalidate>검토 보류</button></div>
          <p data-review-feedback role="status"></p></form>
        <div class="report-save-links">${window.ScenarioLive.reportDownloadHtml(rid, true, "review")}
          <a href="/api/collections/${encodeURIComponent(rid)}/download?format=collection" download>수집 원문(JSON) 저장 ↓</a></div>
        <details class="review-history"><summary>검토 기록 ${report.audit?.length || 0}건</summary>${(report.audit || []).map(a => `<p>${esc(a.reviewer)} · ${esc(statusLabel({approve: "approved", hold: "held", reopen: "draft"}[a.action]))}<br>${esc(a.note)}</p>`).join("")}</details>
      </aside></div>`;
    root.querySelectorAll('.report-ref').forEach(link => link.addEventListener('click', () => {
      const target = document.getElementById(link.getAttribute('href').slice(1));
      if (target) target.open = true;
    }));
    const form = root.querySelector('[data-scenario-review]'), feedback = root.querySelector('[data-review-feedback]');
    const draftKey = `${rid}:${report.version}`, draft = drafts.get(draftKey);
    if (draft) Object.entries(draft).forEach(([name, value]) => {
      const field = form.elements.namedItem(name); if (field) field.value = value;
    });
    form.addEventListener('input', () => drafts.set(draftKey, Object.fromEntries(new FormData(form))));
    let submitting = false;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (submitting) return;
      const data = new FormData(form), action = event.submitter?.value || 'approve';
      const reviewer = String(data.get('reviewer') || '').trim(), note = String(data.get('note') || '').trim();
      if (!reviewer || !note) { feedback.textContent = '검토자와 검토 의견을 입력해 주세요.'; return; }
      const decisions = {};
      proposals.forEach((p, i) => { const choice = data.get(`comparison-${i}`); if (choice) decisions[p.item_id] = choice === 'include'; });
      if (action === 'approve' && Object.keys(decisions).length !== proposals.length) { feedback.textContent = '모든 비교 후보의 반영·제외를 선택해 주세요.'; return; }
      submitting = true; form.querySelectorAll('button').forEach(b => { b.disabled = true; }); feedback.textContent = '검토 기록을 저장하고 있습니다.';
      try {
        const response = await fetch(`${endpoint}/review`, {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({action, reviewer, note, version: report.version, comparison_decisions: decisions})});
        const value = await response.json();
        if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '입력값을 확인해 주세요.');
        drafts.delete(draftKey); mount(root, rid, value);
        root.querySelector('[data-review-feedback]').textContent = action === 'approve' ? '확인한 보고서와 검토 기록을 저장했습니다.' : '검토 보류로 저장했습니다.';
      } catch (error) { feedback.textContent = error.message; }
      finally { submitting = false; form.querySelectorAll('button').forEach(b => { b.disabled = false; }); }
    });
  }
  return {mount};
})();
