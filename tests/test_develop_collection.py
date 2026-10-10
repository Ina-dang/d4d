"""develop 수집 정책이 실제 LLM 검색 계획 경로에서도 적용되는지 확인."""

import pytest

from app.search.search_schemas import CollectionRequest
from frame.collector import OSINTCollector, TavilyClient


@pytest.mark.parametrize('limit,expected', [
    (20, {'CN': 7, 'TW': 7, 'HK': 6, 'KR': 20}),
    (2, {'CN': 1, 'TW': 1, 'HK': 0, 'KR': 2}),
    (100, {'CN': 7, 'TW': 7, 'HK': 6, 'KR': 20}),
])
def test_llm_plan_applies_combined_china_cap_and_keeps_language_balance(monkeypatch, limit, expected):
    docs = [{'country': country, 'language': language, 'score': 0.9 - index / 1000,
             'doc_id': f'{country}-{language}-{index}'}
            for country in expected for language in ('en', 'zh') for index in range(25)]
    monkeypatch.setattr(OSINTCollector, 'collect_multilingual', lambda *_args, **_kwargs: docs)
    output = OSINTCollector(api_key='test').collect_plan(
        {'queries': [{'language': lang, 'query': 'Taiwan Strait'} for lang in ('en', 'zh')]},
        max_docs_per_country=limit)
    assert {country: len(output['by_country'][country]) for country in expected} == expected
    assert output['total_count'] == len(output['documents']) == sum(expected.values())
    assert output['all_documents'] == output['documents']
    for country, count in expected.items():
        assert output[country] == output['by_country'][country]
        if count >= 2:
            assert {doc['language'] for doc in output[country]} == {'en', 'zh'}


def test_small_legacy_quota_does_not_request_from_zero_allocation(monkeypatch):
    calls = []
    monkeypatch.setattr(OSINTCollector, '_expand_korean_to_7_actors',
                        lambda *_args: dict.fromkeys(('CN', 'TW', 'HK'), 'Taiwan Strait'))

    def collect(_self, **kwargs):
        calls.append(kwargs['max_results'])
        return []

    monkeypatch.setattr(OSINTCollector, 'collect', collect)
    OSINTCollector(api_key='test').collect_from_korean('대만해협 군사활동', max_docs_per_country=1)
    assert calls == [1]


@pytest.mark.parametrize('heading', ['### 에디터스 픽', '**에디터스 바**', "**Editors’ Picks**"])
def test_editor_sidebar_does_not_enter_article_or_paragraphs(heading):
    body = '중국과 대만 당국은 대만해협의 군사활동에 관해 각각 발표했다.\n' * 4
    collector = OSINTCollector(api_key='test')
    cleaned, removed = collector._clean_content(
        body + '\n' + heading + '\n남창희 연예뉴스\n추천 기사의 내용이 이어집니다.')
    assert '군사활동' in cleaned
    assert '남창희' not in cleaned
    assert '추천 기사의 내용' not in cleaned
    assert removed
    assert all('남창희' not in p for p in collector._split_into_paragraphs(cleaned))


def test_link_only_widgets_are_not_restored_by_paragraph_fallback():
    assert OSINTCollector(api_key='test')._split_into_paragraphs(
        '**[남창희 관련 추천 기사](https://example.com/news/123)**') == []


@pytest.mark.parametrize('url,weight', [
    ('https://x.com/agency/status/123456', 0.60),
    ('https://twitter.com/agency/status/123456', 0.60),
    ('https://weibo.com/123456/ABC123', 0.60),
    ('https://facebook.com/agency/posts/123456', 0.55),
    ('https://youtube.com/watch?v=ABC123', 0.55),
])
def test_social_posts_keep_weights_body_language_and_review_metadata(monkeypatch, url, weight):
    body = ('India and Pakistan issued conflicting statements about the border clash. '
            'Indian officials reported military operations and Pakistan disputed these claims.')
    calls = []

    def search(_self, **kwargs):
        calls.append(kwargs)
        return {'results': [{'url': url, 'title': 'India Pakistan border clash',
                             'raw_content': body, 'score': 0.5}]}

    monkeypatch.setattr(TavilyClient, 'search', search)
    collector = OSINTCollector(api_key='test')
    doc, = collector.collect('India Pakistan clash', selected_languages=['en'])
    assert url.split('/')[2] in calls[0]['include_domains']
    assert doc['credibility_weight'] == weight
    assert doc['language'] == 'en'
    assert doc['cleaning']['needs_review'] is True
    assert doc['cleaning']['score_notice']
    assert calls[0]['max_results'] <= 20


def test_request_defaults_to_develop_twenty_document_policy():
    assert CollectionRequest(question='대만해협 군사활동 양측 입장 비교').max_docs_per_country == 20


def test_updated_develop_prefers_transcript_over_video_promotion():
    cleaned, _ = OSINTCollector(api_key='test')._clean_content(
        'Subscribe to our channel.\nLike and share the video.\n### Transcript\n'
        '중국 당국은 대만해협에서 군사훈련을 실시한다고 발표했습니다.\n'
        '대만 당국은 중국군의 활동을 감시 중이라고 밝혔습니다.')
    assert 'Subscribe' not in cleaned and 'share' not in cleaned
    assert '군사훈련' in cleaned and '감시 중' in cleaned


@pytest.mark.parametrize('line', ['This is a Premium article available exclusively to subscribers.',
    'Already a subscriber? Log in here.', 'Register to continue reading this article.'])
def test_updated_develop_removes_subscription_or_login_only_content(line):
    cleaned, _ = OSINTCollector(api_key='test')._clean_content(line)
    assert not OSINTCollector(api_key='test')._build_clean_5_sentence_snippet(cleaned)


def test_access_notice_removal_preserves_article_sentence_on_the_same_line():
    collector = OSINTCollector(api_key='test')
    text = ('This is a Premium article available exclusively to subscribers. '
            'Taiwan announced a military exercise in the Strait. '
            'Register to continue reading this article.')
    cleaned, _ = collector._clean_content(text)
    assert cleaned.strip() == 'Taiwan announced a military exercise in the Strait.'
    assert collector._build_clean_5_sentence_snippet(text) == cleaned.strip()
