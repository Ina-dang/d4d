"""snippet 주장 없는 기사만 원문 문장을 검색해 대표 주장을 보완한다."""

import re

from app.claims.claim_quality import TAIWAN_TERMS, claim_rejection_reason
from app.claims.claim_validation import verified_extraction
from app.claims.snippet_quotes import (
    SnippetExtraction,
    grounded_extraction,
    snippet_quotes,
    substantive_quotes,
)
from app.claims.source_analysis import QUOTE_CHARS, request
from app.claims.source_analysis_input import relevance_terms
from app.claims.source_embeddings import cosine, embed_documents
from app.core.errors import AnalysisError

MAX_EMBED_CANDIDATES = 48
MAX_SELECTED_CANDIDATES = 3
INPUT_COST = 2200
BOILERPLATE = re.compile(
    r'^(?:Subscribed with|Logout and Login|Account subscription|Unlock these|'
    r'Products you|Additional Subscription|Account Settings|Need help with your subscription|'
    r'Voluntary Subscription|Hana Bank|Delivering Valuable News|'
    r'This video was produced using AI|Your [\'’]|Subscribe\b|구독\s*안내|로그인\b|'
    r'\d[\d.,]*[KMB]?\s+(?:subscribers|likes|views)|Posted\s*:|Channel\s*:)', re.I)


def text_cost(text):
    return len(text) + 2 * len(re.findall(r'[\u3400-\u9fff\uac00-\ud7a3\u3040-\u30ff]', text))


def search_terms(text):
    terms = relevance_terms(text)
    for word in re.findall(r'[\u3400-\u9fff\u3040-\u30ff]+', text):
        terms.update(word[index:index + 2] for index in range(len(word) - 1))
    return terms


def body_candidates(document, question, *, require_focus=False):
    body = document.get('article_text')
    if not isinstance(body, str) or not body.strip():
        return [], {'status': 'no_article_text', 'candidate_count': 0}
    transcript = re.search(r'^#{1,6}\s*Transcript\s*$', body, re.M | re.I)
    timestamped = len(re.findall(r'^\s*\[\d{1,2}:\d{2}(?::\d{2})?\]', body, re.M)) >= 3
    if transcript:
        regions = [(transcript.end(), len(body))]
    elif timestamped:
        # 자막의 타임스탬프 줄은 문장 경계가 아니다. 이어지는 원문을 그대로 연결해
        # 실제 문장 종결 부호에서 나누고, 인용 오프셋은 전체 본문 기준으로 유지한다.
        regions = [(0, len(body))]
    else:
        boundaries = [0, *[match.end() for match in re.finditer(r'\n\s*\n', body)], len(body)]
        regions = list(zip(boundaries, boundaries[1:], strict=False))
    candidates, oversized = [], 0
    for start, end in regions:
        raw = body[start:end]
        if not raw.strip() or re.match(r'^\s*#{1,6}\s', raw):
            continue
        quotes = snippet_quotes([{'paragraph_id': 'source', 'raw_text': raw}], reject_oversize=False)
        cursor = 0
        located = []
        for quote in quotes:
            text = quote['original_quote']
            offset = raw.index(text, cursor)
            cursor = offset + len(text)
            located.append((start + offset, start + cursor, quote))
        for index, (quote_start, quote_end, quote) in enumerate(located):
            text = quote['original_quote']
            if len(text) > QUOTE_CHARS:
                oversized += 1
                continue
            visible = re.sub(r'\[\d{1,2}:\d{2}(?::\d{2})?\]', '', text).strip(' \n▶')
            if (len(visible) < 8 or visible.endswith(('?', '？'))
                    or BOILERPLATE.match(visible) or visible.startswith('#')
                    or not substantive_quotes([quote]) or claim_rejection_reason(text)
                    or (require_focus and '대만' in question and not TAIWAN_TERMS.search(text))):
                continue
            before = located[max(0, index - 1)][0]
            after = located[min(len(located) - 1, index + 1)][1]
            context = body[before:after]
            # 문장은 자르지 않는다. 큰 문맥은 정확한 인용 문장 하나로 제한한다.
            if text_cost(context) + text_cost(text) > INPUT_COST:
                before, after, context = quote_start, quote_end, text
            candidates.append({
                'quote_id': len(candidates) + 1, 'original_quote': text,
                'paragraph_id': f"{document['doc_id']}-article-at{quote_start}",
                'evidence': {'document_id': document['doc_id'],
                    'paragraph_id': f"{document['doc_id']}-article-at{quote_start}",
                    'raw_text': context, 'origin': 'article_text',
                    'source_start': before, 'source_end': after,
                    'quote_start': quote_start, 'quote_end': quote_end},
            })
    count = len(candidates)
    if count > MAX_EMBED_CANDIDATES:
        source_query = document.get('query')
        terms = search_terms(question + ' ' + (source_query if isinstance(source_query, str) else ''))
        candidates = sorted(candidates, key=lambda item: len(
            terms & search_terms(item['original_quote'])), reverse=True)[:MAX_EMBED_CANDIDATES]
    return candidates, {'status': 'candidates_ready' if candidates else 'no_body_candidates',
                        'candidate_count': count, 'embedded_candidate_count': len(candidates),
                        'lexical_prefilter_applied': count > MAX_EMBED_CANDIDATES,
                        'oversized_sentences_excluded': oversized,
                        'transcript_preferred': transcript is not None or timestamped}


