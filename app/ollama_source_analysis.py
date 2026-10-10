"""로컬 Ollama 원문 분석 호출과 모델 해제."""

import asyncio

import httpx

from .errors import AnalysisError
from .source_analysis import analyze_sources


class OllamaSourceAnalysis:
    def __init__(self, settings):
        self.settings = settings
        self.http = httpx.AsyncClient(base_url=settings.ollama_url,
                                      timeout=settings.ollama_timeout, trust_env=False)

    async def chat(self, payload):
        try:
            response = await self.http.post('/api/chat', json=payload)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise AnalysisError('Ollama 원문 분석 호출에 실패했습니다.') from None

    async def analyze(self, question, documents, trace):
        try:
            response = await self.http.get('/api/tags')
            response.raise_for_status()
            name = self.settings.ollama_model
            name = name if ':' in name else name + ':latest'
            model = next((m for m in response.json().get('models', []) if m.get('name') == name), None)
            if not model or model.get('remote_host') or model.get('remote_model'):
                raise AnalysisError('다운로드된 로컬 분석 모델을 찾지 못했습니다.')
            return await asyncio.wait_for(analyze_sources(self, question, documents,
                self.settings.ollama_model, trace), timeout=self.settings.ollama_timeout)
        except (httpx.HTTPError, ValueError):
            raise AnalysisError('Ollama 분석 서버·모델 확인에 실패했습니다.') from None
        except TimeoutError:
            raise AnalysisError('원문 분석 시간 제한을 초과했습니다. 문서 수를 줄여 다시 실행하세요.') from None
        finally:
            try:
                await self.http.post('/api/generate',
                    json={'model': self.settings.ollama_model, 'keep_alive': 0}, timeout=10)
            except httpx.HTTPError:
                pass
            await self.http.aclose()
