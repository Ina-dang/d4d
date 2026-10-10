"""snippet·질문의 임베딩을 재사용하고 질문 관련도를 계산한다."""

import math
import time

from app.core.errors import AnalysisError

EMBED_BATCH_SIZE = 4


def unit_vector(vector):
    if not isinstance(vector, list) or not vector or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) for value in vector):
        raise AnalysisError('임베딩 벡터에 유효하지 않은 값이 있습니다.')
    norm = math.hypot(*vector)
    if not norm or not math.isfinite(norm):
        raise AnalysisError('임베딩 벡터의 길이가 0이거나 유효하지 않습니다.')
    return [value / norm for value in vector]


def cosine(left, right):
    if len(left) != len(right):
        raise AnalysisError('임베딩 벡터의 차원이 서로 다릅니다.')
    # 외부 sim 계약은 0~1이다. 음수는 0으로 처리하며 확률로 해석하지 않는다.
    return round(max(0.0, min(1.0, math.fsum(
        a * b for a, b in zip(left, right, strict=True)))), 6)


async def embed_documents(client, documents, model, trace):
    cache = getattr(client, 'embedding_cache', None)
    vectors, pending = {}, []
    for document in documents:
        snippet = document['text_snippet'].strip()
        if not snippet:
            continue
        text = '\n'.join(part for part in (document.get('title') or '', snippet) if part)
        key = {'embedding_version': 1, 'model': model, 'input': text}
        started = time.perf_counter()
        saved = cache.read(key) if cache is not None else None
        if saved is not None:
            try:
                vectors[document['doc_id']] = unit_vector(saved.get('embedding'))
                trace.append({'phase': 'embedding', 'kind': 'embedding', 'cache_hit': True,
                              'document_ids': [document['doc_id']],
                              'elapsed_seconds': round(time.perf_counter() - started, 3)})
                continue
            except AnalysisError:
                pass
        pending.append((document['doc_id'], text, key))

    for start in range(0, len(pending), EMBED_BATCH_SIZE):
        batch = pending[start:start + EMBED_BATCH_SIZE]
        payload = {'model': model, 'input': [entry[1] for entry in batch],
                   'truncate': False, 'keep_alive': '30s'}
        if getattr(client, 'force_cpu', False):
            payload['options'] = {'num_gpu': 0}
        record = {'phase': 'embedding', 'kind': 'embedding', 'cache_hit': False,
                  'request': payload, 'response': None,
                  'document_ids': [entry[0] for entry in batch]}
        trace.append(record)
        started = time.perf_counter()
        try:
            response = await client.embed(payload)
            record['response'] = response
            embeddings = response.get('embeddings') if isinstance(response, dict) else None
            if not isinstance(embeddings, list) or len(embeddings) != len(batch):
                raise AnalysisError('임베딩 응답에서 문서별 벡터가 누락됐습니다.')
            normalized = [unit_vector(vector) for vector in embeddings]
            dimensions = {len(vector) for vector in [*vectors.values(), *normalized]}
            if len(dimensions) != 1:
                raise AnalysisError('임베딩 벡터의 차원이 서로 다릅니다.')
            for (did, _text, key), vector, raw in zip(batch, normalized, embeddings, strict=True):
                vectors[did] = vector
                if cache is not None:
                    cache.write(key, {'embedding': raw})
        finally:
            record['elapsed_seconds'] = round(time.perf_counter() - started, 3)
    if len({len(vector) for vector in vectors.values()}) > 1:
        raise AnalysisError('임베딩 벡터의 차원이 서로 다릅니다.')
    return vectors


async def embed_question_and_snippets(client, question, documents, model, trace):
    if not isinstance(question, str) or not question.strip():
        raise AnalysisError('질문 관련도를 계산할 사용자 질문이 필요합니다.')
    ids = {doc['doc_id'] for doc in documents}
    question_id = '__user_question__'
    while question_id in ids:
        question_id += '_'
    inputs = [{'doc_id': question_id, 'text_snippet': question, 'title': ''}]
    inputs.extend({**doc, 'title': ''} for doc in documents)
    vectors = await embed_documents(client, inputs, model, trace)
    query = vectors.pop(question_id)
    return query, vectors


async def question_relevance(client, question, documents, model, trace):
    query, vectors = await embed_question_and_snippets(client, question, documents, model, trace)
    return {doc['doc_id']: cosine(query, vectors[doc['doc_id']])
            if doc['doc_id'] in vectors else None for doc in documents}
