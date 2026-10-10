import asyncio
import copy
import json

import pytest
from pydantic import ValidationError

from app.errors import AnalysisError
from app.reliability_report import (
    ReliabilityResponse,
    generate_report,
    input_digest,
    report_evidence,
    report_markdown,
)
from app.source_analysis_input import verification_input


def inputs():
    documents = [{'doc_id': 'a', 'title': '발표 A', 'country': 'CN', 'tier': 2,
                  'url': 'https://example.com/a', 'source_name': 'A', 'language': 'zh',
                  'text_snippet': '甲方宣布活動。'},
                 {'doc_id': 'b', 'title': '발표 B', 'country': 'TW', 'tier': 2,
                  'url': 'https://example.com/b', 'source_name': 'B', 'language': 'zh-Hant',
                  'text_snippet': '乙方表示正在監視。'}]
    collection = {'status': 'completed', 'input': {'question': '대만해협 양측 발표'},
                  'output': {'documents': documents}}
    analysis = {'analysis_question': '대만해협 양측 발표', 'analysis_scope': 'text_snippet',
                'docs': [{'id': 'a', 'country': 'CN', 'weight': 0.5, 'sim': {'b': 0.67}},
                         {'id': 'b', 'country': 'TW', 'weight': 0.8, 'sim': {'a': 0.67}}],
                'claims': [{'claim_id': 'a-c1', 'document_id': 'a', 'tier': 2, 'event_date': None,
                            'paragraph_id': 'a-p1', 'original_quote': '甲方宣布活動。',
                            'translated_quote': '갑측은 활동을 발표했다.', 'expression': '발표'},
                           {'claim_id': 'b-c1', 'document_id': 'b', 'tier': 2, 'event_date': None,
                            'paragraph_id': 'b-p1', 'original_quote': '乙方表示正在監視。',
                            'translated_quote': '을측은 감시 중이라고 밝혔다.', 'expression': '발표'}],
                'analysis_paragraphs': [{'paragraph_id': 'a-p1', 'raw_text': '甲方宣布活動。'},
                                        {'paragraph_id': 'b-p1', 'raw_text': '乙方表示正在監視。'}],
                'warnings': []}
    response = {'claims': [{**claim, 'reliability': score, 'label': '관점 차이'}
                           for claim, score in zip(verification_input(analysis)['claims'], [0.53, 0.71], strict=True)],
                'summary': {'관점 차이': 2}, 'thresholds': {'low': 0.5, 'high': 0.75}}
    return collection, analysis, response


def draft():
    return {'key_judgment': [{'text': '양측은 서로 다른 발표를 했다.', 'claim_ids': ['a-c1', 'b-c1']}],
            'common_facts': [], 'conflicting_candidates': [],
            'source_interpretations': [{'text': '갑측은 활동을 발표했다.', 'claim_ids': ['a-c1']}],
            'analysis_limits': [{'text': '원문 전체와 독립 확인은 검토하지 않았다.', 'claim_ids': []}]}


class Model:
    def __init__(self, response=None, done_reason='stop', review_response=None):
        self.response, self.done_reason, self.calls = response or draft(), done_reason, []
        self.review_response = review_response

    async def chat(self, payload):
        self.calls.append(payload)
        if payload['format']['title'] == 'ReportChecks':
            context = json.loads(payload['messages'][1]['content'])
            content = {'checks': [{'item_id': item['item_id'], 'verdict': 'supported', 'reason': '테스트 근거 대조'}
                                  for item in context['statements']]}
            if self.review_response is not None:
                ids = {item['item_id'] for item in context['statements']}
                content = {'checks': [item for item in self.review_response['checks'] if item['item_id'] in ids]}
        else:
            content = self.response
        return {'done': True, 'done_reason': self.done_reason,
                'message': {'content': json.dumps(content, ensure_ascii=False)}}


