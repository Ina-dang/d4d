"""같은 실행의 검증 입력으로 로컬 신뢰도 계산·보고서 생성을 마무리한다."""

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

from app.claims.source_analysis_input import verification_input
from app.config import Settings
from app.core.errors import AnalysisError
from app.core.json_io import save_json
from app.reliability.local_reliability import verify_locally
from app.reporting.ollama_reliability_report import create_report
from app.reporting.reliability_report import (
    ReliabilityResponse,
    input_digest,
    report_evidence,
    report_markdown,
)


async def complete_scenario(directory, settings=None):
    directory = directory.resolve()
    settings = settings or Settings()
    def load(name):
        return json.loads((directory / name).read_text(encoding='utf-8-sig'))
    job, collection = load('collection-run.json'), load('collective_live.json')
    analysis = load('all-collected_verification-input-details.json')['result']
    verification, checks = load('all-collected_verification-input.json'), load('scenario-checks.json')
    if job['status'] != 'completed' or not checks['all_checks_passed']:
        raise AnalysisError('수집·분석 검사에 통과한 같은 실행만 보고서로 연결할 수 있습니다.')
    if verification != verification_input(analysis):
        raise AnalysisError('저장된 검증 입력과 분석 상세 기록이 다릅니다.')
    digest = input_digest(analysis)
    result_path = directory / 'reliability-result.json'
    started = time.perf_counter()
    reused = result_path.is_file()
    if reused:
        response = ReliabilityResponse.model_validate(load(result_path.name))
        if response.input_sha256 != digest:
            raise AnalysisError('저장된 신뢰도 결과가 현재 입력과 다릅니다. 새 실행이 필요합니다.')
    else:
        response = await verify_locally(settings, job['id'], analysis)
    packet = report_evidence(collection, analysis, response, digest)
    if {claim.claim_id for claim in response.claims} != {c['claim_id'] for c in verification['claims']}:
        raise AnalysisError('신뢰도 함수가 현재 대표 주장 전체를 반환하지 않았습니다.')
    response_json = response.model_dump(mode='json', exclude_unset=True)
    save_json(result_path, response_json)
    if settings.reliability_function == 'analysis.reliability:run':
        from analysis.reliability import DEFAULT_M, DEFAULT_P_SAME, run

        full = run(verification, full=True)
        if full['claims'] != [claim.model_dump(mode='json', exclude={'country'})
                              for claim in response.claims]:
            raise AnalysisError('실제 함수 반환 점수와 동일 입력의 계산 근거가 다릅니다.')
        full['input_sha256'] = digest
        full['calculation_metadata'] = {'function': settings.reliability_function,
            'm': DEFAULT_M, 'p_same_table': DEFAULT_P_SAME,
            'score_scope': 'document_score_assigned_to_representative_claim',
            'unknown_country_grouped_together': 'GLOBAL' in full['countries']}
        save_json(directory / 'reliability-result-full.json', full)
        packet['warnings'].extend([
            '현재 신뢰도 함수는 문서 유사도 구간을 같은 입장 확률표에 대응시키고 '
            '출처 가중치·국가 보정으로 계산한 문서 점수를 해당 대표 주장에 부여합니다. '
            '개별 주장 간 사실 교차검증 결과나 진실 확률이 아닙니다.',
            '같은 입장 확률표의 대만해협·다국어 snippet 적용 적합성은 이 시나리오에서 검증하지 않았습니다.'])
        if 'GLOBAL' in full['countries']:
            packet['warnings'].append('국가 미상 GLOBAL 문서들은 함수의 같은 국가 보정 그룹에 '
                                      '묶였습니다. 실제 같은 국적이나 출처 종속성을 확인한 것은 아닙니다.')
    reliability_seconds = time.perf_counter() - started
    trace = []
    report_started = time.perf_counter()
    try:
        report = await create_report(settings, packet, trace)
        report['reliability_response'] = response_json
        report['scenario_run_id'] = job['id']
        report['reliability_function'] = settings.reliability_function
        save_json(directory / 'report.json', report)
        (directory / 'report.md').write_text(report_markdown(report), encoding='utf-8')
        save_json(settings.database.parent / 'reliability-reports' / f"{job['id']}.json", report)
    finally:
        if trace:
            save_json(directory / 'report-trace.json', trace)
            save_json(settings.database.parent / 'reliability-reports' / f"{job['id']}-trace.json", trace)
    report_seconds = time.perf_counter() - report_started
    scores = {claim.claim_id: claim.reliability for claim in response.claims}
    full_checks = {
        'verification_input_unchanged': verification == verification_input(analysis),
        'response_bound_to_current_input': response.input_sha256 == digest == report['input_sha256'],
        'every_representative_claim_returned': set(scores) == {c['claim_id'] for c in verification['claims']},
        'returned_scores_preserved': all(claim['reliability'] == scores[claim['claim_id']]
                                         for claim in report['evidence']),
        'all_representative_evidence_retained': len(report['evidence']) == len(scores),
        'report_is_unapproved_draft': report['status'] == 'draft' and report['audit'] == [],
        'report_citations_exist': all(set(item['claim_ids']) <= set(scores)
            for item in [*(item for items in report['sections'].values() for item in items),
                         *report.get('proposed_comparisons', [])]),
    }
    if not all(full_checks.values()):
        raise AnalysisError('신뢰도·보고서의 입력 연결 또는 점수 보존 검사에 실패했습니다.')
    timings = {**checks['timings'], 'reliability_seconds': round(reliability_seconds, 3),
        'report_seconds': round(report_seconds, 3),
        'reliability_and_report_seconds': round(reliability_seconds + report_seconds, 3)}
    timings['through_report_seconds'] = round(timings['through_verification_input_seconds'] +
                                              reliability_seconds + report_seconds, 3)
    checks.update(timings=timings, report_status=report['status'], full_pipeline_checks=full_checks)
    save_json(directory / 'scenario-checks.json', checks)
    evaluated = [value for value in scores.values() if value is not None]
    summary = {'run_id': job['id'], 'question': packet['question'], 'input_sha256': digest,
        'reliability_function': settings.reliability_function, 'reliability_reused': reused,
        'counts': {**checks['counts'], 'scored_claims': len(evaluated),
                   'unevaluated_claims': len(scores) - len(evaluated),
                   'report_evidence': len(report['evidence']),
                   'report_section_items': {key: len(items) for key, items in report['sections'].items()},
                   'proposed_comparisons': dict(Counter(item['section'] for item in report.get('proposed_comparisons', []))),
                   'excluded_statements': len(report.get('excluded_statements', []))},
        'score_range': {'min': min(evaluated) if evaluated else None,
                        'max': max(evaluated) if evaluated else None},
        'labels_returned': dict(Counter(claim.label for claim in response.claims if claim.label is not None)),
        'all_checks_passed': all(full_checks.values()) and checks['all_checks_passed'],
        'timings': timings, 'report_status': report['status'], 'warnings': report['warnings']}
    save_json(directory / 'scenario-summary.json', summary)
    print(json.dumps({'summary': str(directory / 'scenario-summary.json'),
        'documents': len(verification['docs']), 'scored_claims': len(evaluated),
        'report_status': report['status'], 'timings': timings}, ensure_ascii=False), flush=True)
    return summary


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='수집·분석 완료 시나리오를 실제 신뢰도 함수·보고서로 연결')
    parser.add_argument('--directory', required=True, type=Path)
    args = parser.parse_args()
    try:
        asyncio.run(complete_scenario(args.directory))
    except (AnalysisError, OSError, ValueError, TypeError) as exc:
        parser.exit(1, f'신뢰도·보고서 실행 실패: {exc}\n')


if __name__ == '__main__':
    main()
