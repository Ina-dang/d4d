"""python -m app.analyze_collection 수집.json --output 검증입력.json"""

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from .analysis_timing import summarize_timings
from .config import Settings
from .errors import AnalysisError
from .ollama_source_analysis import OllamaSourceAnalysis
from .source_analysis_input import analysis_input, verification_input, verification_selection


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f'.{uuid4().hex}.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
                             encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


async def run(args):
    source = args.input.resolve()
    output = args.output.resolve()
    details = args.details.resolve() if args.details else output.with_name(output.stem + '-details.json')
    if source in {output, details} or output == details:
        raise AnalysisError('수집 원본, 결과 JSON, 상세 기록은 서로 다른 파일이어야 합니다.')
    payload = json.loads(source.read_text(encoding='utf-8-sig'))
    if args.question:
        payload = {**payload, 'input': {**payload.get('input', {}), 'question': args.question}}
    question, documents = analysis_input(payload)
    settings = Settings()
    if args.model:
        settings = replace(settings, ollama_model=args.model)
    if args.embedding_model:
        settings = replace(settings, ollama_embedding_model=args.embedding_model)
    provider = OllamaSourceAnalysis(settings)
    provider.input_scope = 'snippet'
    provider.similarity_target = getattr(args, 'similarity_target', 'other_documents')
    provider.force_cpu = args.cpu or settings.ollama_force_cpu
    def progress(update):
        if (update['stage'] == 'comparing'
                and update['stage_completed'] not in {0, update['stage_total']}):
            return
        print(update['detail'], flush=True)
    provider.progress = progress
    trace = []
    try:
        result = await provider.analyze(question, documents, trace)
    except AnalysisError as exc:
        save_json(details, {'error': str(exc), 'trace': trace,
                            'timings': summarize_timings(trace)})
        raise
    result['verification_selection'] = verification_selection(result)
    exported = verification_input(result)
    save_json(details, {'result': result, 'trace': trace})
    save_json(output, exported)
    print(json.dumps({'output': str(output), 'details': str(details),
                      'documents': len(result['docs']), 'claims': len(exported['claims']),
                      'analyzed_claims': len(result['claims']),
                      'timings': result['timings']}, ensure_ascii=False, indent=2))


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='수집 snippet을 docs·claims 신뢰도 함수 입력으로 변환')
    parser.add_argument('input', type=Path, help='by_country 수집 JSON 또는 저장된 수집 작업 JSON')
    parser.add_argument('--output', type=Path, required=True, help='docs·claims 결과 JSON')
    parser.add_argument('--details', type=Path, help='근거·경고·실측 시간·호출 기록 JSON')
    parser.add_argument('--question', help='분석 질문 재지정')
    parser.add_argument('--model', help='주장 추출·번역용 로컬 모델')
    parser.add_argument('--embedding-model', help='문서 임베딩용 로컬 모델')
    parser.add_argument('--similarity-target', choices=['other_documents', 'user_question'],
                        default='other_documents', help='sim 대상. 기본값은 문서 간 딕셔너리')
    parser.add_argument('--cpu', action='store_true', help='CPU 실행으로 팀원 환경 성능 확인')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (AnalysisError, OSError, ValueError, TypeError) as exc:
        parser.exit(1, f'분석 실패: {exc}\n')


if __name__ == '__main__':
    main()