async def recover_from_article_text(client, question, documents, query, model,
                                   embedding_model, trace, notify):
    prepared, diagnostics = [], []
    for document in documents:
        candidates, record = body_candidates(document, question,
            require_focus=getattr(client, 'require_claim_focus', False))
        diagnostics.append({'document_id': document['doc_id'], **record})
        if candidates:
            prepared.append((document, candidates, diagnostics[-1]))
    if not prepared:
        return {}, [], diagnostics, {}
    inputs = [{
        'doc_id': f"{document['doc_id']}-fallback-q{candidate['quote_id']}",
        'title': '', 'text_snippet': candidate['original_quote']}
        for document, candidates, _ in prepared for candidate in candidates]
    notify('원문 후보 문장과 사용자 질문의 임베딩 유사도 계산 중')
    vectors = await embed_documents(client, inputs, embedding_model, trace)
    ranked = []
    for document, candidates, record in prepared:
        for candidate in candidates:
            key = f"{document['doc_id']}-fallback-q{candidate['quote_id']}"
            candidate['vector'] = vectors[key]
            candidate['question_similarity'] = cosine(query, vectors[key])
        ordered = sorted(candidates, key=lambda item: item['question_similarity'], reverse=True)
        selected, cost = [], 0
        for candidate in ordered:
            item_cost = text_cost(candidate['original_quote']) + text_cost(candidate['evidence']['raw_text'])
            if cost + item_cost > INPUT_COST:
                continue
            selected.append(candidate)
            cost += item_cost
            if len(selected) == MAX_SELECTED_CANDIDATES:
                break
        record['ranked_candidates'] = [
            {'quote_id': c['quote_id'], 'paragraph_id': c['paragraph_id'],
             'question_similarity': c['question_similarity']} for c in ordered]
        if selected:
            ranked.append((document, selected, record))
        else:
            record['status'] = 'candidate_input_too_large'
    if not ranked:
        return {}, [], diagnostics, {}
    # 후보 임베딩을 모두 마친 뒤 LLM을 다시 사용한다. 두 모델을 함께 유지하지 않는다.
    await client.unload(embedding_model)
    recovered, evidence, recovered_vectors = {}, [], {}
    for document, candidates, record in ranked:
        did = document['doc_id']
        block = [candidate['evidence'] for candidate in candidates]
        quotes = [{key: candidate[key] for key in ('quote_id', 'paragraph_id', 'original_quote')}
                  for candidate in candidates]
        payload = request(model, SnippetExtraction, 'source_article_fallback.txt', {
            'document_id': did, 'question': question,
            'quotes': [{key: value for key, value in quote.items() if key != 'paragraph_id'}
                       for quote in quotes], 'context': [p['raw_text'] for p in block]})
        payload['format']['properties']['claims']['maxItems'] = 1
        payload['format']['$defs']['SnippetClaim']['properties']['quote_id']['enum'] = [
            quote['quote_id'] for quote in quotes]
        payload['options'].update(num_ctx=4096, num_predict=768)
        if getattr(client, 'force_cpu', False):
            payload['options']['num_gpu'] = 0

        def ground(selection, quotes=quotes):
            if len(selection.claims) > 1:
                raise AnalysisError('원문 보완은 문서당 대표 주장 하나만 허용합니다.')
            return grounded_extraction(selection, quotes)

        notify(f'{did}: 유사도가 높은 원문 후보에서 대표 주장 추출·번역 중')
        result, repairs = await verified_extraction(
            client, model, payload, block, trace, lambda message, did=did: notify(f'{did}: {message}'),
            initial_schema=SnippetExtraction, prepare_initial=ground, fixed_paragraph_ids=True)
        if len(result.claims) > 1:
            raise AnalysisError('원문 보완 캐시에 대표 주장이 두 개 이상 있습니다.')
        record.update(status='recovered' if result.claims else 'no_relevant_claim', repair_count=repairs)
        record['selected_paragraph_ids'] = [claim.paragraph_id for claim in result.claims]
        evidence.extend(block)
        if result.claims:
            recovered[did] = result
            original = result.claims[0].original_quote
            recovered_vectors[did] = next(c['vector'] for c in candidates if c['original_quote'] == original)
    await client.unload(model)
    return recovered, evidence, diagnostics, recovered_vectors
