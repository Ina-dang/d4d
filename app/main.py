"""웹 화면과 API의 진입점. 분석은 pipeline, 저장은 storage에 맡긴다."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .collection_flow import CollectionFlow
from .config import Settings
from .demo import DEMO_QUESTION
from .export import export_text
from .pipeline import STAGES, run_pipeline
from .schemas import AuditEntry, FindingEdit, Report, ReviewRequest, RunRequest, Step
from .storage import Store, VersionConflict


def now() -> str:
    """저장·검토 이력에서 사용할 UTC 시각을 만든다."""
    return datetime.now(UTC).isoformat()


def _review_fields(body: FindingEdit | ReviewRequest) -> tuple[str, str]:
    """두 검토 API의 입력을 같은 규칙으로 확인하고 앞뒤 공백을 제거한다."""
    reviewer, note = body.reviewer.strip(), body.note.strip()
    if not reviewer or len(note) < 3:
        raise HTTPException(422, "검토자와 구체적인 검토 의견을 입력하세요.")
    return reviewer, note


def _append_audit(report: Report, reviewer: str, action: str, note: str) -> None:
    """저장소가 올릴 다음 버전에 맞춰 검토 이력을 추가한다."""
    report.audit.append(
        AuditEntry(
            at=now(),
            reviewer=reviewer,
            action=action,
            note=note,
            version=report.version + 1,
        )
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """실행 설정을 받아 앱을 만든다. 테스트는 임시 DB와 빈 API 키를 주입한다."""
    settings = settings or Settings()
    store = Store(settings.database)
    tasks: set[asyncio.Task[None]] = set()
    start_lock = asyncio.Lock()
    collections = CollectionFlow(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        for report in await asyncio.to_thread(store.recent):
            if report.status == "running":
                report.mark_failed("이전 서버 실행에서 중단된 작업입니다. 다시 실행해야 합니다.")
                await asyncio.to_thread(store.save, report)
        yield
        await collections.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="겹눈", lifespan=lifespan)
    app.state.store = store
    app.include_router(collections.router())
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def same_origin(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """다른 웹사이트의 변경 요청을 차단하고 로컬 화면의 보안 헤더를 설정한다."""
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected = urlsplit(str(request.base_url))
            if origin:
                actual = urlsplit(origin)
                if actual.scheme != expected.scheme or actual.netloc != expected.netloc:
                    return PlainTextResponse(
                        "다른 출처에서의 변경 요청은 허용하지 않습니다.", status_code=403
                    )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        if request.url.path.startswith('/storyboard/'):
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "font-src 'self' https://cdn.jsdelivr.net; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'self'; base-uri 'none'"
            )
        response.headers["Cache-Control"] = "no-store"
        return response

    def get_report(report_id: str) -> Report:
        report = store.get(report_id)
        if report is None:
            raise HTTPException(404, "보고서를 찾을 수 없습니다.")
        return report

    def mutate(report_id: str, version: int, change: Callable[[Report], None]) -> Report:
        """저장소의 변경 오류를 일관된 HTTP 응답으로 변환한다."""
        try:
            return store.mutate(report_id, version, change)
        except KeyError:
            raise HTTPException(404, "보고서 또는 항목을 찾을 수 없습니다.") from None
        except VersionConflict:
            raise HTTPException(
                409, "다른 검토가 저장되었습니다. 최신 버전을 불러와 다시 검토하세요."
            ) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get("/api/config")
    def config() -> dict[str, object]:
        return {
            "live_ready": settings.live_ready,
            "collection_ready": bool(settings.tavily_key),
            "ollama_model": settings.ollama_model,
            "model": settings.model,
            "max_documents": settings.max_documents,
            "max_document_chars": settings.max_document_chars,
            "allowed_domains": settings.allowed_domains,
            "demo_question": DEMO_QUESTION,
            "live_preset": "2026년 9월 20일 북한 미사일 발사의 시각과 비행거리 보도는 출처 간 일치하는가?",
        }

    @app.post("/api/runs", response_model=Report, status_code=202)
    async def create_run(body: RunRequest) -> Report:
        """실행 자리를 예약하고 즉시 반환한다. 이후 화면이 진행 상태를 조회한다."""
        # 빠른 거절용 검사이며, 동시 요청의 실제 예약은 아래 잠금 안에서 처리한다.
        if tasks:
            raise HTTPException(409, "한 번에 하나의 분석만 실행할 수 있습니다.")
        if body.mode == "live" and not settings.live_ready:
            raise HTTPException(503, "서버 .env에 OpenAI와 Tavily API 키를 설정해야 합니다.")
        if body.mode == "demo" and body.question != DEMO_QUESTION:
            raise HTTPException(
                422, "데모는 고정 가상 질문만 지원합니다. 임의 질문은 실시간 모드를 사용하세요."
            )
        report = Report(
            id=uuid4().hex,
            question=body.question,
            mode=body.mode,
            languages=list(dict.fromkeys(body.languages)),
            created_at=now(),
            steps=[Step(name=name) for name in STAGES],
        )

        async with start_lock:
            if tasks:
                raise HTTPException(409, "한 번에 하나의 분석만 실행할 수 있습니다.")
            await asyncio.to_thread(store.save, report)
            task = asyncio.create_task(
                asyncio.wait_for(run_pipeline(report, settings, store), timeout=210)
            )
            tasks.add(task)

        def completed(done: asyncio.Task[None]) -> None:
            tasks.discard(done)
            if not done.cancelled():
                done.exception()  # 예외를 회수하되 비밀정보가 섞일 수 있는 SDK 원문은 출력하지 않는다.

        task.add_done_callback(completed)
        return report

    @app.get("/api/runs")
    def recent() -> list[dict[str, str | int]]:
        return [
            {
                "id": r.id,
                "question": r.question,
                "mode": r.mode,
                "status": r.status,
                "version": r.version,
                "created_at": r.created_at,
            }
            for r in store.recent()
        ]

    @app.get("/api/runs/{report_id}", response_model=Report)
    def read_run(report_id: str) -> Report:
        return get_report(report_id)

    @app.patch("/api/runs/{report_id}/findings/{finding_id}", response_model=Report)
    def edit_finding(report_id: str, finding_id: str, body: FindingEdit) -> Report:
        """항목 검토를 저장한다. 승인된 보고서라도 수정하면 초안으로 돌아간다."""
        reviewer, note = _review_fields(body)

        def change(report: Report) -> None:
            finding = next((f for f in report.findings if f.id == finding_id), None)
            if finding is None:
                raise KeyError(finding_id)
            before = finding.confidence
            finding.confidence, finding.review_note = body.confidence, note
            report.status = "draft"
            _append_audit(
                report, reviewer, f"{finding.id} 근거 충족도 {before} → {body.confidence}", note
            )

        return mutate(report_id, body.expected_version, change)

    @app.post("/api/runs/{report_id}/review", response_model=Report)
    def review(report_id: str, body: ReviewRequest) -> Report:
        """보고서를 승인·보류하거나 초안으로 되돌리고 검토 이력을 남긴다."""
        reviewer, note = _review_fields(body)

        def change(report: Report) -> None:
            if not report.claims or not report.findings:
                raise ValueError("검토할 근거가 없습니다.")
            report.status = {"approve": "approved", "hold": "held", "reopen": "draft"}[body.action]
            _append_audit(report, reviewer, body.action, note)

        return mutate(report_id, body.expected_version, change)

    @app.get("/api/runs/{report_id}/export", response_class=PlainTextResponse)
    def download(report_id: str) -> PlainTextResponse:
        return PlainTextResponse(
            export_text(get_report(report_id)),
            headers={"Content-Disposition": f'attachment; filename="gyeopnun-{report_id}.txt"'},
        )

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static, check_dir=False), name="static")
    storyboard = Path(__file__).resolve().parent.parent / 'docs'
    app.mount('/storyboard', StaticFiles(directory=storyboard), name='storyboard')

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse('/storyboard/storyboard.html')

    @app.get('/app', include_in_schema=False)
    def analysis_app() -> FileResponse:
        return FileResponse(static / "index.html")

    return app


app = create_app()
