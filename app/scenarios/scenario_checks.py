"""실제 시나리오의 공유 형식·문서 보존·sim 대칭·원문 근거를 검사한다."""

import math
from collections import Counter
from datetime import date

from app.claims.source_analysis_input import (
    CLAIM_FIELDS,
    DOC_FIELDS,
    analysis_input,
    verification_input,
)
from app.collection.collection_export import COLLECTION_DOC_FIELDS
from frame.official_sources import is_official_source


def check_scenario(job, collection, verification, analysis):
    question, documents = analysis_input(collection)
    ids = {document['doc_id'] for document in documents}
    docs = {document['id']: document for document in verification['docs']}
    original_docs = {document['doc_id']: document for entries in job['output']['by_country'].values()
                     for document in entries}
    originals = {claim['claim_id']: claim for claim in analysis['claims']}
    paragraphs = {p['paragraph_id']: p['raw_text'] for p in analysis['analysis_paragraphs']}
    per_doc = Counter(claim['document_id'] for claim in verification['claims'])
    checks = {
        'collection_root_contract': set(collection) == {'reference_date', 'korean_question', 'total_count', 'by_country'},
        'collection_document_contract': all(set(d) == set(COLLECTION_DOC_FIELDS) for d in documents),
        'collection_count_and_unique_ids': collection['total_count'] == len(documents) == len(ids),
        'question_preserved': question == job['input']['question'].strip() == analysis['analysis_question'],
        'source_fields_preserved': all(all(d[key] == original_docs[d['doc_id']].get(key)
                                          for key in COLLECTION_DOC_FIELDS) for d in documents),
        'verification_root_contract': set(verification) == {'docs', 'claims'},
        'verification_fields': all(set(d) == set(DOC_FIELDS) for d in verification['docs']) and
            all(set(c) == set(CLAIM_FIELDS) for c in verification['claims']),
        'all_collected_articles_retained': len(verification['docs']) == len(ids) and set(docs) == ids,
        'export_matches_details': verification == verification_input(analysis),
        'weight_and_country_preserved': all(docs[d['doc_id']]['weight'] == d['credibility_weight'] and
                                            docs[d['doc_id']]['country'] == d['country'] for d in documents),
        'representative_max_one_per_article': all(count == 1 for count in per_doc.values()) and set(per_doc) <= ids,
        'unique_export_claim_ids': len(verification['claims']) == len({c['claim_id'] for c in verification['claims']}),
        'claim_tier_preserved': all(c['tier'] == original_docs[c['document_id']]['tier'] for c in verification['claims']),
        'event_dates_nullable_or_iso': all(c['event_date'] is None or date.fromisoformat(c['event_date'])
                                           for c in verification['claims']),
        'claim_quote_and_paragraph_grounded': all(c['claim_id'] in originals and
            originals[c['claim_id']]['original_quote'] in paragraphs.get(c['paragraph_id'], '') and
            any(originals[c['claim_id']]['original_quote'] in (original_docs[c['document_id']].get(field) or '')
                for field in ('text_snippet', 'article_text')) for c in verification['claims']),
        'sim_all_other_documents_no_self': all(isinstance(d['sim'], dict) and
            set(d['sim']) == ids - {d['id']} for d in verification['docs']),
        'sim_reciprocal_and_finite': all(value == docs[other]['sim'][did] and
            (value is None or (not isinstance(value, bool) and isinstance(value, (int, float))
                              and math.isfinite(value) and 0 <= value <= 1))
            for did, d in docs.items() for other, value in d['sim'].items()),
    }
    filtering = job['output'].get('filtering', {})
    source_countries = dict(Counter(d['country'] for d in documents))
    official_counts = {country: sum(is_official_source(d['url'], country) for d in documents)
                       for country in ('CN', 'TW')}
    quality = [*analysis.get('warnings', [])]
    if not source_countries.get('CN') or not source_countries.get('TW'):
        quality.append('중국·대만 소재 출처 중 하나 이상이 수집되지 않았습니다. 양측 공식 입장 확보를 뜻하지 않습니다.')
    if any(count == 0 for count in official_counts.values()):
        quality.append('중국·대만 정부 웹사이트 원문 중 하나 이상이 확보되지 않았습니다. 언론·SNS로 대체했다고 보지 않습니다.')
    quality.append('SNS·영상의 수집 분류에 공식이라는 이름이 있어도 실제 계정 신원은 검증되지 않았습니다.')
    return {'all_checks_passed': all(checks.values()), 'checks': checks,
        'counts': {'collected_articles': len(documents), 'analyzed_claims': len(analysis['claims']),
                   'verification_docs': len(docs), 'representative_claims': len(verification['claims']),
                   'unique_document_pairs': len(ids) * (len(ids) - 1) // 2,
                   'sim_entries_per_document': len(ids) - 1,
                   'source_country_counts': source_countries,
                   'official_government_source_counts': official_counts,
                   'language_counts': dict(Counter(d['language'] for d in documents)),
                   'articles_without_claims': sorted(ids - set(per_doc)),
                   'article_fallback_count': len(analysis.get('article_fallback', []))},
        'filtering': {'rejected_counts': filtering.get('rejected_counts'),
                      'body_recovery': filtering.get('body_recovery')},
        'timings': {'search_and_collection_seconds': job['timings']['total_seconds'],
                    'analysis_seconds': analysis['timings']['total_seconds'],
                    'through_verification_input_seconds': round(job['timings']['total_seconds'] +
                                                               analysis['timings']['total_seconds'], 3),
                    'reliability_and_report_seconds': None},
        'quality_limits': quality, 'report_status': 'awaiting_current_reliability_result'}
