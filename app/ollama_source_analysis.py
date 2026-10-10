"""로컬 Ollama 원문 분석 호출과 모델 해제."""

import asyncio
import time

import httpx

from .analysis_cache import AnalysisCache
from .errors import AnalysisError
from .ollama_transport import stream_chat
from .snippet_analysis import analyze_snippets
from .source_analysis import analyze_sources


class OllamaSourceAnalysis:
    def __init__(self, settings):
        self.settings = settings
        self.batch_snippets = True
        self.similarity_target = 'other_documents'
        self.force_cpu = settings.ollama_force_cpu
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

    async def embed(self, payload):
        try:
            response = await asyncio.wait_for(self.http.post('/api/embed', json=payload),
                                              timeout=self.settings.ollama_timeout)
            response.raise_for_status()
            return response.json()
        except (TimeoutError, httpx.TimeoutException):
            raise AnalysisError('임베딩 호출 시간 제한을 초과했습니다.') from None
        except (httpx.HTTPError, ValueError):
            raise AnalysisError('Ollama 임베딩 호출에 실패했습니다. 입력 한도와 모델을 확인하세요.') from None

    async def unload(self, model):
        try:
            response = await self.http.post('/api/generate',
                json={'model': model, 'keep_alive': 0}, timeout=10)
            response.raise_for_status()
        except httpx.HTTPError:
            raise AnalysisError('분석 모델을 메모리에서 해제하지 못했습니다.') from None

    async def analyze(self, question, documents, trace):
        started = time.perf_counter()
        result = None
        snippet_mode = (getattr(self, 'input_scope', None) == 'snippet'
                        or any('text_snippet' in document or ('article_text' in document
                               and 'paragraphs' not in document) for document in documents))
        used_models = [self.settings.ollama_model]
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
            if snippet_mode:
                embedding_name = self.settings.ollama_embedding_model
                name = embedding_name if ':' in embedding_name else embedding_name + ':latest'
                embedding = next((m for m in response.json().get('models', [])
                                  if m.get('name') == name), None)
                if not embedding or embedding.get('remote_host') or embedding.get('remote_model'):
                    raise AnalysisError(f'로컬 임베딩 모델이 없습니다. ollama pull {embedding_name}을 실행하세요.')
                if embedding.get('digest'):
                    self.embedding_cache = AnalysisCache(
                        self.settings.database.parent / 'embedding-cache', embedding['digest'])
                used_models.append(embedding_name)
                result = await analyze_snippets(self, question, documents,
                    self.settings.ollama_model, embedding_name, trace,
                    progress=getattr(self, 'progress', None))
                return result
            # ollama_timeout은 개별 HTTP 호출 제한이다. 전체 문서가 하나의 300초 제한을 공유하지 않는다.
            result = await analyze_sources(self, question, documents,
                self.settings.ollama_model, trace, progress=getattr(self, 'progress', None))
            return result
        except (httpx.HTTPError, ValueError):
            raise AnalysisError('Ollama 분석 서버·모델 확인에 실패했습니다.') from None
        finally:
            for name in used_models:
                try:
                    await self.unload(name)
                except AnalysisError:
                    pass
            await self.http.aclose()
            if result is not None:
                result['timings']['total_seconds'] = round(time.perf_counter() - started, 3)
