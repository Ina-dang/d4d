"""검색 계획용 로컬 Ollama 연결. 역할 종료 후 모델을 해제한다."""

import asyncio

import httpx

from app.config import Settings
from app.core.analysis_cache import AnalysisCache
from app.core.errors import AnalysisError
from app.llm.ollama_transport import stream_chat
from app.search.search_pipeline import generate_search
from app.search.search_schemas import SearchPlan


class OllamaSearch:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.force_cpu = settings.ollama_force_cpu
        self.http = httpx.AsyncClient(base_url=settings.ollama_url,
                                      timeout=settings.ollama_timeout, trust_env=False)

    async def chat(self, payload: dict) -> dict:
        try:
            return await asyncio.wait_for(
                stream_chat(self.http, payload, getattr(self, 'activity', None)),
                timeout=self.settings.ollama_timeout)
        except TimeoutError:
            raise AnalysisError('Ollama 검색어 생성의 개별 호출 시간 제한을 초과했습니다.') from None
        except (httpx.HTTPError, ValueError):
            raise AnalysisError('Ollama 검색어 생성 요청에 실패했습니다.') from None

    async def generate(self, question: str, languages: list[str], trace: dict) -> SearchPlan:
        model = self.settings.ollama_model
        try:
            try:
                response = await self.http.get('/api/tags')
                response.raise_for_status()
                name = model if ':' in model else model + ':latest'
                found = next((m for m in response.json().get('models', [])
                              if m.get('name') == name), None)
                if not found or found.get('remote_host') or found.get('remote_model'):
                    raise AnalysisError('다운로드된 로컬 모델을 찾지 못했습니다.')
                if found.get('digest'):
                    self.cache = AnalysisCache(self.settings.database.parent / 'search-cache', found['digest'])
            except (httpx.HTTPError, ValueError):
                raise AnalysisError('Ollama 로컬 서버·모델 확인에 실패했습니다.') from None
            raw = await generate_search(self, {'question': question, 'languages': languages},
                                        model, trace)
            return SearchPlan.model_validate(raw['assembled_output'])
        finally:
            try:
                response = await asyncio.wait_for(self.http.post('/api/generate',
                    json={'model': model, 'keep_alive': 0}, timeout=10), timeout=10)
                response.raise_for_status()
                raw = response.json()
                release = {'released': raw.get('done') is True and raw.get('done_reason') == 'unload'}
            except (httpx.HTTPError, ValueError, TimeoutError):
                release = {'released': False}
            trace['response']['model_release'] = release
            await self.http.aclose()
