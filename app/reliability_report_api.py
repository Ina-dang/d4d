"""신뢰도 함수 반환 JSON → 근거 보고서 → 명시적인 사람 검토·승인."""

import json
import time
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import Field

from .analyze_collection import save_json
from .errors import AnalysisError
from .local_reliability import verify_locally
from .ollama_reliability_report import create_report
from .reliability_report import ReportRequest, input_digest, report_evidence, report_markdown
from .source_analysis import Schema
from .source_analysis_api_types import CollectionId


class ReviewRequest(Schema):
    action: Literal['approve', 'hold', 'reopen']
    reviewer: str = Field(min_length=1, max_length=80)
    note: str = Field(min_length=1, max_length=2000)
    version: int = Field(strict=True, ge=1)
    comparison_decisions: dict[str, bool] = Field(default_factory=dict)


def create_report_router(settings, collections, analysis_lock):
    router = APIRouter(tags=['근거·신뢰도 보고서'])
    directory = settings.database.parent / 'reliability-reports'

    def load(rid, kind):
        folder = {'collection': 'collections', 'analysis': 'source-analyses',
                  'report': 'reliability-reports'}[kind]
        path = settings.database.parent / folder / f'{rid}.json'
        if not path.is_file():
            raise HTTPException(404, f'저장된 {kind} 결과가 없습니다.')
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (OSError, ValueError):
            raise HTTPException(422, '저장된 결과 JSON을 읽지 못했습니다.') from None

    def current_report(rid):
        value = load(rid, 'report')
        analysis = load(rid, 'analysis')
        if (input_digest(analysis) != value.get('input_sha256')
                or (analysis.get('analysis_question') and analysis['analysis_question'] != value.get('question'))):
            raise HTTPException(409, '분석 입력이 변경됐습니다. 신뢰도를 다시 검증하고 보고서를 생성하세요.')
        return value

    @router.get('/{rid}/analysis/report-input')
    def manifest(rid: CollectionId):
        return {'verification_input_sha256': input_digest(load(rid, 'analysis')),
                'local_function_configured': bool(settings.reliability_function)}

    async def generate(rid, body=None):
        if analysis_lock.locked() or (collections.task and not collections.task.done()):
            raise HTTPException(409, '검색·수집 또는 분석·보고서 생성이 실행 중입니다.')
        trace = []
        started = time.perf_counter()
        async with analysis_lock, collections.lock:
            if collections.task and not collections.task.done():
                raise HTTPException(409, '검색·수집이 실행 중입니다.')
            try:
                collection, analysis = load(rid, 'collection'), load(rid, 'analysis')
                if collection.get('status') != 'completed':
                    raise HTTPException(409, '완료된 수집만 보고서로 만들 수 있습니다.')
                if body is None:
                    if not settings.reliability_function:
                        raise HTTPException(503, '실제 로컬 신뢰도 함수의 파일·함수명을 서버 .env에 설정하세요.')
                    response = await verify_locally(settings, rid, analysis)
                    body = ReportRequest(reliability_result=response,
                                         verification_input_sha256=input_digest(analysis))
                packet = report_evidence(collection, analysis, body.reliability_result,
                                         body.verification_input_sha256)
                report = await create_report(settings, packet, trace)
                if input_digest(load(rid, 'analysis')) != packet['input_sha256']:
                    raise HTTPException(409, '보고서 생성 중 검증 입력이 변경됐습니다. 다시 검증하세요.')
                target = directory / f'{rid}.json'
                if target.is_file():
                    previous = load(rid, 'report')
                    report['version'] = previous['version'] + 1
                    report['audit'] = previous.get('audit', [])
                report['reliability_response'] = body.reliability_result.model_dump(mode='json')
                report['timings']['total_seconds'] = round(time.perf_counter() - started, 3)
                save_json(target, report)
                return report
            except AnalysisError as exc:
                raise HTTPException(422, str(exc)) from None
            except OSError:
                raise HTTPException(500, '보고서 결과를 저장하지 못했습니다.') from None
            finally:
                if trace:
                    save_json(directory / f'{rid}-trace.json', trace)

    @router.get('/{rid}/analysis/report')
    def read(rid: CollectionId):
        return current_report(rid)

    @router.get('/{rid}/analysis/report/download')
    def download(rid: CollectionId, format: Literal['md', 'json'] = 'md'):
        value = current_report(rid)
        content = report_markdown(value) if format == 'md' else json.dumps(value, ensure_ascii=False, indent=2)
        return PlainTextResponse(content, media_type='text/markdown' if format == 'md' else 'application/json',
            headers={'Content-Disposition': f'attachment; filename="report-{rid}.{format}"'})

    @router.post('/{rid}/analysis/report/review')
    async def review(rid: CollectionId, body: ReviewRequest):
        async with analysis_lock:
            value = current_report(rid)
            if value['version'] != body.version:
                raise HTTPException(409, '보고서 버전이 변경됐습니다. 최신 내용을 검토하세요.')
            if not body.reviewer.strip() or not body.note.strip():
                raise HTTPException(422, '검토자와 검토 의견을 입력하세요.')
            proposed = {item['item_id']: item for item in value.get('proposed_comparisons', [])}
            if not set(body.comparison_decisions) <= set(proposed):
                raise HTTPException(422, '현재 보고서에 없는 비교 제안입니다.')
            if body.action == 'approve' and set(body.comparison_decisions) != set(proposed):
                raise HTTPException(422, '각 비교 제안의 반영·제외 여부를 선택하세요.')
            for item_id, accepted in body.comparison_decisions.items():
                item = proposed.pop(item_id)
                if accepted:
                    value['sections'][item['section']].append({key: item[key] for key in ('text', 'claim_ids')})
                else:
                    value.setdefault('excluded_statements', []).append({**item, 'verdict': 'human_excluded', 'reason': body.note})
            value['proposed_comparisons'] = list(proposed.values())
            value['status'] = {'approve': 'approved', 'hold': 'held', 'reopen': 'draft'}[body.action]
            value['version'] += 1
            value['audit'].append({**body.model_dump(), 'at': datetime.now(UTC).isoformat()})
            save_json(directory / f'{rid}.json', value)
            return value

    @router.post('/{rid}/analysis/report')
    async def from_uploaded_result(rid: CollectionId, body: ReportRequest):
        return await generate(rid, body)

    @router.post('/{rid}/analysis/verify-report')
    async def from_local_function(rid: CollectionId):
        return await generate(rid)

    return router
