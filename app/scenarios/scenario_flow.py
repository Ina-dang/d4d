"""브라우저 연결과 독립적으로 수집부터 보고서까지 실행하는 로컬 작업."""

import asyncio
import json
import statistics
import time
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.source_analysis_api_types import CollectionId
from app.core.errors import AnalysisError
from app.core.json_io import save_json
from app.search.search_schemas import CollectionRequest

STEPS = [
    ('queries', '언어별 검색어 생성'), ('collecting', 'URL 검색·원문 수집'),
    ('extracting', '주장 추출·번역'), ('comparing', '정규화·유사도 분석'),
    ('reliability', '신뢰도 계산'), ('report', '보고서 작성·근거 대조'),
]
RUNNING = {'running', 'cancelling'}


def now():
    return datetime.now(UTC).isoformat()


class ScenarioFlow:
    def __init__(self, settings, collections):
        self.settings, self.collections = settings, collections
        self.directory = settings.database.parent / 'scenarios-live'
        self.jobs = {}
        self.task = None
        self.lock = asyncio.Lock()
        self.analysis_lock = None
        self.analyze = self.generate = None
        collections.on_progress = self.collection_progress

    def path(self, rid):
        return self.directory / f'{rid}.json'

    def save(self, job):
        save_json(self.path(job['id']), job)

    def load(self, rid):
        if rid in self.jobs:
            return self.jobs[rid]
        try:
            job = json.loads(self.path(rid).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            # 기존 수동/CLI 실행의 run 링크도 같은 화면에서 읽고 이어갈 수 있다.
            collection = self.collections.read(rid)
            if collection.get('status') != 'completed':
                raise HTTPException(404, '저장된 자동 생성 작업을 찾지 못했습니다.') from None
            report_path = self.settings.database.parent / 'reliability-reports' / f'{rid}.json'
            report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else None
            timestamp = time.time()
            job = {'id': rid, 'status': 'completed' if report else 'interrupted', 'stage': 'report' if report else 'extracting',
                   'input': collection['input'], 'created_at': collection.get('created_at', now()),
                   'started_at_epoch': timestamp, 'finished_at_epoch': timestamp,
                   'stage_started_at': timestamp, 'stage_seconds': {}, 'progress': {}, 'legacy': True,
                   'counts': {'articles': collection['output'].get('total_count', 0),
                              'claims': len(report['evidence']) if report else 0},
                   'error': '' if report else '저장된 수집 결과가 있습니다. 이어서 분석과 보고서를 생성할 수 있습니다.'}
        if job['status'] in RUNNING:
            job.update(status='interrupted', error='서버가 다시 시작되어 작업이 중단됐습니다. 완료한 단계부터 이어갈 수 있습니다.')
            self.save(job)
        return job

    def progress(self, job, update):
        if job['status'] != 'running':
            return
        stage = update.get('stage', job['stage'])
        stage = {'generating_queries': 'queries', 'preparing': 'extracting',
                 'saving': 'comparing', 'completed': 'comparing'}.get(stage, stage)
        if stage not in dict(STEPS):
            stage = job['stage']
        if stage != job['stage']:
            previous = job['stage']
            job['stage_seconds'][previous] = job['stage_seconds'].get(previous, 0) + max(
                0, time.time() - job['stage_started_at'])
            job.update(stage=stage, stage_started_at=time.time(), progress={})
            self.save(job)
        job['progress'].update({key: update[key] for key in (
            'detail', 'completed', 'total', 'stage_completed', 'stage_total',
            'stage_percent', 'percent', 'received_chars') if key in update})

    def collection_progress(self, collection):
        job = self.jobs.get(collection['id'])
        if job:
            self.progress(job, {**collection.get('progress', {}), 'stage': collection['stage']})

    def artifacts(self, rid):
        base = self.settings.database.parent
        links = {}
        try:
            collection = self.collections.read(rid)
            if collection.get('collection_request'):
                links['queries'] = f'/api/collections/{rid}/download?format=queries'
            if collection.get('status') == 'completed':
                links['collection'] = f'/api/collections/{rid}/download?format=collection'
        except HTTPException:
            pass
        if (base / 'source-analyses' / f'{rid}.json').is_file():
            links['analysis'] = f'/api/collections/{rid}/analysis/download'
            links['verification'] = f'/api/collections/{rid}/analysis/download?format=verification'
        if (base / 'reliability-results' / f'{rid}.json').is_file():
            links['reliability'] = f'/api/scenarios/{rid}/reliability'
        if (base / 'reliability-reports' / f'{rid}.json').is_file():
            links['report_md'] = f'/api/collections/{rid}/analysis/report/download'
            links['report_json'] = f'/api/collections/{rid}/analysis/report/download?format=json'
        return links

    def estimate(self, body):
        """같은 실행 설정의 최근 실측만 사용한다. 첫 실행의 남은 시간을 꾸며내지 않는다."""
        signature = [self.settings.ollama_model, self.settings.ollama_embedding_model,
                     self.settings.ollama_force_cpu, sorted(body.languages), body.max_docs_per_country]
        samples = []
        paths = sorted(self.directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
        for path in paths:
            try:
                value = json.loads(path.read_text(encoding='utf-8'))
                if value.get('status') == 'completed' and value.get('estimate_signature') == signature:
                    samples.append(value['stage_seconds'])
            except (OSError, ValueError, KeyError):
                continue
        estimate = {key: round(statistics.median(s.get(key, 0) for s in samples), 1)
                    for key, _ in STEPS} if samples else None
        return signature, estimate, len(samples)

    def snapshot(self, job):
        stage_ids = [key for key, _ in STEPS]
        index = stage_ids.index(job['stage'])
        done = job['status'] == 'completed'
        elapsed = max(0, (job.get('finished_at_epoch') or time.time()) - job['started_at_epoch'])
        estimate = job.get('estimate')
        remaining = None
        if estimate and job['status'] == 'running':
            spent = time.time() - job['stage_started_at']
            remaining = sum(estimate[key] for key in stage_ids[index:]) - spent
            if remaining <= 0:
                remaining = None
        progress = job.get('progress', {})
        fraction = progress.get('stage_percent', progress.get('percent'))
        fraction = min(0.99, max(0, fraction / 100)) if isinstance(fraction, (int, float)) else 0
        return {**job, 'elapsed_seconds': round(elapsed), 'estimated_remaining_seconds':
                round(remaining) if remaining is not None else None,
                'percent': 100 if done else round((index + fraction) / len(STEPS) * 100),
                'steps': [{'id': key, 'label': label, 'status': 'completed' if done or i < index
                           else ('running' if job['status'] in RUNNING else job['status'])
                           if i == index else 'pending'} for i, (key, label) in enumerate(STEPS)],
                'artifacts': self.artifacts(job['id'])}

    def ensure_available(self):
        if ((self.task and not self.task.done()) or self.collections.scenario_id
                or (self.collections.task and not self.collections.task.done())
                or self.collections.lock.locked() or self.analysis_lock.locked()):
            raise HTTPException(409, '이미 실행 중인 작업이 있습니다. 진행 상태에서 이어서 확인하세요.')

    async def start(self, body, job=None):
        if not self.settings.tavily_key or not self.settings.reliability_function:
            raise HTTPException(503, 'Tavily 연결과 로컬 신뢰도 함수를 서버에 설정하세요.')
        async with self.lock:
            self.ensure_available()
            if job is None:
                signature, estimate, samples = self.estimate(body)
                job = {'id': uuid4().hex, 'created_at': now(), 'stage': 'queries',
                       'input': body.model_dump(mode='json'), 'stage_seconds': {},
                       'estimate_signature': signature, 'estimate': estimate, 'estimate_samples': samples}
            job.update(status='running', error='', progress={}, started_at_epoch=time.time(),
                       stage_started_at=time.time(), finished_at_epoch=None, cancel_requested=False,
                       execution_started=False)
            self.save(job)
            self.jobs[job['id']] = job
            # 동시 시작 및 별도 수동 API가 자동 실행 사이에 끼어들지 못하게 예약한다.
            self.collections.scenario_id = job['id']
            self.task = asyncio.create_task(self.execute(job, body), name=f'scenario-{job["id"]}')
            return self.snapshot(job)

    async def execute(self, job, body):
        rid = job['id']
        job['execution_started'] = True
        def notify(update):
            self.progress(job, update)
        try:
            if job.get('cancel_requested'):
                raise asyncio.CancelledError
            try:
                collection = self.collections.read(rid)
            except HTTPException:
                collection = None
            if not collection or collection.get('status') != 'completed':
                notify({'stage': 'queries', 'detail': '선택한 언어로 검색어를 만듭니다.'})
                collection = await self.collections.start(body, owner=rid)
                await asyncio.shield(self.collections.task)
            if job.get('cancel_requested'):
                raise asyncio.CancelledError
            if collection.get('status') != 'completed':
                raise AnalysisError(collection.get('error') or '원문 수집이 완료되지 않았습니다.')
            if not collection.get('output', {}).get('total_count'):
                raise AnalysisError('조건에 맞는 원문을 찾지 못했습니다. 질문이나 검색 언어를 조정하세요.')
            base = self.settings.database.parent
            analysis_path = base / 'source-analyses' / f'{rid}.json'
            notify({'stage': 'extracting', 'detail': '수집한 모든 문서에서 주장과 번역을 준비합니다.'})
            if not analysis_path.is_file():
                await self.analyze(rid, progress=notify)
            analysis = json.loads(analysis_path.read_text(encoding='utf-8'))
            job['counts'] = {'articles': collection['output']['total_count'],
                             'claims': analysis.get('verification_selection', {}).get(
                                 'exported_claim_count', len(analysis.get('claims', [])))}
            if job.get('cancel_requested'):
                raise asyncio.CancelledError
            notify({'stage': 'reliability'})
            report = await self.generate(rid, progress=notify)
            if job.get('cancel_requested'):
                raise asyncio.CancelledError
            job['counts']['claims'] = len(report['evidence'])
            job.update(status='completed', report_status=report['status'])
        except asyncio.CancelledError:
            job.update(status='cancelled' if job.get('cancel_requested') else 'interrupted',
                       error='작업을 중단했습니다. 저장된 단계부터 이어갈 수 있습니다.')
        except (AnalysisError, HTTPException) as exc:
            job.update(status='failed', error=exc.detail if isinstance(exc, HTTPException) else str(exc))
        except Exception:
            job.update(status='failed', error='처리 중 오류가 발생했습니다. 완료된 결과를 보존했습니다. 다시 이어서 실행하세요.')
        finally:
            job['stage_seconds'][job['stage']] = job['stage_seconds'].get(job['stage'], 0) + max(
                0, time.time() - job['stage_started_at'])
            job['finished_at_epoch'] = time.time()
            job['finished_at'] = now()
            try:
                self.save(job)
            except OSError:
                job.update(status='failed', error='작업 상태를 저장하지 못했습니다. 디스크 공간과 권한을 확인하세요.')
            finally:
                self.collections.scenario_id = None

    async def stop(self, rid):
        job = self.jobs.get(rid)
        if not job or job['status'] not in RUNNING:
            return self.snapshot(self.load(rid))
        job.update(status='cancelling', cancel_requested=True)
        self.save(job)
        if self.collections.task and not self.collections.task.done():
            self.collections.cancel_event.set()
            collection = self.collections.jobs[rid]
            stage = collection['stage']
            collection.update(cancel_requested=True, stage='cancelling')
            if stage == 'generating_queries' and self.collections.started:
                self.collections.task.cancel()
        elif self.task and job.get('execution_started'):
            self.task.cancel()
        return self.snapshot(job)

    async def close(self):
        await self.collections.close()
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    def router(self):
        router = APIRouter(prefix='/api/scenarios', tags=['질문부터 보고서까지'])

        @router.post('', status_code=202)
        async def start(body: CollectionRequest):
            return await self.start(body)

        @router.get('/active')
        async def active():
            rid = self.collections.scenario_id
            return self.snapshot(self.jobs[rid]) if rid else None

        @router.get('/{rid}')
        async def read(rid: CollectionId):
            return self.snapshot(self.load(rid))

        @router.post('/{rid}/cancel', status_code=202)
        async def cancel(rid: CollectionId):
            return await self.stop(rid)

        @router.post('/{rid}/resume', status_code=202)
        async def resume(rid: CollectionId):
            job = self.load(rid)
            if job['status'] not in {'failed', 'cancelled', 'interrupted'}:
                raise HTTPException(409, '중단되거나 실패한 작업만 이어서 실행할 수 있습니다.')
            return await self.start(CollectionRequest.model_validate(job['input']), job)

        @router.get('/{rid}/reliability')
        async def reliability(rid: CollectionId):
            self.load(rid)
            path = self.settings.database.parent / 'reliability-results' / f'{rid}.json'
            if not path.is_file():
                raise HTTPException(409, '신뢰도 계산이 아직 완료되지 않았습니다.')
            return FileResponse(path, media_type='application/json', filename=f'reliability-result-{rid}.json')

        return router
