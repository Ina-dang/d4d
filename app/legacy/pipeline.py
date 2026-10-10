"""분석 순서를 연결하는 오케스트레이터. 호출·검증·저장은 각 모듈에 맡긴다."""

import asyncio
from collections.abc import Awaitable, Callable
from enum import IntEnum

from app.config import Settings
from app.core.errors import AnalysisError
from app.core.schemas import ClaimDraft, Report, Source, StepStatus
from app.core.storage import Store
from app.legacy.demo import fixtures
from app.legacy.providers import (
    SEARCH_RESULTS_LIMIT,
    Provider,
    balanced_candidates,
    make_source,
    safe_url,
)
from app.legacy.verification import crosscheck, validate_claims


class Stage(IntEnum):
    """저장된 진행 목록의 인덱스. 순서는 화면과 기존 보고서의 계약이다."""

    QUERY = 0
    SEARCH = 1
    COLLECT = 2
    EXTRACT = 3
    COMPARE = 4
    REPORT = 5


STAGES = ["언어별 검색어", "URL 검색", "원문 수집", "주장 추출", "교차 비교", "보고서 초안"]
StageUpdate = Callable[[Stage, StepStatus, str], Awaitable[None]]


def _append_claims(report: Report, source: Source, drafts: list[ClaimDraft]) -> None:
    """데모·실시간 모두 같은 인용 검사를 거쳐 주장과 제외 사유를 누적한다."""
    if report.plan is None:
        raise AnalysisError("주장을 검증할 검색 계획이 없습니다.")
    accepted, rejected = validate_claims(drafts, source, report.plan)
    report.claims.extend(accepted)
    report.warnings.extend(rejected)


async def _load_demo(report: Report, update: StageUpdate) -> None:
    """가상 자료만 적재한다. API 클라이언트를 만들거나 호출하지 않는다."""
    report.plan, report.sources, drafts = fixtures(report.created_at)
    report.warnings.extend(
        [
            "가상 데이터 데모: 검색·원문 수집·LLM 호출 없음. 실제 사건·항행 판단에 사용 금지.",
            "D4는 D1의 영문 번역본이며 같은 출처 그룹입니다. 독립 근거로 세지 않습니다.",
        ]
    )
    for stage in (Stage.QUERY, Stage.SEARCH, Stage.COLLECT, Stage.EXTRACT):
        await update(stage, "done", "고정 가상 자료 사용 / 외부 API 미호출")
    for source in report.sources:
        _append_claims(report, source, drafts[source.id])


async def _search_candidates(
    report: Report,
    settings: Settings,
    provider: Provider,
) -> dict[str, str]:
    """언어별 검색을 병렬 수행하고 중복 없는 허용 URL을 문서 예산 안에서 고른다."""
    if report.plan is None:
        raise AnalysisError("검색어를 생성하지 못했습니다.")
    results = await asyncio.gather(
        *(provider.search(query.query) for query in report.plan.queries),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, BaseException):
            report.warnings.append(f"일부 검색 실패 ({type(result).__name__})")
    candidates = balanced_candidates(results, settings.allowed_domains, settings.max_documents)
    if not candidates:
        raise AnalysisError("허용 출처 검색 결과 없음")
    return candidates


async def _collect_sources(
    report: Report,
    settings: Settings,
    provider: Provider,
    candidates: dict[str, str],
) -> int:
    """검색 요약 대신 본문을 확보한다. 중복·빈 본문은 제외하고 미확보 개수를 반환한다."""
    extracted = await provider.collect(list(candidates))
    collected_urls: set[str] = set()
    for item in extracted.get("results", []):
        url = safe_url(item.get("url", ""), settings.allowed_domains)
        body = item.get("raw_content")
        if url is None or url not in candidates or not isinstance(body, str) or not body.strip():
            continue
        if url in collected_urls:
            continue
        collected_urls.add(url)
        source = make_source(f"S{len(report.sources) + 1}", candidates[url], url, body, settings)
        report.sources.append(source)
        if source.truncated:
            report.warnings.append(
                f"{source.id}: 비용 제한으로 본문 일부만 분석. 원문 전체 판단 아님."
            )
    missing = len(candidates) - len(report.sources)
    if missing:
        report.warnings.append(f"URL {missing}개 원문 수집 실패 또는 빈 본문")
    if not report.sources:
        raise AnalysisError("수집 가능한 원문 없음")
    return missing


