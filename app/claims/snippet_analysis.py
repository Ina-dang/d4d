"""수집 snippet의 주장·번역과 문서 유사도·질문 관련도를 만든다."""

import time

from app.core.analysis_timing import summarize_timings
from app.claims.article_fallback import recover_from_article_text
from app.core.errors import AnalysisError
from app.claims.snippet_batch import extract_group, snippet_groups
from app.claims.snippet_quotes import snippet_quotes, substantive_quotes
from app.claims.source_analysis import paragraph_blocks
from app.claims.source_analysis_input import verification_selection
from app.claims.source_embeddings import cosine, embed_question_and_snippets

SNIPPET_MAX_CHARS = 6000


async def analyze_snippets(client, question, documents, model, embedding_model,
                           trace=None, progress=None):
    started = time.perf_counter()
    trace = [] if trace is None else trace
    if not isinstance(question, str) or not question.strip():
        raise AnalysisError('질문 관련도를 계산할 사용자 질문이 필요합니다.')
    similarity_target = getattr(client, 'similarity_target', 'other_documents')
    if similarity_target not in {'user_question', 'other_documents'}:
        raise AnalysisError('유사도 대상은 user_question 또는 other_documents여야 합니다.')
    if not isinstance(documents, list) or any(not isinstance(d, dict) for d in documents):
        raise AnalysisError('수집 문서 목록 형식이 올바르지 않습니다.')
    ids = [d.get('doc_id') for d in documents]
    if any(not isinstance(did, str) or not did.strip() for did in ids) or len(ids) != len(set(ids)):
        raise AnalysisError('수집 문서 ID가 누락되었거나 중복됩니다.')
    docs, claims, warnings, paragraphs = [], [], [], []
    prepared = []
    for document in documents:
        snippet = document.get('text_snippet')
        if snippet is None:
            snippet = ''
        if not isinstance(snippet, str):
            raise AnalysisError('text_snippet은 문자열 또는 null이어야 합니다.')
        document = {**document, 'text_snippet': snippet}
        if len(snippet) > SNIPPET_MAX_CHARS:
            raise AnalysisError('text_snippet이 6,000자 입력 한도를 초과했습니다. 중간을 자르지 않습니다.')
        if document.get('title') is not None and not isinstance(document['title'], str):
            raise AnalysisError('문서 제목은 문자열이어야 합니다.')
        weight = document.get('credibility_weight')
        if weight is not None and (isinstance(weight, bool) or not isinstance(weight, (int, float))
                                   or not 0 <= weight <= 1):
            raise AnalysisError('수집 가중치가 0~1 범위를 벗어났습니다.')
        did = document['doc_id']
        docs.append({'id': did, 'country': document.get('country'), 'weight': weight,
                     'sim': None if similarity_target == 'user_question' else {}})
        # 수집기에서 문단 ID를 제거했으므로 분석 근거 ID를 명시적으로 새로 만든다.
        # snippet 근거를 기사 전체의 원문 문단으로 가장하지 않는다.
        evidence = {'document_id': did, 'paragraph_id': f'{did}-snippet-p1',
                    'raw_text': snippet, 'origin': 'text_snippet'}
        blocks = paragraph_blocks({'paragraphs': [evidence]}) if snippet.strip() else []
        if blocks:
            paragraphs.append(evidence)
            candidates = snippet_quotes(blocks[0])
            excluded = len(candidates) - len(substantive_quotes(candidates))
            if excluded:
                warnings.append(f'{did}: 링크·참고 목록 {excluded}개를 주장 후보에서 제외했습니다. '
                                '기사와 snippet 원문은 보존했습니다.')
        prepared.append((document, blocks))

    extraction_total = sum(len(blocks) for _, blocks in prepared)
    comparison_total = (len(docs) if similarity_target == 'user_question'
                        else len(docs) * (len(docs) - 1) // 2)
    total = extraction_total + comparison_total
    completed, extracted_blocks = 0, 0

    def emit(stage, detail, stage_completed=0, stage_total=0):
        if progress is not None:
            progress({'stage': stage, 'completed': completed, 'total': total, 'detail': detail,
                      'stage_completed': stage_completed, 'stage_total': stage_total,
                      'received_chars': 0, 'similarity_target': similarity_target})

    warnings.append('snippet을 우선 분석하고 주장이 없는 문서만 원문 후보를 검색합니다. '
                    '원문 전체의 모든 주장·날짜를 평가하는 분석은 아닙니다.')
    emit('extracting', 'snippet 주장 추출·번역을 시작합니다.', stage_total=extraction_total)
    index = 0
    for group in snippet_groups(prepared, getattr(client, 'batch_snippets', False)):
        detail = f'문서 {index + 1}~{index + len(group)}/{len(documents)} · snippet 주장 추출·번역'
        extracted = await extract_group(client, model, question, group, trace,
            lambda message, detail=detail, done=extracted_blocks: emit(
                'extracting', f'{detail} · {message}', done, extraction_total))
        for (document, blocks), (result, repairs) in zip(group, extracted, strict=True):
            index += 1
            did = document['doc_id']
            seen, document_claims = set(), []
            for claim in result.claims:
                key = (claim.original_quote, claim.translated_quote, claim.expression)
                if key in seen:
                    continue
                seen.add(key)
                document_claims.append({
                    'claim_id': f'{did}-c{len(document_claims) + 1}', 'document_id': did,
                    'tier': document.get('tier'),
                    'event_date': claim.event_date.isoformat() if claim.event_date else None,
                    'paragraph_id': claim.paragraph_id, 'original_quote': claim.original_quote,
                    'translated_quote': claim.translated_quote, 'expression': claim.expression,
                })
            if repairs:
                warnings.append(f'{did}: 해당 문서가 포함된 추출 결과를 {repairs}회 재추출 후 확인했습니다.')
            completed += len(blocks)
            extracted_blocks += len(blocks)
            emit('extracting', detail, extracted_blocks, extraction_total)
            claims.extend(document_claims)
            if not document_claims:
                warnings.append(f'{did}: snippet이 비어 있거나 질문 관련 주장이 없습니다.')

    # snippet 추출을 마친 뒤 임베딩한다. 필요한 원문 보완만 LLM으로 돌아간다.
    await client.unload(model)
    effective_documents = [document for document, _ in prepared]
    claimed_ids = {claim['document_id'] for claim in claims}
    missing = [document for document in effective_documents if document['doc_id'] not in claimed_ids]
    extraction_total += len(missing)
    total += len(missing)
    emit('comparing', ('사용자 질문과 각 text_snippet의 관련도를 계산합니다.'
         if similarity_target == 'user_question' else '모든 text_snippet의 문서 간 유사도를 계산합니다.'),
         stage_total=comparison_total)
    query, vectors = await embed_question_and_snippets(
        client, question, effective_documents, embedding_model, trace)
    recovered, body_evidence, fallback, body_vectors = await recover_from_article_text(
        client, question, missing, query, model, embedding_model, trace,
        lambda message: emit('extracting', message, extracted_blocks, extraction_total))
    paragraphs.extend(body_evidence)
    vectors.update(body_vectors)
    for document in missing:
        did = document['doc_id']
        result = recovered.get(did)
        if result:
            for claim in result.claims:
                claims.append({'claim_id': f'{did}-c1', 'document_id': did,
                    'tier': document.get('tier'),
                    'event_date': claim.event_date.isoformat() if claim.event_date else None,
                    'paragraph_id': claim.paragraph_id, 'original_quote': claim.original_quote,
                    'translated_quote': claim.translated_quote, 'expression': claim.expression,
                    'evidence_origin': 'article_text'})
            warnings.append(f'{did}: snippet에 주장이 없어 원문의 관련 문장에서 대표 주장을 보완했습니다. '
                            'sim도 보완한 원문 인용으로 계산했습니다.')
        else:
            reason = next(item['status'] for item in fallback if item['document_id'] == did)
            warnings.append(f'{did}: 원문 보완 후에도 대표 주장이 없습니다 ({reason}). 문서는 유지했습니다.')
        completed += 1
        extracted_blocks += 1
        emit('extracting', f'{did}: 원문 보완 확인 완료', extracted_blocks, extraction_total)
    emit('comparing', '기사별 분석 근거의 유사도를 계산합니다.', stage_total=comparison_total)
    scores = {doc['id']: cosine(query, vectors[doc['id']]) if doc['id'] in vectors else None
              for doc in docs}
    compared = 0
    for doc in docs:
        score = scores[doc['id']]
        if score is None:
            warnings.append(f"{doc['id']}: 빈 snippet으로 질문 관련도를 계산하지 못했습니다.")
        if similarity_target == 'user_question':
            doc['sim'] = score
            compared += 1
            completed += 1
            emit('comparing', f'문서 {compared}/{comparison_total}개 질문 관련도 계산 완료',
                 compared, comparison_total)
    if similarity_target == 'other_documents':
        for index, left in enumerate(docs):
            for right in docs[index + 1:]:
                left_id, right_id = left['id'], right['id']
                score = cosine(vectors[left_id], vectors[right_id]) if (
                    left_id in vectors and right_id in vectors) else None
                left['sim'][right_id] = right['sim'][left_id] = score
                compared += 1
                completed += 1
                emit('comparing', f'문서 {compared}/{comparison_total}쌍 유사도 계산 완료',
                     compared, comparison_total)
        if not comparison_total:
            emit('comparing', '비교할 다른 문서가 없습니다.', 0, 0)
        if any(doc['id'] not in vectors for doc in docs):
            warnings.append('빈 snippet이 포함된 문서 쌍의 sim은 null입니다.')
    result = {
        'docs': docs, 'claims': claims, 'warnings': warnings, 'analysis_paragraphs': paragraphs,
        'analysis_scope': 'text_snippet_with_article_text_fallback' if recovered else 'text_snippet',
        'similarity_method': 'clipped_cosine',
        'similarity_target': similarity_target,
        'similarity_input': 'text_snippet_or_article_text_fallback' if recovered else 'text_snippet',
        'similarity_sources': {doc['id']: 'article_text' if doc['id'] in recovered else 'text_snippet'
                               for doc in docs},
        'article_fallback': fallback,
        'analysis_question': question,
        'question_relevance': scores,
        'embedding_model': embedding_model,
        'timings': {**summarize_timings(trace),
                    'analysis_seconds': round(time.perf_counter() - started, 3)},
    }
    from app.claims.source_terminology import normalize_source_terminology

    normalize_source_terminology(result)
    result['timings']['analysis_seconds'] = round(time.perf_counter() - started, 3)
    result['verification_selection'] = verification_selection(result)
    return result
