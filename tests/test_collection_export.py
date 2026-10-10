import pytest

from app.collection.collection_export import COLLECTION_DOC_FIELDS, collection_export
from app.core.errors import AnalysisError


def test_clean_export_drops_duplicate_fields_and_job_metadata_without_modifying_original():
    document = {'doc_id': 'd1', 'country': 'GLOBAL', 'text_snippet': '핵심 문장',
                'article_text': '전체 본문', 'raw_content': '전체 본문', 'paragraphs': ['전체 본문']}
    job = {'id': 'job', 'input': {'question': '질문'}, 'output': {'total_count': 99,
           'by_country': {'US': [document]}}}
    exported = collection_export(job)
    assert set(exported) == {'reference_date', 'korean_question', 'total_count', 'by_country'}
    assert set(exported['by_country']['US'][0]) == set(COLLECTION_DOC_FIELDS)
    assert exported['total_count'] == 1 and exported['by_country']['US'][0]['country'] == 'GLOBAL'
    assert document['raw_content'] == '전체 본문' and document['paragraphs'] == ['전체 본문']


@pytest.mark.parametrize('countries', [{'CN': {}}, {'CN': [None]}, {'CN': [{}]},
    {'CN': [{'doc_id': 'same'}], 'TW': [{'doc_id': 'same'}]}])
def test_invalid_collection_objects_and_duplicate_ids_fail(countries):
    with pytest.raises(AnalysisError):
        collection_export({'by_country': countries})
