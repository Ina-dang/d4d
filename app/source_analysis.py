"""수집 메타데이터는 보존하고 원문 주장·번역과 문서 간 의미 유사도를 생성한다."""

import json
import re
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import AnalysisError

PROMPTS = Path(__file__).parent / 'prompts'
BLOCK_CHARS = 6000
PAIR_CHARS = 18000
QUOTE_CHARS = 1600


class Schema(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class ClaimDraft(Schema):
    paragraph_id: str
    original_quote: str = Field(min_length=1, max_length=QUOTE_CHARS)
    translated_quote: str = Field(min_length=1, max_length=QUOTE_CHARS)
    expression: Literal['예정', '추정', '부정', '미확인', '가능', '발표']
    event_date: date | None


class Extraction(Schema):
    claims: list[ClaimDraft] = Field(max_length=12)


class Similarity(Schema):
    similarity: float | None = Field(ge=0, le=1, strict=True)


def request(model, schema, prompt_name, data):
    return {
        'model': model, 'stream': False, 'think': False, 'keep_alive': '30s',
        'truncate': False, 'shift': False, 'format': schema.model_json_schema(),
        'options': {'temperature': 0, 'seed': 43, 'num_gpu': 0,
                    'num_ctx': 16384, 'num_predict': 4096, 'num_batch': 32},
        'messages': [
            {'role': 'system', 'content': (PROMPTS / prompt_name).read_text(encoding='utf-8')},
            {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)},
        ],
    }


async def generate(client, schema, payload, trace):
    record = {'request': payload, 'response': None}
    trace.append(record)
    raw = await client.chat(payload)
    record['response'] = raw
    if raw.get('done') is not True or raw.get('done_reason') != 'stop':
        raise AnalysisError('원문 분석 출력이 잘렸거나 완료되지 않았습니다. 결과를 사용하지 않습니다.')
    try:
        return schema.model_validate_json(raw['message']['content'])
    except (ValidationError, KeyError, TypeError):
        raise AnalysisError('원문 분석 응답이 지정된 JSON 명세와 맞지 않습니다.') from None


def paragraph_blocks(document):
    paragraphs = []
    seen = set()
    raw_paragraphs = document.get('paragraphs')
    if not isinstance(raw_paragraphs, list):
        raise AnalysisError('분석할 원문 문단 목록이 없습니다.')
    for p in raw_paragraphs:
        if not isinstance(p, dict):
            raise AnalysisError('원문 문단 형식이 올바르지 않습니다.')
        pid = p.get('paragraph_id') or p.get('id')
        text = p.get('raw_text') or p.get('text')
        if not isinstance(pid, str) or not isinstance(text, str) or not text.strip() or pid in seen:
            raise AnalysisError('원문 문단 ID·본문이 누락되었거나 중복됩니다.')
        seen.add(pid)
        # 긴 문단도 삭제하거나 자르지 않고 모두 입력한다. 인용은 원래 문단 ID로 검증한다.
        for start in range(0, len(text), BLOCK_CHARS - QUOTE_CHARS):
            paragraphs.append({'paragraph_id': pid, 'raw_text': text[start:start + BLOCK_CHARS]})
            if start + BLOCK_CHARS >= len(text):
                break
    if not paragraphs:
        raise AnalysisError('분석할 원문 문단이 없습니다. 검색 요약으로 대체하지 않습니다.')
    blocks, block, size = [], [], 0
    for p in paragraphs:
        if block and size + len(p['raw_text']) > BLOCK_CHARS:
            blocks.append(block)
            block, size = [], 0
        block.append(p)
        size += len(p['raw_text'])
    if block:
        blocks.append(block)
    return blocks


def complete_paragraphs(document):
    """기존 문단은 유지하며 전체 정제 본문의 미포함 구간을 보충한다."""
    # 기존 ID·본문 검사를 먼저 수행한다.
    paragraph_blocks(document)
    full = document.get('article_text')
    source = document['paragraphs']
    supplements = []
    if isinstance(full, str) and full.strip():
        joined = ''.join(p.get('raw_text') or p.get('text') for p in source)
        if re.sub(r'\s+', '', full) != re.sub(r'\s+', '', joined):
            ids = {p.get('paragraph_id') or p.get('id') for p in source}
            pid = f"{document['doc_id']}-body"
            while pid in ids:
                pid += '-full'
            # 원래 문단 ID를 바꾸지 않고 전체 본문용 추가 근거를 보존한다.
            supplements.append({'document_id': document['doc_id'],
                                'paragraph_id': pid, 'raw_text': full})
    return {**document, 'paragraphs': [*source, *supplements]}, supplements


