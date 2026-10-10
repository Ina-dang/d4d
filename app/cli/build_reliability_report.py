"""저장한 수집·분석 결과를 로컬 신뢰도 함수 또는 반환 JSON으로 보고서에 연결한다."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.core.errors import AnalysisError
from app.core.json_io import save_json
from app.reliability.local_reliability import verify_locally
from app.reporting.ollama_reliability_report import create_report
from app.reporting.reliability_report import ReliabilityResponse, report_evidence, report_markdown


async def run(args):
    protected = {args.collection.resolve(), args.details.resolve()}
    if args.result:
        protected.add(args.result.resolve())
    if args.output.resolve() in protected or args.output.with_suffix('.md').resolve() in protected:
        raise AnalysisError('보고서 파일이 수집·분석·신뢰도 원본을 덮어쓸 수 없습니다.')
    collection = json.loads(args.collection.read_text(encoding='utf-8-sig'))
    details = json.loads(args.details.read_text(encoding='utf-8-sig'))
    analysis = details.get('result', details)
    settings = Settings()
    response = ReliabilityResponse.model_validate(json.loads(args.result.read_text(encoding='utf-8-sig'))) if args.result else await verify_locally(settings, uuid4().hex, analysis)
    packet = report_evidence(collection, analysis, response)
    trace = []
    try:
        report = await create_report(settings, packet, trace)
        report['reliability_response'] = response.model_dump(mode='json')
        save_json(args.output, report)
        args.output.with_suffix('.md').write_text(report_markdown(report), encoding='utf-8')
        print(json.dumps({'output': str(args.output.resolve()), 'status': report['status'],
                          'evidence': len(report['evidence']), 'timings': report['timings']}, ensure_ascii=False))
    finally:
        if trace:
            save_json(args.output.with_name(args.output.stem + '-trace.json'), trace)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='신뢰도 반환 점수로 근거 보고서 초안 생성')
    parser.add_argument('--collection', type=Path, required=True)
    parser.add_argument('--details', type=Path, required=True)
    parser.add_argument('--result', type=Path, help='생략하면 .env의 로컬 함수를 실제 호출')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (AnalysisError, OSError, ValueError) as exc:
        parser.exit(1, f'보고서 생성 실패: {exc}\n')


if __name__ == '__main__':
    main()
