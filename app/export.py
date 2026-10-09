"""원문·판단·검토 이력을 텍스트로 출력한다. 수집한 내용을 HTML로 실행하지 않는다."""

from .schemas import Report

STATUS = {
    "aligned": "값 일치",
    "conflict": "값 상충",
    "insufficient": "근거 부족",
    "not_comparable": "직접 비교 불가",
    "revision_review": "수정 공지 검토",
}
CONFIDENCE = {
    "medium": "중간",
    "low": "낮음",
    "unassessed": "평가 불가",
    "high": "높음 (사람 지정)",
}
REPORT_STATUS = {
    "running": "분석 중",
    "draft": "검토 대기",
    "failed": "분석 실패",
    "approved": "검토 승인",
    "held": "검토 보류",
}


def export_text(report: Report) -> str:
    """현재 보고서 버전과 미확정 사항을 포함한 내려받기용 텍스트를 만든다."""
    rows = [
        "SKYTRACE / 근거 검토 보고서",
        "=" * 40,
        f"모드: {'가상 데이터 데모' if report.mode == 'demo' else '공개 원문 분석'}",
        f"질문: {report.question}",
        f"상태: {REPORT_STATUS[report.status]} / 버전: {report.version}",
        f"생성: {report.created_at}",
        "",
        "주의: 신뢰도는 정답 확률이 아닌 근거 충족도입니다. 자동 평가는 최대 중간입니다.",
        "같은 도메인 그룹은 독립 근거로 중복 계산하지 않으나, 서로 다른 그룹도 독립성이 보장되지 않습니다.",
        "원문 대조는 인용 존재 확인이며, 모델 번역·추출 의미의 정확성을 보증하지 않습니다.",
        "",
    ]
    for finding in report.findings:
        rows += [
            f"[{finding.id}] {finding.label} / {STATUS[finding.status]}",
            f"근거 충족도: {CONFIDENCE[finding.confidence]}",
            finding.reason,
            f"인용 주장: {', '.join(finding.claim_ids) or '없음'}",
            f"검토 의견: {finding.review_note or '없음'}",
            "",
        ]
    for source in report.sources:
        rows += [
            f"[{source.id}] {source.title} ({source.language})",
            f"URL: {source.url or '없음: 가상 자료'}",
            f"출처 그룹: {source.publisher_group} / 독립성 미확인",
            f"수집: {source.collected_at} / 게시: {source.published_at or '미확인'}",
            f"원문 SHA256: {source.content_hash}",
            f"본문 잘림: {'있음' if source.truncated else '없음'}",
            "",
        ]
        for claim in (c for c in report.claims if c.source_id == source.id):
            rows += [
                f"  [{claim.id}] 문단 {claim.paragraph_id} / {claim.subject}",
                f"  원문: {claim.quote}",
                f"  한국어 번역: {claim.translation}",
                f"  표현: {claim.certainty}/{claim.quantifier}/{claim.polarity}",
                f"  값: {claim.value} / 정규화: {claim.normalized or '미확정'}",
                f"  정규화 근거: {claim.normalization_note}",
                "",
            ]
    rows += ["수집·분석 한계", *report.warnings, "", "검토 기록 (이름은 자기 기입; 인증 아님)"]
    for entry in report.audit:
        rows.append(f"v{entry.version} {entry.at} {entry.reviewer} / {entry.action} / {entry.note}")
    rows += [
        "",
        f"LLM 호출 {report.model_calls}, 입력 토큰 {report.input_tokens}, 출력 토큰 {report.output_tokens}",
        "토큰 사용량은 API 응답에서 확인된 값이며 비용 청구액과 같지 않습니다.",
    ]
    return "\n".join(rows)
