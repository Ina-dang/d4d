"""실제 질문 → 검색어 생성 → Tavily 수집 → 검증 입력 JSON을 저장한다."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

from .analyze_collection import run as analyze_collection
from .analyze_collection import save_json
from .collection_export import collection_export
from .collection_flow import CollectionFlow
from .config import Settings
from .errors import AnalysisError
from .scenario_checks import check_scenario
from .search_schemas import CollectionRequest


async def run(args):
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    settings = Settings()
    request = CollectionRequest(question=args.question, languages=args.languages)
    flow = CollectionFlow(settings)
    job = {'id': uuid4().hex, 'status': 'running', 'stage': 'generating_queries',
           'created_at': datetime.now(UTC).isoformat(), 'input': request.model_dump(mode='json'),
           'error': '', 'search_plan': None, 'collection_request': None, 'output': None,
           'llm_trace': {'request': {}, 'response': {}}}
    print(f"질문: {request.question}\n실행 ID: {job['id']}", flush=True)
    try:
        await flow.execute(job, request, Event())
    finally:
        save_json(directory / 'collection-run.json', job)
    if job['status'] != 'completed':
        raise AnalysisError(job.get('error') or '실제 수집 실행이 완료되지 않았습니다.')
    collected = collection_export(job)
    save_json(directory / 'collective_live.json', collected)
    save_json(directory / 'collected_live.json', collected)
    save_json(directory / 'collection-counts.json', {
        'id': job['id'], 'documents': collected['total_count'],
        'by_country': {country: len(documents) for country, documents in collected['by_country'].items()},
        'filtering': job['output'].get('filtering'), 'timings': job['timings']})
    print(json.dumps({'collection': str(directory / 'collective_live.json'),
                      'documents': collected['total_count'], 'timings': job['timings']},
                     ensure_ascii=False), flush=True)
    args.input = directory / 'collective_live.json'
    args.output = directory / 'all-collected_verification-input.json'
    args.details = directory / 'all-collected_verification-input-details.json'
    args.question = args.model = args.embedding_model = None
    args.cpu = False
    args.similarity_target = 'other_documents'
    await analyze_collection(args)
    # CLI로 실행한 시나리오도 화면의 신뢰도 보고서 API에서 이어서 사용할 수 있다.
    details = json.loads(args.details.read_text(encoding='utf-8'))
    analysis_dir = settings.database.parent / 'source-analyses'
    save_json(analysis_dir / f"{job['id']}.json", details['result'])
    save_json(analysis_dir / f"{job['id']}-trace.json", details['trace'])
    verification = json.loads(args.output.read_text(encoding='utf-8'))
    checks = check_scenario(job, collected, verification, details['result'])
    save_json(directory / 'scenario-checks.json', checks)
    if not checks['all_checks_passed']:
        raise AnalysisError('시나리오 형식·근거 검사에 실패했습니다. scenario-checks.json을 확인하세요.')


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='같은 화면 경로로 실제 수집·검증 입력 시나리오 실행')
    parser.add_argument('--question', required=True)
    parser.add_argument('--languages', nargs='+', default=['ko', 'zh', 'zh-Hant', 'ja', 'en'])
    parser.add_argument('--output', type=Path, required=True, help='새로 생성할 시나리오 폴더')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (AnalysisError, OSError, ValueError, TypeError) as exc:
        parser.exit(1, f'시나리오 실패: {exc}\n')


if __name__ == '__main__':
    main()
