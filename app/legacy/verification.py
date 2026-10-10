"""원문 근거를 확인하고 비교 조건이 같은 값만 보수적으로 대조한다.

인용 존재와 값 일치는 사실의 진위 또는 출처 독립성을 보증하지 않는다.
"""

import re
import unicodedata
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

from app.core.schemas import (
    MAX_CLAIMS_PER_SOURCE,
    Claim,
    ClaimDraft,
    Confidence,
    Finding,
    FindingStatus,
    SearchPlan,
    Source,
)

TIMEZONE_MARKERS = {
    "UTC": r"UTC|协调世界时|協調世界時|協定世界時",
    "KST": r"KST|한국\s*시간|한국\s*표준시",
    "JST": r"JST|日本時間|日本標準時",
    "Asia/Shanghai": r"北京时间|北京時間",
}
UTC_OFFSETS = {"UTC": 0, "KST": 9, "JST": 9, "Asia/Shanghai": 8}
UNIT_MARKERS = {
    "km": r"km|킬로미터|キロメートル|公里|千米",
    "m": r"(?<![a-z])m(?![a-z])|(?<!킬로)미터|(?<!キロ)メートル|(?<!千)米",
    "fl": r"FL\s*\d|비행\s*고도|フライトレベル",
    "count": r"개|회|발|건|枚|件|次|count",
    "minute": r"minute|분|分",
    "second": r"second|초|秒",
}


