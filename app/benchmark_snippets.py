"""모든 수집 snippet의 CPU 처리 시간과 메모리를 캐시 조건별로 기록한다."""

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
import platform
import sys
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import httpx

from .analysis_timing import summarize_timings
from .analyze_collection import save_json
from .config import Settings
from .errors import AnalysisError
from .ollama_source_analysis import OllamaSourceAnalysis
from .source_analysis_input import analysis_input, verification_input


def system_memory():
    if sys.platform != 'win32':
        return None

    class Memory(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                    *[(key, ctypes.c_ulonglong) for key in (
                        'total', 'available', 'page_total', 'page_available',
                        'virtual_total', 'virtual_available', 'extended')]]

    value = Memory()
    value.length = ctypes.sizeof(value)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        return None
    return {'physical_total_gib': round(value.total / 2**30, 3),
            'physical_available_gib': round(value.available / 2**30, 3),
            'load_percent': value.load}


def hardware():
    cpu = platform.processor()
    if sys.platform == 'win32':
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                    r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                cpu = winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
        except OSError:
            pass
    return {'cpu': cpu, 'logical_cpus': os.cpu_count(),
            'platform': platform.platform(), 'memory': system_memory()}


async def run(args):
    source = args.input.resolve()
    content = source.read_bytes()
    question, documents = analysis_input(json.loads(content.decode('utf-8-sig')))
    if any(d.get('text_snippet') is not None and not isinstance(d['text_snippet'], str)
           for d in documents):
        raise AnalysisError('text_snippet은 문자열 또는 null이어야 합니다.')
    directory = args.output.resolve()
    # 새 폴더만 허용하여 이전 결과·캐시가 최초 실행에 섞이지 않게 한다.
    directory.mkdir(parents=True, exist_ok=False)
    settings = replace(Settings(), ollama_force_cpu=True)
    if args.cache_run:
        settings = replace(settings, database=args.cache_run.resolve() / 'state.db')
    else:
        settings = replace(settings, database=directory / 'state.db')
    metadata = {**hardware(), 'force_cpu': True, 'cold_cache': args.cache_run is None,
                'cache_directory': str(settings.database.parent),
                'input': str(source), 'input_sha256': hashlib.sha256(content).hexdigest(),
                'document_ids': [d['doc_id'] for d in documents],
                'document_count': len(documents), 'model': settings.ollama_model,
                'embedding_model': settings.ollama_embedding_model,
                'similarity_target': 'other_documents',
                'article_fallback_enabled': True,
                'scope': 'saved_snippet_to_verification_input', 'target_seconds': 180,
                'excluded_stages': ['query_generation', 'live_collection',
                                    'confidence_function', 'report_generation']}
    save_json(directory / 'metadata.json', metadata)
    print(json.dumps(metadata, ensure_ascii=False), flush=True)
    provider = OllamaSourceAnalysis(settings)
    provider.input_scope = 'snippet'
    trace = []
    started = time.perf_counter()

    def append(name, row):
        with (directory / name).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')

    def progress(update):
        if update['stage'] == 'comparing' and update['stage_completed'] != update['stage_total']:
            return
        elapsed = round(time.perf_counter() - started, 3)
        append('progress.jsonl', {**update, 'elapsed_seconds': elapsed})
        save_json(directory / 'trace-live.json', trace)
        print(f"{elapsed}s {update['detail']}", flush=True)

    async def observe():
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            while True:
                row = {'elapsed_seconds': round(time.perf_counter() - started, 3),
                       'memory': system_memory()}
                try:
                    response = await client.get(settings.ollama_url + '/api/ps')
                    response.raise_for_status()
                    row['models'] = [{key: value for key, value in model.items() if key in (
                        'name', 'size', 'size_vram', 'context_length')}
                        for model in response.json().get('models', [])]
                except (httpx.HTTPError, ValueError):
                    row['models'] = None
                append('resources.jsonl', row)
                await asyncio.sleep(5)

    provider.progress = progress
    observer = asyncio.create_task(observe())
    result, error = None, None
    try:
        result = await provider.analyze(question, documents, trace)
        if [d['id'] for d in result['docs']] != metadata['document_ids']:
            raise AnalysisError('측정 결과의 기사 목록이 입력과 다릅니다.')
        save_json(directory / 'verification-input.json', verification_input(result))
    except (AnalysisError, OSError, ValueError) as exc:
        error = str(exc)
    finally:
        observer.cancel()
        await asyncio.gather(observer, return_exceptions=True)
    elapsed = round(time.perf_counter() - started, 3)
    record = {'status': 'failed' if error else 'completed', 'error': error,
              'metadata': metadata, 'wall_seconds': elapsed,
              'within_180_seconds': error is None and elapsed <= 180,
              'timings': result['timings'] if result else summarize_timings(trace),
              'result': result, 'trace': trace}
    save_json(directory / 'result.json', record)
    print(json.dumps({key: value for key, value in record.items()
                      if key not in ('metadata', 'result', 'trace')}, ensure_ascii=False), flush=True)
    return record


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='기사 수 제한 없는 CPU snippet 성능 측정')
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, default=Path('data/benchmarks') / ('cpu-' + uuid4().hex[:8]))
    parser.add_argument('--cache-run', type=Path, help='이전 측정 폴더의 캐시를 재사용하는 별도 측정')
    args = parser.parse_args()
    try:
        record = asyncio.run(run(args))
    except (AnalysisError, OSError, ValueError) as exc:
        parser.exit(1, f'측정 실패: {exc}\n')
    if record['status'] != 'completed':
        parser.exit(1, f"측정 실패: {record['error']}\n")


if __name__ == '__main__':
    main()
