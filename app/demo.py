"""일치·상충·근거 부족·표현 차이를 시연하는 가상 자료. 실제 사건을 나타내지 않는다."""

from hashlib import sha256

from .schemas import ClaimDraft, Paragraph, SearchPlan, SearchQuery, Source, Target

DEMO_QUESTION = (
    "가상 발사체 시험의 통제구역 시작·종료 시각, 고도 제한과 항공 영향은 출처 간 일치하는가?"
)


def fixtures(now: str) -> tuple[SearchPlan, list[Source], dict[str, list[ClaimDraft]]]:
    """네 언어의 고정 원문과 주장을 반환한다. 네 문서 중 두 개는 같은 출처다."""
    plan = SearchPlan(
        event="가상 발사체 시험 / 실제 사건 아님",
        event_date="2026-10-10",
        queries=[
            SearchQuery(language="ko", query="가상 시험 통제구역"),
            SearchQuery(language="zh", query="模拟发射 空域限制"),
            SearchQuery(language="ja", query="架空打上げ 空域制限"),
        ],
        targets=[
            Target(id="start", label="통제 시작", subject="가상 시험 통제구역 시작"),
            Target(id="end", label="통제 종료", subject="가상 시험 통제구역 종료"),
            Target(id="altitude", label="고도 제한", subject="가상 시험 통제구역 고도"),
            Target(id="impact", label="항공 영향", subject="가상 시험 항공 영향"),
        ],
    )
    texts = {
        "D1": (
            "ko",
            "가상 한국어 공지",
            "demo-origin-a",
            [
                "가상 공지: 2026-10-10 통제구역 시작은 23:00 KST, 종료는 23:40 KST이다.",
                "가상 통제구역 상한은 FL200이다. 실제 항행에 사용하지 마시오.",
                "항공편 지연이 발생할 가능성이 있다. 지연 발생을 확인한 것은 아니다.",
            ],
        ),
        "D2": (
            "zh",
            "가상 중국어 보도",
            "demo-origin-b",
            [
                "模拟公告：2026-10-10 空域限制开始时间为北京时间22:00，结束时间为北京时间22:40。",
                "可能发生航班延误；目前尚未确认实际延误。",
            ],
        ),
        "D3": (
            "ja",
            "가상 일본어 공지",
            "demo-origin-c",
            [
                "架空の通知：2026-10-10、空域制限の開始は23:00 JST、終了は23:20 JST。",
                "航空便の遅延はまだ確認されていない。遅延がないという意味ではない。",
            ],
        ),
        "D4": (
            "en",
            "가상 한국어 공지의 영문 번역",
            "demo-origin-a",
            [
                "Synthetic translation: on 2026-10-10 restrictions start at 23:00 KST and end at 23:40 KST.",
            ],
        ),
    }
    sources, drafts = [], {}
    subjects = {t.id: t.subject for t in plan.targets}
    for sid, (language, title, group, paragraphs) in texts.items():
        sources.append(
            Source(
                id=sid,
                title=title,
                url=None,
                publisher_group=group,
                language=language,
                collected_at=now,
                content_hash=sha256("\n".join(paragraphs).encode()).hexdigest(),
                paragraphs=[
                    Paragraph(id=f"{sid}-P{i + 1}", text=p) for i, p in enumerate(paragraphs)
                ],
                is_demo=True,
            )
        )
        drafts[sid] = []
        start = "22:00" if language == "zh" else "23:00"
        end = {"ko": "23:40", "zh": "22:40", "ja": "23:20", "en": "23:40"}[language]
        tz = {"ko": "KST", "zh": "Asia/Shanghai", "ja": "JST", "en": "KST"}[language]
        for target, clock in [("start", start), ("end", end)]:
            drafts[sid].append(
                ClaimDraft(
                    target_id=target,
                    matches_event=True,
                    event_date="2026-10-10",
                    subject=subjects[target],
                    value=f"{clock} {tz}",
                    value_number=None,
                    unit=None,
                    time_local=clock,
                    timezone=tz,
                    certainty="reported",
                    quantifier="exact",
                    polarity="positive",
                    attribution=title,
                    paragraph_id=f"{sid}-P1",
                    quote=paragraphs[0],
                    translation=f"가상 통제 시작 {start}, 종료 {end} ({tz}).",
                    revision_note=None,
                )
            )
        if language == "ko":
            drafts[sid].append(
                ClaimDraft(
                    target_id="altitude",
                    matches_event=True,
                    event_date="2026-10-10",
                    subject=subjects["altitude"],
                    value="FL200",
                    value_number=200,
                    unit="fl",
                    time_local=None,
                    timezone=None,
                    certainty="reported",
                    quantifier="exact",
                    polarity="positive",
                    attribution=title,
                    paragraph_id=f"{sid}-P2",
                    quote=paragraphs[1],
                    translation=paragraphs[1],
                    revision_note=None,
                )
            )
        if language != "en":
            index = 2 if language == "ko" else 1
            drafts[sid].append(
                ClaimDraft(
                    target_id="impact",
                    matches_event=True,
                    event_date="2026-10-10",
                    subject=subjects["impact"],
                    value="지연 미확인" if language == "ja" else "지연 가능성",
                    value_number=None,
                    unit=None,
                    time_local=None,
                    timezone=None,
                    certainty="unconfirmed" if language == "ja" else "possible",
                    quantifier="exact",
                    polarity="unknown",
                    attribution=title,
                    paragraph_id=f"{sid}-P{index + 1}",
                    quote=paragraphs[index],
                    translation="지연은 아직 확인되지 않았다. 지연이 없다는 뜻은 아니다."
                    if language == "ja"
                    else "지연이 발생할 가능성이 있지만 실제 발생은 확인되지 않았다.",
                    revision_note=None,
                )
            )
    return plan, sources, drafts