async def analyze_sources(client, question, documents, model, trace=None):
    """문서별 추출 후 각 문서 쌍을 한 번 평가하고 대칭 sim으로 반환한다.

    sim은 추출한 질문 관련 주장들의 의미 유사도이며 사실 일치·모순 판정이 아니다.
    claims가 없거나 비교 자료가 과다하면 null과 경고를 남긴다.
    """
    trace = [] if trace is None else trace
    if not isinstance(documents, list) or any(not isinstance(d, dict) for d in documents):
        raise AnalysisError('수집 문서 목록 형식이 올바르지 않습니다.')
    ids = [d.get('doc_id') for d in documents]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise AnalysisError('수집 문서 ID가 누락되었거나 중복됩니다.')
    docs, claims, warnings, supplemental_paragraphs = [], [], [], []
    by_document = {}
    for document in documents:
        did = document['doc_id']
        weight, score = document.get('credibility_weight'), document.get('score')
        for value in (weight, score):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (float, int))
                                      or not 0 <= value <= 1):
                raise AnalysisError('수집 가중치 또는 검색 관련도가 0~1 범위를 벗어났습니다.')
        docs.append({'id': did, 'country': document.get('country'),
                     'weight': weight, 'score': score, 'sim': {}})
        extracted, seen = [], set()
        complete, supplements = complete_paragraphs(document)
        supplemental_paragraphs.extend(supplements)
        if supplements:
            warnings.append(f'{did}: 수집 문단 외의 전체 본문도 추가 근거 문단으로 분석했습니다.')
        for block in paragraph_blocks(complete):
            payload = request(model, Extraction, 'source_extract.txt', {
                'question': question, 'query': document.get('query', ''),
                'language': document.get('language', 'unknown'), 'paragraphs': block})
            result = await generate(client, Extraction, payload, trace)
            for c in result.claims:
                # 인용은 이번 호출에 전달한 해당 문단에 실제로 존재해야 한다.
                if not any(p['paragraph_id'] == c.paragraph_id
                           and c.original_quote in p['raw_text'] for p in block):
                    raise AnalysisError('LLM 인용이 해당 원문 문단에 존재하지 않습니다.')
                if not any('\uac00' <= char <= '\ud7a3' for char in c.translated_quote):
                    raise AnalysisError('주장 번역에 한국어가 없습니다.')
                key = (c.original_quote, c.translated_quote, c.expression)
                if key in seen:
                    continue
                seen.add(key)
                claim = {
                    'claim_id': f'{did}-c{len(extracted) + 1}', 'document_id': did,
                    'tier': document.get('tier'),
                    'event_date': c.event_date.isoformat() if c.event_date else None,
                    'paragraph_id': c.paragraph_id, 'original_quote': c.original_quote,
                    'translated_quote': c.translated_quote, 'expression': c.expression,
                }
                extracted.append(claim)
        by_document[did] = extracted
        claims.extend(extracted)
        if not extracted:
            warnings.append(f'{did}: 질문 관련 주장을 추출하지 못했습니다.')

    for a, b in combinations(docs, 2):
        left, right = by_document[a['id']], by_document[b['id']]
        score = None
        # 번역된 주장·뉘앙스를 모두 비교한다. 일부 주장만 임의 선택하지 않는다.
        pair = {'left': [{'text': c['translated_quote'], 'expression': c['expression']} for c in left],
                'right': [{'text': c['translated_quote'], 'expression': c['expression']} for c in right]}
        if left and right and len(json.dumps(pair, ensure_ascii=False)) <= PAIR_CHARS:
            result = await generate(client, Similarity,
                request(model, Similarity, 'source_similarity.txt', pair), trace)
            score = result.similarity
            if score is None:
                warnings.append(f"{a['id']}–{b['id']}: 모델이 sim을 판단하지 못했습니다.")
        else:
            warnings.append(f"{a['id']}–{b['id']}: 주장 부족 또는 비교 입력 한도 초과로 sim 미산출.")
        a['sim'][b['id']] = score
        b['sim'][a['id']] = score
    return {'docs': docs, 'claims': claims, 'warnings': warnings,
            'analysis_paragraphs': supplemental_paragraphs}
