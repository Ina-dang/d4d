"""Inspect deployability without running a paid search or an LLM inference."""

import argparse
import importlib
import json
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

import httpx

from app.config import Settings
from app.core.json_io import save_json
from app.core.paths import PROMPTS, STATIC


def inspect(settings, target='local', check_services=False):
    checks = []

    def add(name, passed, detail):
        checks.append({'name': name, 'passed': bool(passed), 'detail': detail})

    add('tavily_configured', settings.tavily_key, 'Tavily 키 설정 여부. 유효성·잔액은 별도 확인 필요.')
    add('prompts', (PROMPTS / 'source_reliability_report.txt').is_file(), '보고서 프롬프트 포함 여부')
    add('pdf_font', (STATIC / 'fonts/NotoSansCJKkr-Regular.ttf').is_file(), '한중일 PDF 글꼴 포함 여부')
    module, separator, name = settings.reliability_function.partition(':')
    try:
        function_ready = bool(separator and callable(getattr(importlib.import_module(module), name)))
    except (ImportError, AttributeError, ValueError):
        function_ready = False
    add('reliability_function', function_ready, '설정한 module:function import 확인 (함수 실행 없음)')
    try:
        settings.database.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=settings.database.parent):
            pass
        writable = True
    except OSError:
        writable = False
    add('storage_writable', writable, '데이터 디렉터리 쓰기 확인. 재배포 후 영속성은 호스팅에서 확인 필요.')
    if target == 'persistent':
        add('deployment_mode', settings.deployment, 'SKYTRACE_DEPLOYMENT=1')
        add('access_control', settings.access_user and len(settings.access_password) >= 16, '팀 접속 계정 설정')
        add('public_origins', settings.public_origins, 'Vercel/백엔드의 정확한 HTTPS 출처 설정')
    if target == 'vercel-functions':
        add('hosted_llm', False, '현재 Ollama는 로컬 루프백 전용. 외부 추론 서비스와 어댑터가 필요합니다.')
        add('durable_storage', False, '현재 SQLite/JSON 파일 저장. 외부 DB·오브젝트 저장소가 필요합니다.')
        add('durable_jobs', False, '현재 프로세스 내 asyncio 작업·잠금. 내구성 작업 큐와 공유 상태가 필요합니다.')
    if check_services:
        try:
            response = httpx.get(f'{settings.ollama_url.rstrip("/")}/api/tags', timeout=5)
            response.raise_for_status()
            models = {item['name'] for item in response.json()['models']}
            for role, model in [('generation', settings.ollama_model), ('embedding', settings.ollama_embedding_model)]:
                add(f'ollama_{role}', model in models or model + ':latest' in models,
                    'Ollama에 설정한 모델이 설치되어 있는지 확인 (추론 없음)')
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            add('ollama_connection', False, 'Ollama 모델 목록 조회 실패. 서비스 주소·기동 상태를 확인하세요.')
    return {
        'target': target, 'checks_passed': all(c['passed'] for c in checks), 'checks': checks,
        'scope': '설정·리소스 검사이며 실제 클라우드 배포나 유료 API 호출 성공을 보증하지 않습니다.',
        'optional_openai_configured': bool(settings.openai_key),
        'constraints': ['단일 서버/worker 1개', '영구 데이터 볼륨', '원스톱은 비동기 시작 후 상태 조회',
                        '기존 수동 분석·보고서 동기 API는 외부 프록시의 120초 제한에 걸릴 수 있음'],
    }


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=['local', 'persistent', 'vercel-functions'], default='local')
    parser.add_argument('--check-services', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = inspect(Settings(), args.target, args.check_services)
    if args.output:
        save_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['checks_passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