def comparable_text(text: str) -> str:
    """전각·공백 차이를 무시한다. 번역이나 의미 추론은 하지 않는다."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def _normalize_time(draft: ClaimDraft, quote: str) -> tuple[str | None, str]:
    if not draft.event_date or not draft.timezone:
        return None, "날짜 또는 시간대 미확인: UTC 변환하지 않음"
    if not re.search(TIMEZONE_MARKERS[draft.timezone], quote, re.I):
        return None, "근거 문단에서 명시적 시간대 표현을 확인하지 못함"
    try:
        local_date = date.fromisoformat(draft.event_date)
        y, m, d = local_date.year, local_date.month, local_date.day
        pattern = rf"{y}\s*(?:[-/.년年])\s*0?{m}\s*(?:[-/.월月])\s*0?{d}(?:일|日)?(?!\d)"
        if not re.search(pattern, unicodedata.normalize("NFKC", quote)):
            return None, "인용 구절에 사건의 전체 날짜가 명시되지 않아 날짜 추정 없이 비교 제외"
        if not draft.time_local or not re.fullmatch(r"\d{2}:\d{2}", draft.time_local):
            return None, "날짜·시각 형식 오류: 비교 제외"
        hour, minute = map(int, draft.time_local.split(":"))
        local = datetime(
            y,
            m,
            d,
            hour,
            minute,
            tzinfo=timezone(timedelta(hours=UTC_OFFSETS[draft.timezone])),
        )
    except ValueError:
        return None, "날짜·시각 형식 오류: 비교 제외"
    normalized = local.astimezone(UTC).isoformat()
    return normalized, f"{draft.time_local} {draft.timezone} → {normalized}"


def normalize_claim(draft: ClaimDraft, paragraph: str) -> tuple[str | None, str]:
    """시각은 UTC로, km는 m로 맞춘다. FL과 서술형은 임의 환산하지 않는다."""
    if draft.time_local:
        return _normalize_time(draft, paragraph)
    if draft.value_number is None:
        return None, "서술형 의미 비교는 자동 확정하지 않고 검토 대상으로 남김"
    value = Decimal(str(draft.value_number))
    unit = (draft.unit or "").lower().strip()
    if unit == "km":
        value *= 1000
        unit = "m"
    elif unit not in {"m", "fl", "count", "minute", "second"}:
        return None, "단위 기준 불명확: 숫자 비교 제외"
    return (
        f"{value.normalize()} {unit}",
        "명시된 동일 기준 단위로 비교; FL은 미터로 환산하지 않음",
    )


def _numeric_evidence_error(draft: ClaimDraft) -> str | None:
    if draft.value_number is None:
        return None
    text = unicodedata.normalize("NFKC", draft.quote)
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    if not any(Decimal(n) == Decimal(str(draft.value_number)) for n in numbers):
        return "근거 구절에서 숫자를 확인하지 못한 주장 제외"
    if draft.unit in UNIT_MARKERS and not re.search(UNIT_MARKERS[draft.unit], draft.quote, re.I):
        return "숫자 단위의 원문 근거 미확인 주장 제외"
    return None


def _quote_has_time(quote: str, time_local: str) -> bool:
    """23시 15분을 23:00의 근거로 잘못 인정하지 않도록 분까지 대조한다."""
    try:
        hour, minute = map(int, time_local.split(":"))
    except ValueError:
        return False
    # 정각의 '분' 생략은 허용하되 뒤에 다른 분 숫자가 있으면 거부한다.
    minutes = rf"0?{minute}\s*[분分]" if minute else r"(?:0?0\s*[분分])?(?!\s*\d)"
    clock = rf"(?<!\d)0?{hour}\s*(?:[:：]\s*{minute:02d}(?!\d)|[시時时]\s*{minutes})"
    return bool(re.search(clock, unicodedata.normalize("NFKC", quote)))


def validate_claims(
    drafts: list[ClaimDraft],
    source: Source,
    plan: SearchPlan,
) -> tuple[list[Claim], list[str]]:
    """사건·항목·인용·수치 근거를 검사한 뒤에만 비교용 주장을 만든다."""
    accepted: list[Claim] = []
    rejected: list[str] = []
    target_ids = {target.id for target in plan.targets}
    paragraphs = {p.id: p.text for p in source.paragraphs}
    for index, draft in enumerate(drafts[:MAX_CLAIMS_PER_SOURCE]):
        paragraph = paragraphs.get(draft.paragraph_id, "")
        if not draft.matches_event or draft.target_id not in target_ids:
            rejected.append(f"{source.id}: 질의 사건·비교 항목과 맞지 않는 주장 제외")
            continue
        if not paragraph or comparable_text(draft.quote) not in comparable_text(paragraph):
            rejected.append(f"{source.id}: 원문 근거 구절 불일치 주장 제외")
            continue
        numeric_error = _numeric_evidence_error(draft)
        if numeric_error:
            rejected.append(f"{source.id}: {numeric_error}")
            continue
        if draft.time_local and not _quote_has_time(draft.quote, draft.time_local):
            rejected.append(f"{source.id}: 인용에서 시각을 확인하지 못한 주장 제외")
            continue
        normalized, note = normalize_claim(draft, draft.quote)
        accepted.append(
            Claim(
                **draft.model_dump(),
                id=f"{source.id}-C{index + 1}",
                source_id=source.id,
                normalized=normalized,
                normalization_note=note,
            )
        )
    return accepted, rejected


def _assess_claims(entries: list[Claim], group_count: int) -> tuple[FindingStatus, Confidence, str]:
    """수정 공지 → 비교 조건 → 정규화 값 순서로 판단한다. 순서에 의미가 있다."""
    if not entries:
        return (
            "insufficient",
            "unassessed",
            "질문에 해당하는 원문 근거가 부족함. 미기재는 반박이 아님.",
        )
    if any(c.revision_note for c in entries):
        return (
            "revision_review",
            "low",
            "수정·대체 표현 존재. 이전/이후 공지를 연결하기 전에는 상충으로 단정하지 않음.",
        )
    if len(entries) < 2:
        return "insufficient", "low", "질문에 해당하는 원문 근거가 부족함. 미기재는 반박이 아님."
    dates = {c.event_date for c in entries}
    subjects = {comparable_text(c.subject) for c in entries}
    states = {(c.certainty, c.polarity, c.quantifier) for c in entries}
    if None in dates or len(dates) != 1 or len(subjects) != 1 or len(states) != 1:
        return (
            "not_comparable",
            "low",
            "사건 날짜·대상·예정/추정/부정·수량 표현이 달라 직접 비교 불가. 원문 검토 필요.",
        )
    dimensions = {"time" if c.time_local else ("m" if c.unit == "km" else c.unit) for c in entries}
    if any(c.normalized is None for c in entries) or len(dimensions) != 1:
        return (
            "not_comparable",
            "low",
            "서술형 의미 또는 시간대·단위가 확정되지 않아 자동 수치 비교하지 않음.",
        )
    if len({c.normalized for c in entries}) == 1:
        reason = "정규화한 값과 표현 상태가 일치함. 출처 간 독립성·진위는 사람이 추가 확인해야 함."
        if group_count == 1:
            reason += " 같은 출처 그룹의 번역·재인용이므로 독립 교차검증으로 세지 않음."
        return "aligned", "medium" if group_count >= 2 else "low", reason
    if entries[0].quantifier != "exact":
        return (
            "not_comparable",
            "low",
            "추정치·최소/최대 범위가 다름. 수치 차이를 곧바로 모순으로 판정하지 않음.",
        )
    return (
        "conflict",
        "low",
        "같은 날짜·대상·표현 상태에서 정규화 값이 다름. 수정 공지·관측 차이·추출 오류 검토 필요.",
    )


def crosscheck(plan: SearchPlan, claims: list[Claim], sources: list[Source]) -> list[Finding]:
    """항목별로 주장을 묶어 비교 결과를 만든다. 미기재는 반박으로 세지 않는다."""
    source_map = {source.id: source for source in sources}
    grouped: dict[str, list[Claim]] = defaultdict(list)
    for claim in claims:
        grouped[claim.target_id].append(claim)
    findings: list[Finding] = []
    for index, target in enumerate(plan.targets):
        entries = grouped[target.id]
        groups = {source_map[c.source_id].publisher_group for c in entries}
        status, confidence, reason = _assess_claims(entries, len(groups))
        findings.append(
            Finding(
                id=f"F{index + 1}",
                target_id=target.id,
                label=target.label,
                subject=target.subject,
                status=status,
                confidence=confidence,
                reason=reason,
                claim_ids=[c.id for c in entries],
                publisher_groups=len(groups),
            )
        )
    return findings
