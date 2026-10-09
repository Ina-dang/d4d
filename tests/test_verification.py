import pytest

from app.demo import fixtures
from app.schemas import ClaimDraft
from app.verification import crosscheck, normalize_claim, validate_claims


@pytest.fixture
def corpus():
    return fixtures("2026-10-09T00:00:00+00:00")


def accepted(corpus):
    plan, sources, drafts = corpus
    claims = []
    for source in sources:
        good, bad = validate_claims(drafts[source.id], source, plan)
        assert not bad
        claims.extend(good)
    return claims


def test_demo_outcomes_and_duplicate_group(corpus):
    plan, sources, _ = corpus
    findings = crosscheck(plan, accepted(corpus), sources)
    assert [f.status for f in findings] == ["aligned", "conflict", "insufficient", "not_comparable"]
    assert findings[0].publisher_groups == 3  # 언어는 네 개지만 출처 그룹은 세 개다.
    assert findings[0].confidence == "medium"
    assert findings[2].confidence == "low"


def test_single_origin_is_not_independent(corpus):
    plan, sources, _ = corpus
    claims = [c for c in accepted(corpus) if c.source_id in {"D1", "D4"}]
    finding = crosscheck(plan, claims, sources)[0]
    assert finding.status == "aligned" and finding.confidence == "low"
    assert finding.publisher_groups == 1


@pytest.mark.parametrize(
    "update",
    [
        {"quote": "발표하지 않은 인용문"},
        {"paragraph_id": "invented"},
        {"matches_event": False},
        {"target_id": "invented"},
        {"time_local": "19:59"},
    ],
)
def test_unanchored_claim_rejected(corpus, update):
    plan, sources, drafts = corpus
    draft = drafts["D1"][0].model_copy(update=update)
    good, bad = validate_claims([draft], sources[0], plan)
    assert not good and bad


def test_missing_timezone_is_not_inferred(corpus):
    _, _, drafts = corpus
    draft = drafts["D1"][0].model_copy(update={"timezone": None})
    normalized, _ = normalize_claim(draft, draft.quote)
    assert normalized is None


def test_timezone_marker_required(corpus):
    _, _, drafts = corpus
    draft = drafts["D1"][0]
    assert normalize_claim(draft, draft.quote.replace("KST", ""))[0] is None


def test_utc_date_rollover(corpus):
    _, _, drafts = corpus
    draft = drafts["D1"][0].model_copy(update={"time_local": "01:00"})
    assert normalize_claim(draft, "2026-10-10 01:00 KST")[0] == "2026-10-09T16:00:00+00:00"


def test_invented_date_not_normalized(corpus):
    _, _, drafts = corpus
    draft = drafts["D1"][0].model_copy(update={"event_date": "2026-11-10"})
    assert normalize_claim(draft, draft.quote)[0] is None


def test_native_minutes_cannot_be_dropped(corpus):
    """원문의 15분을 무시한 정시 추출은 인용 검사에서 제외한다."""
    plan, sources, drafts = corpus
    quote = "2026-10-10 통제 시작은 23시 15분 KST이다."
    source = sources[0].model_copy(deep=True)
    source.paragraphs[0].text = quote
    draft = drafts["D1"][0].model_copy(update={"quote": quote, "time_local": "23:00"})
    good, bad = validate_claims([draft], source, plan)
    assert not good and bad


@pytest.mark.parametrize(
    ("clock", "time_local"),
    [
        ("23시", "23:00"),
        ("23시 00분", "23:00"),
        ("23시 15분", "23:15"),
        ("23時15分", "23:15"),
        ("23时15分", "23:15"),
        ("23：15", "23:15"),
    ],
)
def test_native_clock_preserves_minutes(corpus, clock, time_local):
    """정각 생략·한중일 시각 표기·전각 콜론을 원래 분 값으로 인정한다."""
    plan, sources, drafts = corpus
    quote = f"2026-10-10 통제 시작은 {clock} KST이다."
    source = sources[0].model_copy(deep=True)
    source.paragraphs[0].text = quote
    draft = drafts["D1"][0].model_copy(update={"quote": quote, "time_local": time_local})
    good, bad = validate_claims([draft], source, plan)
    assert len(good) == 1 and not bad
    assert good[0].normalized == f"2026-10-10T14:{time_local[3:]}:00+00:00"


def test_numeric_mismatch_rejected(corpus):
    plan, sources, drafts = corpus
    draft = drafts["D1"][2].model_copy(update={"value_number": 300})
    good, bad = validate_claims([draft], sources[0], plan)
    assert not good and bad


def test_unit_mismatch_rejected(corpus):
    plan, sources, drafts = corpus
    draft = drafts["D1"][2].model_copy(update={"unit": "km"})
    good, bad = validate_claims([draft], sources[0], plan)
    assert not good and bad


@pytest.mark.parametrize(
    "update",
    [
        {"event_date": "2026-10-11"},
        {"subject": "다른 시험"},
        {"certainty": "planned"},
        {"polarity": "negative"},
        {"quantifier": "approx"},
    ],
)
def test_different_context_not_conflict(corpus, update):
    plan, sources, _ = corpus
    claims = [c for c in accepted(corpus) if c.target_id == "start"]
    claims[0] = claims[0].model_copy(update=update)
    assert crosscheck(plan, claims, sources)[0].status == "not_comparable"


def test_revision_is_not_immediate_conflict(corpus):
    plan, sources, _ = corpus
    claims = accepted(corpus)
    claims[0] = claims[0].model_copy(update={"revision_note": "이전 공지 수정"})
    assert crosscheck(plan, claims, sources)[0].status == "revision_review"


def test_estimate_differences_not_conflict(corpus):
    plan, sources, _ = corpus
    claims = [c.model_copy(update={"quantifier": "approx"}) for c in accepted(corpus)]
    assert crosscheck(plan, claims, sources)[1].status == "not_comparable"


def test_incompatible_dimensions_not_conflict(corpus):
    plan, sources, _ = corpus
    claims = [c for c in accepted(corpus) if c.target_id == "start"]
    claims[0] = claims[0].model_copy(
        update={"time_local": None, "unit": "fl", "normalized": "200 fl"}
    )
    assert crosscheck(plan, claims, sources)[0].status == "not_comparable"


def test_schema_rejects_nan(corpus):
    _, _, drafts = corpus
    data = drafts["D1"][0].model_dump()
    data["value_number"] = float("nan")
    with pytest.raises(ValueError):
        ClaimDraft.model_validate(data)
