"""사용자 질문 → 로컬 검색 계획 → frame 요청 → 실제 수집 결과."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from frame.collector import OSINTCollector
from frame.schemas import SearchPlanRequest

from .config import Settings
from .errors import AnalysisError
from .ollama_search import OllamaSearch
from .search_schemas import CollectionRequest


class CollectionFlow:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.directory = settings.database.parent / 'collections'
        self.jobs: dict[str, dict] = {}
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()

    def path(self, rid: str):
        return self.directory / (rid + '.json')

    def save(self, job: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.path(job['id'])
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(target)

    async def execute(self, job: dict, body: CollectionRequest) -> None:
        final_status = 'failed'
        try:
            plan = await asyncio.wait_for(OllamaSearch(self.settings).generate(
                body.question, body.languages, job['llm_trace']),
                timeout=self.settings.ollama_timeout)
            if body.event_date and plan.event_date and body.event_date.isoformat() != plan.event_date:
                raise AnalysisError('입력한 사건 날짜와 질문에 명시된 날짜가 다릅니다.')
            event_date = body.event_date.isoformat() if body.event_date else plan.event_date
            if event_date:
                for query in plan.queries:
                    if event_date not in query.query:
                        query.query += '; ' + event_date
            request = SearchPlanRequest(event=plan.event, event_date=event_date,
                                       queries=[q.model_dump() for q in plan.queries],
                                       selected_languages=body.languages,
                                       relevance_context=job['llm_trace']['response']['relevance_context'])
            job.update(search_plan=plan.model_dump(), collection_request=request.model_dump(),
                       stage='collecting')
            collector = OSINTCollector(api_key=self.settings.tavily_key, raise_on_error=True)
            if collector.client is None:
                raise AnalysisError('Tavily 수집 클라이언트를 준비하지 못했습니다.')
            job['output'] = await asyncio.to_thread(collector.collect_plan,
                plan=request.model_dump(), days_back=body.days_back,
                max_docs_per_country=body.max_docs_per_country,
                max_results_per_query=body.max_docs_per_country,
                min_score=body.min_score, strict_min_score=body.strict_min_score)
            final_status = 'completed'
        except asyncio.CancelledError:
            job.update(stage='interrupted', error='서버 종료로 수집 작업이 중단됐습니다.')
            raise
        except AnalysisError as exc:
            job.update(error=str(exc))
        except TimeoutError:
            job.update(error='검색어 생성 시간 제한을 초과했습니다.')
        except Exception:
            job.update(error='수집 요청에 실패했습니다. Tavily 인증·연결 상태를 확인하세요.')
        finally:
            job['finished_at'] = datetime.now(UTC).isoformat()
            try:
                completed = {**job, 'status': final_status,
                             'stage': 'completed' if final_status == 'completed' else job['stage']}
                await asyncio.to_thread(self.save, completed)
                job.update(completed)
            except OSError:
                job.update(status='failed', error='수집 결과 파일을 저장하지 못했습니다.')

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    def router(self) -> APIRouter:
        router = APIRouter(prefix='/api/collections', tags=['실제 수집'])

        @router.post('', status_code=202)
        async def start(body: CollectionRequest):
            if not self.settings.tavily_key:
                raise HTTPException(503, '서버 .env에 TAVILY_API_KEY를 설정하세요.')
            async with self.lock:
                if self.task and not self.task.done():
                    raise HTTPException(409, '한 번에 하나의 검색·수집만 실행할 수 있습니다.')
                while len(self.jobs) >= 10:
                    self.jobs.pop(next(iter(self.jobs)))
                job = {'id': uuid4().hex, 'status': 'running', 'stage': 'generating_queries',
                       'created_at': datetime.now(UTC).isoformat(),
                       'input': body.model_dump(mode='json'), 'error': '',
                       'search_plan': None, 'collection_request': None, 'output': None,
                       'llm_trace': {'request': {}, 'response': {}}}
                self.jobs[job['id']] = job
                self.task = asyncio.create_task(self.execute(job, body))
                return job

        @router.get('/{rid}')
        def read(rid: str):
            if rid not in self.jobs:
                raise HTTPException(404, '이 서버 실행의 수집 기록을 찾지 못했습니다.')
            return self.jobs[rid]

        @router.get('/{rid}/download')
        def download(rid: str):
            job = read(rid)
            if job['status'] == 'running' or not self.path(rid).is_file():
                raise HTTPException(409, '수집 요청 처리가 아직 끝나지 않았습니다.')
            return FileResponse(self.path(rid), media_type='application/json',
                                filename='collected-' + rid + '.json')

        return router
