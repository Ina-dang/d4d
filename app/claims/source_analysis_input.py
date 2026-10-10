"""수집 JSON을 읽고 신뢰도 함수에 전달할 필드만 내보낸다."""

import re
import unicodedata

from app.core.errors import AnalysisError

DOC_FIELDS = ('id', 'country', 'weight', 'sim')
CLAIM_FIELDS = ('claim_id', 'document_id', 'tier', 'event_date',
                'paragraph_id', 'translated_quote')


def analysis_input(payload):
    if not isinstance(payload, dict):
        raise AnalysisError('수집 결과는 JSON 객체여야 합니다.')
    output = payload.get('output', payload)
    if not isinstance(output, dict):
        raise AnalysisError('수집 결과 output은 객체여야 합니다.')
    user_input = payload.get('input') or {}
    if not isinstance(user_input, dict):
        raise AnalysisError('수집 질문 형식이 올바르지 않습니다.')
    question = user_input.get('question') or output.get('korean_question') or output.get('event')
    if not isinstance(question, str) or not question.strip():
        raise AnalysisError('수집 결과에 question 또는 korean_question이 필요합니다.')
    if 'by_country' in output:
        countries = output['by_country']
        if not isinstance(countries, dict):
            raise AnalysisError('by_country는 국가별 문서 배열이어야 합니다.')
        documents = []
        for country, entries in countries.items():
            if not isinstance(entries, list) or any(not isinstance(d, dict) for d in entries):
                raise AnalysisError('by_country의 각 국가는 문서 객체 배열이어야 합니다.')
            for document in entries:
                # 수집 그룹은 검색 대상이고 country는 출처 국가다.
                # GLOBAL 매체가 US 그룹에 들어가는 기존 수집 결과도 보존한다.
                documents.append({**document, 'country': document.get('country') or country})
    else:
        documents = output.get('documents') or output.get('all_documents') or []
    if not isinstance(documents, list) or not documents or any(
            not isinstance(d, dict) for d in documents):
        raise AnalysisError('분석할 수집 문서가 없습니다.')
    return question.strip(), documents


def relevance_terms(text):
    """한국어 번역과 질문의 어휘 겹침을 비교한다. 의미 판정 점수가 아니다."""
    text = unicodedata.normalize('NFKC', text).casefold()
    terms = set()
    for word in re.findall(r'[가-힣]+|[a-z0-9]+', text):
        if re.fullmatch(r'[가-힣]+', word):
            terms.update(word[index:index + 2] for index in range(len(word) - 1))
        elif len(word) > 1:
            terms.add(word)
    return terms


def representative_claims(result):
    """검토된 주장 중 질문 어휘가 가장 많이 겹치는 하나를 기사별로 고른다."""
    terms = relevance_terms(result.get('analysis_question') or '')
    grouped = {}
    for claim in result['claims']:
        grouped.setdefault(claim['document_id'], []).append(claim)
    selected = []
    for doc in result['docs']:
        candidates = grouped.get(doc['id'], [])
        if candidates:
            # 같은 점수면 추출 순서를 보존한다. ID와 인용을 재작성하지 않는다.
            selected.append(max(candidates, key=lambda claim: len(
                terms & relevance_terms(claim['translated_quote']))))
    return selected


def verification_selection(result):
    selected = representative_claims(result)
    represented = {claim['document_id'] for claim in selected}
    return {'method': 'question_lexical_overlap_then_extraction_order',
            'claims_per_document': 1, 'analyzed_claim_count': len(result['claims']),
            'exported_claim_count': len(selected),
            'selected_claim_ids': [claim['claim_id'] for claim in selected],
            'documents_without_claims': [doc['id'] for doc in result['docs']
                                         if doc['id'] not in represented]}


def verification_input(result):
    """요청 필드와 기사당 대표 주장 하나만 전달한다. 전체 주장은 상세 기록에 둔다."""
    return {
        'docs': [{key: doc[key] for key in DOC_FIELDS} for doc in result['docs']],
        'claims': [{key: claim[key] for key in CLAIM_FIELDS}
                   for claim in representative_claims(result)],
    }
