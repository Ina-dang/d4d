"""미검토 기사 최대 두 개를 묶고 검토된 결과는 문서별로 캐시한다."""

import re
from itertools import chain

from .claim_validation import (
    VerifiedBlock,
    find_verified_cache,
    verified_cache_key,
    verified_extraction,
)
from .errors import AnalysisError
from .snippet_quotes import (
    SnippetExtraction,
    grounded_extraction,
    snippet_quotes,
    substantive_quotes,
)
from .source_analysis import Extraction, Schema, request


class SnippetBatchExtraction(Schema):
    documents: dict[str, SnippetExtraction]


def extraction_request(client, model, question, document, block):
    quotes = substantive_quotes(snippet_quotes(block))
    payload = request(model, SnippetExtraction, 'source_snippet_extract.txt', {
        'document_id': document['doc_id'], 'question': question,
        'language': document.get('language', 'unknown'), 'quotes': model_quotes(quotes)})
    payload['options'].update(num_ctx=4096, num_predict=2048)
    if getattr(client, 'force_cpu', False):
        payload['options']['num_gpu'] = 0
    payload['format']['$defs']['SnippetClaim']['properties']['quote_id']['enum'] = [
        quote['quote_id'] for quote in quotes]
    return payload, quotes


def model_quotes(quotes):
    return [{key: value for key, value in quote.items() if key != 'paragraph_id'} for quote in quotes]


def snippet_groups(prepared, enabled):
    pending, cost = [], 0
    for row in prepared:
        text = row[0]['text_snippet']
        cjk = len(re.findall(r'[\u3400-\u9fff\uac00-\ud7a3\u3040-\u30ff]', text))
        item_cost = len(text) + 2 * cjk
        if pending and (not enabled or len(pending) == 2 or cost + item_cost > 2200
                        or not row[1] or not pending[-1][1]):
            yield pending
            pending, cost = [], 0
        pending.append(row)
        cost += item_cost
    if pending:
        yield pending


async def extract_group(client, model, question, group, trace, notify):
    ready, pending = {}, []
    for document, blocks in group:
        did = document['doc_id']
        if not blocks:
            ready[did] = (Extraction(claims=[]), 0)
            continue
        block = blocks[0]
        payload, quotes = extraction_request(client, model, question, document, block)
        if not quotes:
            ready[did] = (Extraction(claims=[]), 0)
            continue
        saved, _ = find_verified_cache(client, payload, block)
        if saved is not None:
            ready[did] = await verified_extraction(client, model, payload, block, trace, notify,
                initial_schema=SnippetExtraction,
                prepare_initial=lambda selected, quotes=quotes: grounded_extraction(selected, quotes))
        else:
            pending.append((document, block, payload, quotes))
    if len(pending) == 1:
        document, block, payload, quotes = pending[0]
        ready[document['doc_id']] = await verified_extraction(
            client, model, payload, block, trace, notify, initial_schema=SnippetExtraction,
            prepare_initial=lambda selected: grounded_extraction(selected, quotes))
    elif len(pending) == 2:
        payload = request(model, SnippetBatchExtraction, 'source_snippet_batch.txt', {
            'question': question, 'documents': [
                {'document_id': document['doc_id'], 'language': document.get('language', 'unknown'),
                 'quotes': model_quotes(quotes)} for document, _, _, quotes in pending]})
        payload['options'] = dict(pending[0][2]['options'])
        # 고정된 객체 키로 문서 ID를 강제한다. 배열의 enum만으로는 같은 ID를
        # 두 번 출력하는 것을 막을 수 없다.
        document_ids = [document['doc_id'] for document, _, _, _ in pending]
        payload['format']['properties']['documents'] = {
            'type': 'object', 'properties': {
                did: {'$ref': '#/$defs/SnippetExtraction'} for did in document_ids},
            'required': document_ids, 'additionalProperties': False}
        block = list(chain.from_iterable(entry[1] for entry in pending))
        origin_ids = []

        def ground_batch(selected):
            if set(selected.documents) != set(document_ids):
                raise AnalysisError('묶음 추출 응답에 문서 ID 누락·중복·추가가 있습니다.')
            claims = []
            for document, _, _, quotes in pending:
                selection = selected.documents[document['doc_id']]
                result = grounded_extraction(selection, quotes)
                claims.extend(result.claims)
            origin_ids.extend(claim.paragraph_id for claim in claims)
            return Extraction(claims=claims)

        trace_start = len(trace)
        result, repairs = await verified_extraction(client, model, payload, block, trace, notify,
            initial_schema=SnippetBatchExtraction, prepare_initial=ground_batch,
            fixed_paragraph_ids=True)
        if origin_ids and [claim.paragraph_id for claim in result.claims] != origin_ids:
            raise AnalysisError('묶음 재추출에서 주장의 근거 문서가 변경됐습니다.')
        cache = getattr(client, 'cache', None)
        for document, source, individual_payload, _ in pending:
            pids = {paragraph['paragraph_id'] for paragraph in source}
            extraction = Extraction(claims=[claim for claim in result.claims
                                           if claim.paragraph_id in pids])
            ready[document['doc_id']] = extraction, repairs
            if cache is not None:
                cache.write(verified_cache_key(individual_payload, source), VerifiedBlock(
                    extraction=extraction, repair_count=repairs,
                    validation_trace=trace[trace_start:]).model_dump(mode='json'))
    return [ready[document['doc_id']] for document, _ in group]
