"""API 대역으로 실시간 분석 경로를 검증한다. 유료 호출은 하지 않는다."""

import asyncio

from app.config import Settings
from app.core.schemas import Extraction, Report, Step
from app.core.storage import Store
from app.legacy.demo import fixtures
from app.legacy.pipeline import STAGES, run_pipeline


def test_live_orchestration_partial_and_dedup(tmp_path, monkeypatch):
    plan, sources, drafts = fixtures("2026-10-09T00:00:00+00:00")
    calls = []

    class FakeProvider:
        def __init__(self, settings):
            pass

        async def close(self):
            calls.append("close")

        async def plan(self, question, languages, report):
            assert languages == ["zh"]
            calls.append("plan")
            return plan

        async def search(self, query):
            calls.append("search")
            return [
                {"url": "https://mod.go.jp/demo", "title": "Test"},
                {"url": "http://127.0.0.1/secrets", "title": "Bad"},
                {"url": "https://reuters.com/missing", "title": "Missing"},
            ]

        async def collect(self, urls):
            calls.append("collect")
            assert len(urls) == 2  # 중복 URL과 허용되지 않은 로컬 URL은 제외한다.
            return {
                "results": [
                    {
                        "url": urls[0],
                        "raw_content": "\n\n".join(p.text for p in sources[0].paragraphs),
                    }
                ],
                "failed_results": [{"url": urls[1]}],
            }

        async def claims(self, source, plan, report):
            calls.append("claims")
            claims = [
                c.model_copy(update={"paragraph_id": c.paragraph_id.replace("D1", "S1")})
                for c in drafts["D1"]
            ]
            # 형식이 맞아도 원문에 없는 인용이면 모델 출력 이후 제외해야 한다.
            claims.append(claims[0].model_copy(update={"quote": "존재하지 않는 문구"}))
            return Extraction(language="ko", claims=claims)

    monkeypatch.setattr("app.legacy.pipeline.Provider", FakeProvider)
    settings = Settings(database=tmp_path / "live.sqlite3", openai_key="test", tavily_key="test")
    store = Store(settings.database)
    report = Report(
        id="live-test",
        question="테스트 사건 비교",
        mode="live",
        languages=["zh"],
        created_at="2026-10-09T00:00:00+00:00",
        steps=[Step(name=s) for s in STAGES],
    )
    asyncio.run(run_pipeline(report, settings, store))
    saved = store.get(report.id)
    assert saved.status == "draft" and len(saved.sources) == 1
    assert len(saved.claims) == 4 and saved.sources[0].language == "ko"
    assert saved.steps[2].status == "partial"
    assert any("원문 근거 구절 불일치" in w for w in saved.warnings)
    assert any("수집 실패" in w for w in saved.warnings)
    assert calls[0] == "plan" and calls[-1] == "close"
    assert calls.index("collect") < calls.index("claims")


def test_live_failure_does_not_fabricate_demo(tmp_path, monkeypatch):
    class BrokenProvider:
        def __init__(self, settings):
            pass

        async def plan(self, *args):
            raise RuntimeError("secret-value-not-for-client")

        async def close(self):
            pass

    monkeypatch.setattr("app.legacy.pipeline.Provider", BrokenProvider)
    settings = Settings(database=tmp_path / "failed.sqlite3")
    store = Store(settings.database)
    report = Report(
        id="failed-test",
        question="실패 테스트 사건 비교",
        mode="live",
        created_at="2026-10-09T00:00:00+00:00",
        steps=[Step(name=s) for s in STAGES],
    )
    asyncio.run(run_pipeline(report, settings, store))
    saved = store.get(report.id)
    assert saved.status == "failed" and not saved.sources and not saved.claims
    assert "secret-value" not in saved.model_dump_json()
    assert saved.steps[0].status == "failed"
