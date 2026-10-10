"""Run the deployed one-stop API and save its real outputs and timings locally."""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

from app.reporting.reliability_report import input_digest
from app.scenarios.scenario_checks import check_scenario

QUESTION = '중국과 대만의 대만해협 충돌에 관한 양측 발표와 주요 논쟁사항'


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def run(args):
    origin = urlsplit(args.origin)
    if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.password
            or origin.path not in {'', '/'} or origin.query or origin.fragment):
        raise ValueError('Use an exact HTTPS origin, with no credentials or path.')
    credentials = dotenv_values(args.env)
    auth = (credentials['SKYTRACE_ACCESS_USER'], credentials['SKYTRACE_ACCESS_PASSWORD'])
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=args.run_id is not None)
    with httpx.Client(base_url=args.origin, auth=auth, timeout=60, follow_redirects=False) as client:
        security = {
            'anonymous_access_blocked': client.get('/healthz', auth=None).status_code == 401,
            'authenticated_health_ok': client.get('/healthz').status_code == 200,
            'storyboard_ok': client.get('/storyboard/storyboard.html').status_code == 200,
        }
        save(output / 'http-checks.json', security)
        if not all(security.values()):
            raise RuntimeError('Deployment access checks failed; scenario was not started.')
        started = time.perf_counter()
        if args.run_id:
            rid = args.run_id
        else:
            request = {'question': QUESTION, 'languages': ['ko', 'zh', 'zh-Hant', 'ja', 'en'],
                       'max_docs_per_country': 20, 'days_back': 30, 'min_score': 0.7,
                       'strict_min_score': False}
            save(output / 'request.json', request)
            response = client.post('/api/scenarios', json=request,
                                   headers={'Origin': args.origin.rstrip('/')})
            response.raise_for_status()
            job = response.json()
            rid = job['id']
            save(output / 'scenario-start.json', job)
        print(json.dumps({'run_id': rid, 'output': str(output)}, ensure_ascii=False), flush=True)
        last = None
        while True:
            response = client.get(f'/api/scenarios/{rid}')
            response.raise_for_status()
            job = response.json()
            save(output / 'scenario-run.json', job)
            state = (job['status'], job['stage'], job.get('counts'), job.get('progress'))
            if state != last:
                print(json.dumps({'status': job['status'], 'stage': job['stage'],
                                  'seconds': job.get('elapsed_seconds'),
                                  'counts': job.get('counts'), 'progress': job.get('progress')},
                                 ensure_ascii=False), flush=True)
                last = state
            if job['status'] not in {'running', 'cancelling'}:
                break
            if time.perf_counter() - started > args.max_seconds:
                raise TimeoutError(f'Run {rid} continues on the server. Reconnect with --run-id.')
            time.sleep(5)
        observed_seconds = round(time.perf_counter() - started, 3)
        routes = {
            'collection-run.json': f'/api/collections/{rid}/download',
            'search-queries.json': f'/api/collections/{rid}/download?format=queries',
            'collected_live.json': f'/api/collections/{rid}/download?format=collection',
            'analysis.json': f'/api/collections/{rid}/analysis/download',
            'all-collected_verification-input.json': f'/api/collections/{rid}/analysis/download?format=verification',
            'reliability-result.json': f'/api/scenarios/{rid}/reliability',
            **{f'report.{fmt}': f'/api/collections/{rid}/analysis/report/download?format={fmt}'
               for fmt in ('json', 'md', 'pdf')},
        }
        downloads = {}
        for name, route in routes.items():
            response = client.get(route)
            downloads[name] = {'status': response.status_code, 'bytes': len(response.content)}
            if response.status_code == 200:
                (output / name).write_bytes(response.content)
        save(output / 'download-checks.json', downloads)
    if job['status'] != 'completed' or any(d['status'] != 200 for d in downloads.values()):
        raise RuntimeError(f"Scenario {rid} did not complete all outputs: {job.get('error', '')}")

    def load(name):
        return json.loads((output / name).read_text(encoding='utf-8'))

    collection = load('collected_live.json')
    save(output / 'collective_live.json', collection)
    analysis, verification = load('analysis.json'), load('all-collected_verification-input.json')
    report, reliability = load('report.json'), load('reliability-result.json')
    checks = check_scenario(load('collection-run.json'), collection, verification, analysis)
    scores = {claim['claim_id']: claim['reliability'] for claim in reliability['claims']}
    digest = input_digest(analysis)
    report_checks = {
        'current_input_bound': report['input_sha256'] == reliability['input_sha256'] == digest,
        'all_claims_scored': set(scores) == {c['claim_id'] for c in verification['claims']},
        'all_evidence_retained': len(report['evidence']) == len(scores),
        'scores_preserved': all(c['reliability'] == scores[c['claim_id']] for c in report['evidence']),
        'labels_returned': all(c.get('label') in {'값 일치', '개연성 있음', '판단 보류'}
                               for c in reliability['claims']),
        'unapproved_draft': report['status'] == 'draft' and not report.get('audit'),
        'pdf_signature': (output / 'report.pdf').read_bytes().startswith(b'%PDF-'),
    }
    checks['report_checks'] = report_checks
    checks['report_status'] = report['status']
    checks['all_checks_passed'] = checks['all_checks_passed'] and all(report_checks.values())
    checks['timings'].update(server_stage_seconds=job['stage_seconds'],
                             server_total_seconds=job['elapsed_seconds'],
                             reliability_and_report_seconds=round(sum(
                                 job['stage_seconds'].get(stage, 0)
                                 for stage in ('reliability', 'report')), 3),
                             observer_seconds=observed_seconds,
                             reconnect_only=args.run_id is not None)
    save(output / 'scenario-checks.json', checks)
    print(json.dumps({'run_id': rid, 'counts': checks['counts'], 'timings': checks['timings'],
                      'all_checks_passed': checks['all_checks_passed']}, ensure_ascii=False), flush=True)
    if not checks['all_checks_passed']:
        raise RuntimeError('Output integrity checks failed; inspect scenario-checks.json.')


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--origin', required=True)
    parser.add_argument('--env', required=True, type=Path, help='Private local deployment credentials')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--run-id', help='Download/watch an existing run without starting a paid search')
    parser.add_argument('--max-seconds', type=int, default=3600)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
