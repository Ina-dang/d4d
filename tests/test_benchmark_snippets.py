import asyncio
import json
from types import SimpleNamespace

import pytest
from test_snippet_analysis import collection

from app import benchmark_snippets
from app.errors import AnalysisError


@pytest.mark.parametrize('fail', [False, True])
def test_cpu_benchmark_uses_all_articles_and_isolates_cold_cache(tmp_path, monkeypatch, fail):
    source = tmp_path / 'source.json'
    source.write_text(json.dumps(collection()), encoding='utf8')
    original = source.read_bytes()
    output = tmp_path / 'run'
    args = SimpleNamespace(input=source, output=output, cache_run=None)
    seen = []

    class Provider:
        def __init__(self, settings):
            assert settings.ollama_force_cpu is True
            assert settings.database.parent == output

        async def analyze(self, question, documents, trace):
            seen.extend(d['doc_id'] for d in documents)
            trace.append({'phase': 'extraction', 'elapsed_seconds': 2})
            if fail:
                raise AnalysisError('번역 검토 실패')
            return {'docs': [{'id': d['doc_id'], 'country': d['country'],
                             'weight': d['credibility_weight'], 'sim': {}} for d in documents],
                    'claims': [], 'timings': {'total_seconds': 2}}

    monkeypatch.setattr(benchmark_snippets, 'OllamaSourceAnalysis', Provider)
    record = asyncio.run(benchmark_snippets.run(args))
    assert seen == ['doc_cn', 'doc_tw']
    assert record['metadata']['cold_cache'] is True
    assert record['metadata']['scope'] == 'saved_snippet_to_verification_input'
    assert source.read_bytes() == original
    assert (output / 'result.json').is_file()
    assert (output / 'verification-input.json').is_file() is (not fail)
    assert record['within_180_seconds'] is (not fail)
    with pytest.raises(FileExistsError):
        asyncio.run(benchmark_snippets.run(args))
