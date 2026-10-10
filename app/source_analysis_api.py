"""완료된 수집 파일을 분석하고 docs/claims 계약으로 저장·반환한다."""

import asyncio
import json
import time
from typing import Annotated

from fastapi import APIRouter, HTTPException
from fastapi import Path as ApiPath
from fastapi.responses import FileResponse

from .analysis_timing import summarize_timings
from .errors import AnalysisError
from .ollama_source_analysis import OllamaSourceAnalysis

CollectionId = Annotated[str, ApiPath(pattern=r'^[a-zA-Z0-9_-]{1,80}$')]


def create_source_analysis_router(settings, collections):
    router = APIRouter(prefix='/api/collections', tags=['원문 주장·유사도 분석'])
    directory = settings.database.parent / 'source-analyses'
    lock = asyncio.Lock()
    latest = {}

    def update_progress(update):
        latest.update(update)
        total = latest.get('total', 0)
        latest['percent'] = min(99.9, round(latest.get('completed', 0) / total * 100, 1)) if total else None
        stage_total = latest.get('stage_total', 0)
        latest['stage_percent'] = round(latest.get('stage_completed', 0) / stage_total * 100, 1) if stage_total else None

    @router.get('/{rid}/analysis/status')
    async def status(rid: CollectionId):
        if latest.get('id') == rid:
            return {**latest, 'elapsed_seconds': round(
                latest.get('finished_at', time.monotonic()) - latest['started_at'])}
        if (directory / f'{rid}.json').is_file():
            return {'id': rid, 'status': 'completed', 'stage': 'completed', 'percent': 100}
        raise HTTPException(404, '진행 중이거나 완료된 원문 분석이 없습니다.')

    @router.post('/{rid}/analysis')
    async def analyze(rid: CollectionId):
        # 검색·분석 모델이 동시에 로드되는 것을 피한다.
        if lock.locked() or (collections.task and not collections.task.done()):
            raise HTTPException(409, '검색·수집 또는 원문 분석이 실행 중입니다.')
        source = settings.database.parent / 'collections' / f'{rid}.json'
        if not source.is_file():
            raise HTTPException(404, '저장된 수집 결과를 찾지 못했습니다.')
        try:
            job = json.loads(source.read_text(encoding='utf-8'))
            if job.get('status') != 'completed':
                raise HTTPException(409, '완료된 수집 결과만 분석할 수 있습니다.')
            question = job['input']['question']
            output = job['output']
            documents = output.get('documents') or output.get('all_documents') or []
            if not isinstance(documents, list) or not documents:
                raise HTTPException(422, '분석할 수집 원문이 없습니다.')
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(422, '저장된 수집 결과 형식을 확인하세요.') from None
        async with lock, collections.lock:
            if collections.task and not collections.task.done():
                raise HTTPException(409, '검색·수집이 실행 중입니다.')
            # 이전 성공 결과가 재실행 실패의 결과로 오인되지 않게 제거한다.
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f'{rid}.json'
            target.unlink(missing_ok=True)
            trace = []
            latest.clear()
            latest.update(id=rid, status='running', stage='preparing', completed=0,
                          total=0, percent=None, detail='분석 모델과 원문을 준비합니다.',
                          started_at=time.monotonic())
            try:
                provider = OllamaSourceAnalysis(settings)
                provider.progress = update_progress
                provider.activity = lambda activity: latest.update(activity)
                result = await provider.analyze(question, documents, trace)
                latest.update(stage='saving', detail='분석 결과를 저장합니다.',
                              stage_completed=0, stage_total=1, stage_percent=0, received_chars=0)
                temporary = target.with_suffix('.tmp')
                temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                temporary.replace(target)
                latest.update(status='completed', stage='completed', percent=100,
                              stage_completed=1, stage_total=1, stage_percent=100,
                              detail='분석이 완료되었습니다.')
                return result
            except AnalysisError as exc:
                latest.update(status='failed', stage='failed', error=str(exc))
                raise HTTPException(422, str(exc)) from None
            except OSError:
                latest.update(status='failed', stage='failed', error='원문 분석 결과를 저장하지 못했습니다.')
                raise HTTPException(500, '원문 분석 결과를 저장하지 못했습니다.') from None
            finally:
                if latest['status'] == 'running':
                    latest.update(status='failed', stage='failed', error='원문 분석이 중단되었습니다.')
                latest['finished_at'] = time.monotonic()
                # 부분 실패도 호출 입력·원시 응답을 보존해 원인 검토가 가능하다.
                try:
                    (directory / f'{rid}-trace.json').write_text(
                        json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
                    (directory / f'{rid}-timings.json').write_text(json.dumps({
                        **summarize_timings(trace),
                        'total_seconds': round(latest['finished_at'] - latest['started_at'], 3),
                        'status': latest['status']}, ensure_ascii=False, indent=2), encoding='utf-8')
                except OSError:
                    pass

    @router.get('/{rid}/analysis/download')
    def download(rid: CollectionId):
        target = directory / f'{rid}.json'
        if not target.is_file():
            raise HTTPException(404, '완료된 원문 분석 결과가 없습니다.')
        return FileResponse(target, media_type='application/json', filename=f'analysis-{rid}.json')

    return router
