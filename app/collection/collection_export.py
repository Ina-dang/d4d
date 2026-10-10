"""내부 수집 실행 기록과 공유용 by_country JSON을 구분한다."""

from app.core.errors import AnalysisError

COLLECTION_DOC_FIELDS = (
    'doc_id', 'title', 'url', 'score', 'score_notice', 'language', 'tier', 'source_name',
    'country', 'published_date', 'text_snippet', 'source_category', 'credibility_weight',
    'query', 'status', 'article_text',
)


def collection_export(job):
    if not isinstance(job, dict):
        raise AnalysisError('수집 결과는 JSON 객체여야 합니다.')
    output = job.get('output', job)
    if not isinstance(output, dict) or not isinstance(output.get('by_country'), dict):
        raise AnalysisError('국가별 수집 결과가 없습니다.')
    user_input = job.get('input') or {}
    if not isinstance(user_input, dict) or any(not isinstance(documents, list)
            or any(not isinstance(doc, dict) for doc in documents)
            for documents in output['by_country'].values()):
        raise AnalysisError('국가별 수집 문서·질문 형식이 올바르지 않습니다.')
    countries = {country: [{key: document.get(key) for key in COLLECTION_DOC_FIELDS}
                           for document in documents]
                 for country, documents in output['by_country'].items()}
    ids = [doc['doc_id'] for docs in countries.values() for doc in docs]
    if any(not isinstance(did, str) or not did for did in ids) or len(ids) != len(set(ids)):
        raise AnalysisError('수집 문서 ID가 누락되었거나 중복됩니다.')
    return {'reference_date': output.get('reference_date'),
            'korean_question': user_input.get('question') or output.get('korean_question')
                               or output.get('event'),
            'total_count': sum(len(documents) for documents in countries.values()),
            'by_country': countries}