def test_exact_returned_scores_are_joined_without_recalculating_or_treating_label_as_conflict():
    collection, analysis, response = inputs()
    packet = report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))
    assert [e['reliability'] for e in packet['evidence']] == [0.53, 0.71]
    assert packet['confidence_input_binding'] == 'claim_fields'
    assert packet['docs'] == verification_input(analysis)['docs']
    client = Model()
    trace = []
    report = asyncio.run(generate_report(client, 'test', packet, trace))
    assert report['status'] == 'draft' and report['audit'] == []
    assert report['sections']['conflicting_candidates'] == []
    assert len(client.calls) == 2
    context = json.loads(client.calls[0]['messages'][1]['content'])
    assert 'docs' not in context and 'article_text' not in context
    assert context['evidence'][0]['original_quote'] == '甲方宣布活動。'
    assert len(context['evidence']) == len(packet['evidence'])
    assert all('url' not in item and 'title' not in item for item in context['evidence'])
    markdown = report_markdown(report)
    assert '점수 0.53' in markdown and '점수 0.71' in markdown and 'https://example.com/a' in markdown


@pytest.mark.parametrize('field,value', [('document_id', 'old-doc'), ('translated_quote', '다른 인용'),
    ('event_date', '2026-10-01'), ('tier', 3), ('paragraph_id', 'other-p'), ('claim_id', 'old-c1')])
def test_old_or_modified_reliability_claim_is_rejected(field, value):
    collection, analysis, response = inputs()
    response['claims'][0][field] = value
    with pytest.raises(AnalysisError):
        report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -0.1, 1.1, '0.5', True])
def test_reliability_requires_finite_number_in_range(value):
    _, _, response = inputs()
    response['claims'][0]['reliability'] = value
    with pytest.raises(ValidationError):
        ReliabilityResponse.model_validate(response)


def test_returned_input_digest_binds_weights_and_sim_changes():
    collection, analysis, response = inputs()
    response['input_sha256'] = input_digest(analysis)
    assert report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))['confidence_input_binding'] == 'input_sha256'
    analysis['docs'][0]['weight'] = 0.7
    with pytest.raises(AnalysisError, match='해시'):
        report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))


def test_partial_scores_remain_unevaluated_and_duplicate_scores_are_rejected():
    collection, analysis, response = inputs()
    response['claims'] = response['claims'][:1]
    response['summary'] = {'관점 차이': 1}
    packet = report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))
    assert packet['evidence'][1]['reliability'] is None and packet['missing_scores'] == ['b-c1']
    response['claims'].append(copy.deepcopy(response['claims'][0]))
    with pytest.raises(AnalysisError, match='중복'):
        report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))


def test_source_or_question_mismatch_and_ungrounded_quote_are_rejected():
    collection, analysis, response = inputs()
    response = ReliabilityResponse.model_validate(response)
    other = copy.deepcopy(collection)
    other['input']['question'] = '다른 질문'
    with pytest.raises(AnalysisError, match='질문'):
        report_evidence(other, analysis, response)
    collection['output']['documents'][0]['text_snippet'] = '다른 내용'
    with pytest.raises(AnalysisError, match='수집 원문'):
        report_evidence(collection, analysis, response)


@pytest.mark.parametrize('mutate', ['unknown', 'duplicate', 'common_one', 'conflict_one', 'interpret_no_ref', 'judgment_no_ref', 'truncated'])
def test_report_rejects_bad_citations_and_truncated_output(mutate):
    collection, analysis, response = inputs()
    packet = report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))
    value = draft()
    if mutate == 'unknown':
        value['key_judgment'][0]['claim_ids'] = ['fake-c1']
    elif mutate == 'duplicate':
        value['key_judgment'][0]['claim_ids'] = ['a-c1', 'a-c1']
    elif mutate in {'common_one', 'conflict_one'}:
        key = 'common_facts' if mutate == 'common_one' else 'conflicting_candidates'
        value[key] = [{'text': '같은 주장', 'claim_ids': ['a-c1']}]
    elif mutate == 'interpret_no_ref':
        value['source_interpretations'][0]['claim_ids'] = []
    elif mutate == 'judgment_no_ref':
        value['key_judgment'][0]['claim_ids'] = []
    client = Model(value, done_reason='length' if mutate == 'truncated' else 'stop')
    with pytest.raises(AnalysisError):
        asyncio.run(generate_report(client, 'test', packet, []))


