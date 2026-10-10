"""신뢰도 점수는 외부에서 받고, 로컬 모델 한 번으로 보고서 초안을 만든다."""

import httpx

from app.claims.ollama_source_analysis import OllamaSourceAnalysis
from app.core.analysis_cache import AnalysisCache
from app.core.errors import AnalysisError
from app.reporting.reliability_report import generate_report


async def create_report(settings, packet, trace, progress=None):
    provider = OllamaSourceAnalysis(settings)
    if progress:
        provider.activity = lambda update: progress({**update, 'stage': 'report'})
    try:
        response = await provider.http.get('/api/tags')
        response.raise_for_status()
        name = settings.ollama_model
        name = name if ':' in name else name + ':latest'
        model = next((m for m in response.json().get('models', []) if m.get('name') == name), None)
        if not model or model.get('remote_host') or model.get('remote_model'):
            raise AnalysisError('다운로드된 로컬 보고서 모델을 찾지 못했습니다.')
        if model.get('digest'):
            provider.cache = AnalysisCache(settings.database.parent / 'analysis-cache', model['digest'])
        return await generate_report(provider, settings.ollama_model, packet, trace)
    except (httpx.HTTPError, ValueError):
        raise AnalysisError('로컬 보고서 모델 확인에 실패했습니다.') from None
    finally:
        try:
            await provider.unload(settings.ollama_model)
        except AnalysisError:
            pass
        await provider.http.aclose()
