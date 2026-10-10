"""완료된 수집 파일을 분석하고 docs/claims 계약으로 저장·반환한다."""

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, HTTPException
from fastapi import Path as ApiPath
from fastapi.responses import FileResponse

from .errors import AnalysisError
from .ollama_source_analysis import OllamaSourceAnalysis

CollectionId = Annotated[str, ApiPath(pattern=r'^[a-zA-Z0-9_-]{1,80}$')]


def create_source_analysis_router(settings, collections):
    router = APIRouter(prefix='/api/collections', tags=['원문 주장·유사도 분석'])
    directory = settings.database.parent / 'source-analyses'
    lock = asyncio.Lock()

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
            try:
                result = await OllamaSourceAnalysis(settings).analyze(question, documents, trace)
                temporary = target.with_suffix('.tmp')
                temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                temporary.replace(target)
                return result
            except AnalysisError as exc:
                raise HTTPException(422, str(exc)) from None
            except OSError:
                raise HTTPException(500, '원문 분석 결과를 저장하지 못했습니다.') from None
            finally:
                # 부분 실패도 호출 입력·원시 응답을 보존해 원인 검토가 가능하다.
                try:
                    (directory / f'{rid}-trace.json').write_text(
                        json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
                except OSError:
                    pass

    @router.get('/{rid}/analysis/download')
    def download(rid: CollectionId):
        target = directory / f'{rid}.json'
        if not target.is_file():
            raise HTTPException(404, '완료된 원문 분석 결과가 없습니다.')
        return FileResponse(target, media_type='application/json', filename=f'analysis-{rid}.json')

    return router