def test_platform_classification_is_not_accepted_as_official_identity():
    collection, analysis, response = inputs()
    document = collection['output']['documents'][0]
    document.update(url='https://x.com/random/status/123', source_name='공식 계정', country='GLOBAL')
    packet = report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))
    assert packet['collection_coverage']['platform_account_identity_verified'] is False
    assert packet['collection_coverage']['platform_document_ids'] == ['a']
    assert any('공식성' in warning for warning in packet['warnings'])


@pytest.mark.parametrize('thresholds', [{'low': 0.8, 'high': 0.5}, {'low': 0.5},
                                      {'low': True, 'high': 0.75}, {'low': -0.1, 'high': 0.75}])
def test_bad_thresholds_are_rejected(thresholds):
    collection, analysis, response = inputs()
    response['thresholds'] = thresholds
    with pytest.raises((AnalysisError, ValidationError)):
        report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))


def test_false_common_stays_provisional_without_dropping_articles_or_original_scores():
    collection, analysis, response = inputs()
    packet = report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))
    value = draft()
    value['common_facts'] = [{'text': '두 기사 모두 활동 발표를 확인했다.', 'claim_ids': ['a-c1', 'b-c1']}]
    checks = {'checks': [{'item_id': 'key_judgment:0', 'verdict': 'supported', 'reason': '별도 발표'},
        {'item_id': 'common_facts:0', 'verdict': 'unsupported', 'reason': '활동 발표와 감시는 같은 주장이 아니다.'},
        {'item_id': 'source_interpretations:0', 'verdict': 'supported', 'reason': '원문에 발표 명시'},
        {'item_id': 'analysis_limits:0', 'verdict': 'supported', 'reason': 'snippet 분석 범위'}]}
    trace = []
    report = asyncio.run(generate_report(Model(value, review_response=checks), 'test', packet, trace))
    assert report['sections']['common_facts'] == []
    assert report['proposed_comparisons'][0]['item_id'] == 'common_facts:0'
    assert report['report_review']['checks'][0]['verdict'] == 'uncertain'
    assert [e['reliability'] for e in report['evidence']] == [0.53, 0.71]
    assert len(report['docs']) == len(report['evidence']) == 2
    assert 'LLM 비교 제안 · 사람 검토 대기' in report_markdown(report)
    assert [entry['phase'] for entry in trace] == ['report', 'report_review']


def test_global_source_and_zero_matching_labels_do_not_hide_comparison_candidates():
    collection, analysis, response = inputs()
    collection['output']['documents'][1]['country'] = 'GLOBAL'
    response['claims'][0]['label'] = response['claims'][1]['label'] = '판단 보류'
    response['summary'] = {'판단 보류': 2}
    packet = report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))
    value = draft()
    value['common_facts'] = [{'text': '같은 발표 내용을 담은 후보', 'claim_ids': ['a-c1', 'b-c1']}]
    report = asyncio.run(generate_report(Model(value), 'test', packet, []))
    assert report['evidence'][1]['country'] == 'GLOBAL'
    assert len(report['proposed_comparisons']) == 1
    assert [e['reliability'] for e in report['evidence']] == [0.53, 0.71]
    section = report_markdown(report).split('## 공통 사실 주장')[1].split('## 상충 후보')[0]
    assert '같은 발표 내용을 담은 후보' in section
    assert '[a-c1]' in section and '[b-c1]' in section
    assert '찾지 못했습니다' not in section


def test_missing_or_duplicate_semantic_review_items_fail_closed():
    collection, analysis, response = inputs()
    packet = report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))
    checks = {'checks': [{'item_id': 'key_judgment:0', 'verdict': 'supported', 'reason': '동일'}] * 3}
    with pytest.raises(AnalysisError, match='누락·중복·추가'):
        asyncio.run(generate_report(Model(review_response=checks), 'test', packet, []))


def test_returned_country_must_match_collected_source_metadata():
    collection, analysis, response = inputs()
    response['claims'][0]['country'] = 'CN'
    assert report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))['evidence'][0]['country'] == 'CN'
    response['claims'][0]['country'] = 'US'
    with pytest.raises(AnalysisError, match='출처 국가'):
        report_evidence(collection, analysis, ReliabilityResponse.model_validate(response))
