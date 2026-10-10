"""로컬 Ollama 원문 분석 호출과 모델 해제."""

import asyncio
import time

import httpx

from .analysis_cache import AnalysisCache
from .errors import AnalysisError
from .ollama_transport import stream_chat
from .source_analysis import analyze_sources


class OllamaSourceAnalysis:
    def __init__(self, settings):
        self.settings = settings
        self.http = httpx.AsyncClient(base_url=settings.ollama_url,
                                      timeout=settings.ollama_timeout, trust_env=False)

    async def chat(self, payload):
        try:
            return await asyncio.wait_for(
                stream_chat(self.http, payload, getattr(self, 'activity', None)),
                timeout=self.settings.ollama_timeout)
        except (TimeoutError, httpx.TimeoutException):
            raise AnalysisError('원문 분석의 개별 LLM 호출 시간 제한을 초과했습니다. 완료된 검증 캐시는 재사용할 수 있습니다.') from None
        except (httpx.HTTPError, ValueError):
            raise AnalysisError('Ollama 원문 분석 호출에 실패했습니다.') from None

    async def analyze(self, question, documents, trace):
        started = time.perf_counter()
        result = None
        try:
            response = await self.http.get('/api/tags')
            response.raise_for_status()
            name = self.settings.ollama_model
            name = name if ':' in name else name + ':latest'
            model = next((m for m in response.json().get('models', []) if m.get('name') == name), None)
            if not model or model.get('remote_host') or model.get('remote_model'):
                raise AnalysisError('다운로드된 로컬 분석 모델을 찾지 못했습니다.')
            # 가변 모델 태그가 교체되면 동일 요청이라도 이전 응답을 사용하지 않는다.
            if model.get('digest'):
                self.cache = AnalysisCache(self.settings.database.parent / 'analysis-cache',
                                           model['digest'])
            # ollama_timeout은 개별 HTTP 호출 제한이다. 전체 문서가 하나의 300초 제한을 공유하지 않는다.
            result = await analyze_sources(self, question, documents,
                self.settings.ollama_model, trace, progress=getattr(self, 'progress', None))
            return result
        except (httpx.HTTPError, ValueError):
            raise AnalysisError('Ollama 분석 서버·모델 확인에 실패했습니다.') from None
        finally:
            try:
                await self.http.post('/api/generate',
                    json={'model': self.settings.ollama_model, 'keep_alive': 0}, timeout=10)
            except httpx.HTTPError:
                pass
            await self.http.aclose()
            if result is not None:
                result['timings']['total_seconds'] = round(time.perf_counter() - started, 3)