async def _extract_claims(report: Report, provider: Provider) -> int:
    """LLM 추출 결과를 원문과 대조하고 문서별 실패·언어 미확보를 남긴다."""
    if report.plan is None:
        raise AnalysisError("주장을 추출할 검색 계획이 없습니다.")
    results = await asyncio.gather(
        *(provider.claims(source, report.plan, report) for source in report.sources),
        return_exceptions=True,
    )
    failures = 0
    for source, result in zip(report.sources, results, strict=True):
        if isinstance(result, BaseException):
            failures += 1
            report.warnings.append(f"{source.id}: 주장 추출 실패 ({type(result).__name__})")
            continue
        source.language = result.language
        _append_claims(report, source, result.claims)
    missing_languages = set(report.languages) - {source.language for source in report.sources}
    if missing_languages:
        report.warnings.append(
            "요청 언어의 원문 미확보 또는 언어 식별 실패: " + ", ".join(sorted(missing_languages))
        )
    report.warnings.append(
        "언어는 모델 식별값입니다. 번역·사건 대응·출처 독립성은 분석가 확인이 필요합니다."
    )
    return failures


async def run_pipeline(report: Report, settings: Settings, store: Store) -> None:
    """데모 또는 검색→수집→추출을 실행한 뒤 공통 비교와 초안을 만든다."""
    provider: Provider | None = None

    async def update(stage: Stage, status: StepStatus, detail: str) -> None:
        report.steps[stage].status = status
        report.steps[stage].detail = detail
        await asyncio.to_thread(store.save, report)

    try:
        if report.mode == "demo":
            await _load_demo(report, update)
        else:
            provider = Provider(settings)
            await update(Stage.QUERY, "running", "질문을 단일 비교 항목과 언어별 검색어로 분해")
            report.plan = await provider.plan(report.question, report.languages, report)
            await update(
                Stage.QUERY,
                "done",
                f"검색어 {len(report.plan.queries)}개 / 항목 {len(report.plan.targets)}개",
            )

            await update(
                Stage.SEARCH,
                "running",
                f"허용 도메인 내 URL 검색 / 언어별 최대 {SEARCH_RESULTS_LIMIT}개",
            )
            candidates = await _search_candidates(report, settings, provider)
            await update(Stage.SEARCH, "done", f"중복 제거 후 원문 수집 대상 {len(candidates)}개")

            await update(Stage.COLLECT, "running", "검색 요약이 아닌 원문 본문 추출")
            missing = await _collect_sources(report, settings, provider, candidates)
            await update(
                Stage.COLLECT,
                "partial" if missing else "done",
                f"본문 확보 {len(report.sources)}/{len(candidates)}개",
            )

            await update(Stage.EXTRACT, "running", "원문·번역·표현 상태 추출 후 인용 구절 대조")
            failures = await _extract_claims(report, provider)
            await update(
                Stage.EXTRACT,
                "partial" if failures else "done",
                f"인용 검사를 통과한 주장 {len(report.claims)}개",
            )

        await update(
            Stage.COMPARE, "running", "사건·대상·표현 상태 확인 → 시간/단위 정규화 → 값 비교"
        )
        if report.plan is None:
            raise AnalysisError("비교할 검색 계획이 없습니다.")
        report.findings = crosscheck(report.plan, report.claims, report.sources)
        await update(
            Stage.COMPARE, "done", f"{len(report.findings)}개 항목 비교 / 서술형은 검토로 남김"
        )
        if not report.claims:
            raise AnalysisError("질문에 대응하는 검증 가능한 인용 근거 없음")
        report.status = "draft"
        await update(Stage.REPORT, "done", "근거 기반 템플릿 초안 생성. 분석가 검토 대기")
    except asyncio.CancelledError:
        report.mark_failed("실행 시간 제한 또는 서버 종료로 중단됨. 미완성 결과입니다.")
        await asyncio.to_thread(store.save, report)
        raise  # 작업 취소는 호출자까지 전달해야 서버 종료·시간 제한이 정상 동작한다.
    except Exception as exc:
        # SDK 오류에는 비밀정보가 섞일 수 있어 우리가 작성한 안내문만 공개한다.
        message = str(exc) if isinstance(exc, AnalysisError) else type(exc).__name__
        report.mark_failed(f"분석 미완료: {message}. 데모 결과로 자동 대체하지 않았습니다.")
        await asyncio.to_thread(store.save, report)
    finally:
        if provider is not None:
            await provider.close()
