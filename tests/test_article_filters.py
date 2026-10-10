import unicodedata
from pathlib import Path

import pytest

from frame.article_filters import detect_body_language
from frame.collector import OSINTCollector, TavilyClient

CONTEXT = {'anchor_groups': [['India', '인도', 'भारत', 'بھارت'],
                             ['Pakistan', '파키스탄', 'पाकिस्तान', 'پاکستان']],
           'security_topic': True}
ENGLISH = ('India and Pakistan issued conflicting statements about the border clash. '
           'Indian military officials said troops exchanged fire, while Pakistan disputed the claim.')
HINDI = ('भारत और पाकिस्तान के बीच सीमा पर सैन्य संघर्ष को लेकर दोनों देशों ने बयान जारी किए। '
         'भारतीय सेना ने गोलीबारी की जानकारी दी और पाकिस्तान ने इस दावे से इनकार किया।')
URDU = ('بھارت اور پاکستان کے درمیان سرحد پر فوجی تصادم کے بارے میں دونوں ممالک نے بیانات جاری کیے۔ '
        'بھارتی فوج نے فائرنگ کی اطلاع دی جبکہ پاکستان نے اس دعوے کی تردید کی۔')
ARABIC = ('أعلنت الشرطة أن ثلاثة أشخاص لقوا مصرعهم في حادث تصادم على طريق سريع في مدينة ملبورن. '
          'وأفادت السلطات بأن التحقيق في أسباب الحادث مستمر حتى الآن.')


def youtube_traditional_chinese_body():
    return (Path(__file__).parent / 'fixtures' / 'youtube_zh_hant.txt').read_text(encoding='utf-8')


def test_traditional_chinese_youtube_body_without_hangul_is_not_korean():
    # Captured body of the reported EBC video; the old detector returned ko with probability 1.
    result = detect_body_language(youtube_traditional_chinese_body())
    assert result['language'] == 'zh-Hant'
    assert result['confidence'] >= 0.8


@pytest.mark.parametrize('body,expected', [
    ('중국과 대만 당국은 대만해협의 군사활동에 관해 각각 발표했다. '
     '한국 정부는 양측의 발표와 해군 훈련 상황을 확인하고 지역 안보를 논의했다.', 'ko'),
    (unicodedata.normalize('NFD', '한국 정부는 대만해협에서 벌어진 군사활동을 확인했다. '
                          '중국과 대만 당국은 해군 훈련과 군대의 이동에 대해 서로 다른 입장을 발표했다.'), 'ko'),
    ('中国和台湾当局分别就台湾海峡的军事活动发表声明。中国军队进行了海军演习，'
     '台湾国防部门表示正在监视有关活动，双方对局势提出了不同说法。', 'zh'),
    ('中国と台湾の当局は台湾海峡での軍事活動についてそれぞれ声明を発表した。'
     '日本の防衛省は海軍の演習と部隊の動きを確認し、地域の安全保障について説明した。', 'ja'),
])
def test_script_constraint_preserves_korean_chinese_and_japanese(body, expected):
    assert detect_body_language(body)['language'] == expected


def article(number, body, *, domain='www.reuters.com', score=0.9, title='Report'):
    return {'url': f'https://{domain}/world/article-{number}/', 'title': f'{title} {number}',
            'score': score, 'raw_content': body, 'content': ENGLISH}


@pytest.mark.parametrize('domain,body,expected', [
    ('arabic.news.cn', ARABIC, 'ar'), ('www.nhk.or.jp', URDU, 'ur'),
    ('pib.gov.in', HINDI, 'hi'), ('news.cn', ENGLISH, 'en')])
def test_language_comes_from_body_not_domain(domain, body, expected):
    assert OSINTCollector(api_key='test')._detect_language('https://' + domain, body) == expected


def collect(monkeypatch, articles, languages=('ko', 'en', 'hi', 'ur'), context=CONTEXT):
    calls = []

    def search(_client, **kwargs):
        calls.append(kwargs)
        return {'results': articles}

    monkeypatch.setattr(TavilyClient, 'search', search)
    monkeypatch.setattr(TavilyClient, 'extract', lambda *_args, **_kwargs: {'results': []})
    result = OSINTCollector(api_key='test').collect_plan(
        {'event': '인도 파키스탄 충돌', 'queries': [{'language': 'en', 'query': 'India Pakistan conflict'}],
         'selected_languages': list(languages), 'relevance_context': context},
        max_results_per_query=5, max_docs_per_country=5)
    return result, calls


@pytest.mark.parametrize('language,expected_count', [('zh-Hant', 1), ('ko', 0)])
def test_youtube_traditional_chinese_respects_selected_body_language(
    monkeypatch, language, expected_count,
):
    video = article(1, youtube_traditional_chinese_body(), domain='youtube.com',
                    title='習近平敢打台灣就下地獄')
    video['url'] = 'https://www.youtube.com/watch?v=ABC123'
    monkeypatch.setattr(TavilyClient, 'search', lambda *_args, **_kwargs: {'results': [video]})
    result = OSINTCollector(api_key='test').collect_plan(
        {'queries': [{'language': language, 'query': '台灣海峽軍事活動'}],
         'selected_languages': [language]})
    assert result['total_count'] == expected_count
    if expected_count:
        assert result['documents'][0]['language'] == 'zh-Hant'
        assert result['filtering']['rejected_counts'] == {}
    else:
        assert result['filtering']['rejected_counts'] == {'language_not_selected': 1}


def test_rejects_wrong_language_and_unrelated_articles_before_padding(monkeypatch):
    result, _ = collect(monkeypatch, [
        article(1, ARABIC, domain='arabic.news.cn', score=0.17),
        article(2, 'India and New Zealand signed a free trade agreement. '
                'The new partnership expands exports and supports economic development.', score=0.9),
        article(3, 'India and Pakistan will meet in the same cricket World Cup group. '
                'Their clash will take place during the tournament scheduled for next year.', score=0.95),
        article(4, ENGLISH, domain='news.cn', score=0.65),
        article(5, HINDI, domain='pib.gov.in', score=0.6),
        article(6, URDU, domain='www.nhk.or.jp', score=0.5),
    ])
    assert {doc['url'] for doc in result['documents']} == {
        'https://news.cn/world/article-4/', 'https://pib.gov.in/world/article-5/',
        'https://www.nhk.or.jp/world/article-6/'}
    assert {doc['language'] for doc in result['documents']} == {'en', 'hi', 'ur'}
    assert result['by_country']['CN'][0]['language'] == 'en'
    assert result['filtering']['rejected_counts'] == {'language_not_selected': 1,
                                                    'topic_anchors_missing': 1,
                                                    'security_topic_missing': 1}
    assert all(doc['language_detection']['method'] == 'body_langdetect'
               for doc in result['documents'])


def test_selected_languages_do_not_add_a_korean_search(monkeypatch):
    result, calls = collect(monkeypatch, [article(1, ENGLISH)], languages=('en',))
    assert len(calls) == 1
    assert list(result['queries']) == ['en']


def test_legacy_frame_schema_infers_languages_when_optional_selection_is_null(monkeypatch):
    from frame.schemas import SearchPlanRequest

    monkeypatch.setattr(TavilyClient, 'search', lambda *_args, **_kwargs:
                        {'results': [article(1, ENGLISH)]})
    plan = SearchPlanRequest(event='인도 파키스탄 충돌',
                             queries=[{'language': 'en', 'query': 'India Pakistan conflict'}])
    result = OSINTCollector(api_key='test').collect_plan(plan.model_dump())
    assert result['total_count'] == 1
    assert result['filtering']['selected_languages'] == ['en']


def test_summary_without_article_body_and_uncertain_language_are_rejected(monkeypatch):
    result, _ = collect(monkeypatch, [article(1, ''), article(2, '1234567890 ' * 20)])
    assert result['documents'] == []
    assert result['filtering']['rejected_counts'] == {'body_unavailable': 1,
                                                    'language_uncertain': 1}


def test_title_and_menu_cannot_supply_missing_topic_anchors(monkeypatch):
    result, _ = collect(monkeypatch, [article(1, 'Pakistan police reported an explosion in a city. '
                                         'Investigators are examining the evidence at the scene.',
                                         title='India Pakistan military conflict')])
    assert result['documents'] == []


def test_taiwan_strait_place_must_appear_in_body(monkeypatch):
    context = {'anchor_groups': [['Taiwan Strait', '대만해협'], ['China', '중국'],
                                 ['Taiwan authorities', '대만 당국']], 'security_topic': True}
    result, _ = collect(monkeypatch, [article(1, 'China and Taiwan authorities discussed their military '
                                         'policy at a press conference without naming any location.')],
                        context=context)
    assert result['documents'] == []


def test_search_includes_urdu_publishers_and_language_still_comes_from_body(monkeypatch):
    result, calls = collect(monkeypatch, [article(1, URDU, domain='jang.com.pk')], languages=('ur',))
    # Real plans use their selected query language, unlike this helper's English query.
    monkeypatch.setattr(TavilyClient, 'search', lambda _client, **kwargs:
                        calls.append(kwargs) or {'results': [article(1, URDU, domain='jang.com.pk')]})
    result = OSINTCollector(api_key='test').collect_plan(
        {'event': '인도 파키스탄 충돌', 'queries': [{'language': 'ur', 'query': 'بھارت پاکستان تصادم'}],
         'selected_languages': ['ur'], 'relevance_context': CONTEXT})
    assert {'jang.com.pk', 'dawnnews.tv', 'urdu.geo.tv', 'bbc.com'} <= set(calls[-1]['include_domains'])
    assert result['documents'][0]['country'] == 'PK'
    assert result['documents'][0]['language'] == 'ur'


def test_missing_search_body_is_recovered_by_extract_before_language_filter(monkeypatch):
    missing = article(1, '', domain='jang.com.pk', title='بھارت پاکستان فوجی تصادم')
    requests = []
    monkeypatch.setattr(TavilyClient, 'search', lambda *_args, **_kwargs: {'results': [missing]})

    def extract(_client, **kwargs):
        requests.append(kwargs)
        return {'results': [{'url': missing['url'], 'raw_content': URDU}]}

    monkeypatch.setattr(TavilyClient, 'extract', extract)
    result = OSINTCollector(api_key='test').collect_plan(
        {'event': '인도 파키스탄 충돌', 'queries': [{'language': 'ur', 'query': 'بھارت پاکستان تصادم'}],
         'selected_languages': ['ur'], 'relevance_context': CONTEXT})
    assert result['total_count'] == 1
    assert result['documents'][0]['language'] == 'ur'
    assert result['documents'][0]['body_acquisition']['method'] == 'tavily_extract'
    assert requests[0]['urls'] == [missing['url']]


def test_extract_failure_does_not_promote_summary_to_article_body(monkeypatch):
    missing = article(1, '', title='India Pakistan border clash')
    monkeypatch.setattr(TavilyClient, 'search', lambda *_args, **_kwargs: {'results': [missing]})

    def extract(*_args, **_kwargs):
        raise RuntimeError('provider-secret-detail')

    monkeypatch.setattr(TavilyClient, 'extract', extract)
    result = OSINTCollector(api_key='test', raise_on_error=True).collect_plan(
        {'event': '인도 파키스탄 충돌', 'queries': [{'language': 'en', 'query': 'India Pakistan clash'}],
         'selected_languages': ['en'], 'relevance_context': CONTEXT})
    assert result['documents'] == []
    assert result['filtering']['body_recovery']['failed'] == 1
    assert 'provider-secret-detail' not in str(result)


def test_urdu_diplomatic_tension_article_is_not_rejected_for_lacking_word_military(monkeypatch):
    body = ('پاکستان اور انڈیا کے درمیان کشیدگی پر دونوں حکومتوں نے اپنے اپنے مؤقف پیش کیے۔ '
            'انڈیا نے مذاکرات کی شرط بیان کی، جبکہ پاکستان نے تنازع کے پُرامن حل کی حمایت کی۔')
    result, _ = collect(monkeypatch, [article(1, body)], languages=('ur',))
    # Use a selected Urdu query as the caller would.
    result = OSINTCollector(api_key='test').collect_plan(
        {'event': '인도 파키스탄 충돌', 'queries': [{'language': 'ur', 'query': 'بھارت پاکستان تصادم'}],
         'selected_languages': ['ur'], 'relevance_context': CONTEXT})
    assert result['total_count'] == 1


def test_kashmir_place_name_alone_does_not_make_space_article_relevant(monkeypatch):
    body = ('India launched a satellite providing telemedicine services in Kashmir. '
            'Pakistan did not join the satellite education project. Medical services support remote hospitals.')
    result, _ = collect(monkeypatch, [article(1, body)])
    assert result['documents'] == []


def test_same_site_header_does_not_deduplicate_distinct_urdu_articles(monkeypatch):
    header = 'بانی گروپ چیف ایگزیکٹو ایڈیٹر ادارتی خبریں معلومات ' * 12
    articles = [article(1, header + '\n\n# Report A\n\n' + URDU, domain='jang.com.pk', title='Report A'),
                article(2, header + '\n\n# Report B\n\nپاکستانی وزارت خارجہ نے بھارت کی فوجی کارروائی پر احتجاج کیا۔ '
                        'بھارت نے اس الزام کو مسترد کرتے ہوئے سرحد پر پاکستان کے موقف سے اختلاف کیا۔',
                        domain='jang.com.pk', title='Report B')]
    result, _ = collect(monkeypatch, articles)
    assert result['total_count'] == 2


def test_country_limit_does_not_starve_selected_urdu_language(monkeypatch):
    articles = [article(1, ENGLISH, domain='dawn.com', title='English A'),
                article(2, 'Pakistan troops reported a clash near the border with India. '
                        'India disputed the military account of the incident and requested an investigation.',
                        domain='dawn.com', title='English B'),
                article(3, URDU, domain='jang.com.pk', title='Urdu')]
    monkeypatch.setattr(TavilyClient, 'search', lambda *_args, **_kwargs: {'results': articles})
    result = OSINTCollector(api_key='test').collect_plan(
        {'event': '인도 파키스탄 충돌', 'queries': [{'language': 'en', 'query': 'India Pakistan clash'},
         {'language': 'ur', 'query': 'بھارت پاکستان تصادم'}],
         'selected_languages': ['en', 'ur'], 'relevance_context': CONTEXT},
        max_results_per_query=3, max_docs_per_country=2)
    assert {doc['language'] for doc in result['by_country']['PK']} == {'en', 'ur'}


def test_background_mentions_in_unrelated_award_article_are_not_the_main_topic(monkeypatch):
    lead = 'Pakistan religious leader received an award for interfaith dialogue. The ceremony was held in a hall. '
    background = ('The award was later withdrawn after statements about an attack. '
                  'He said lobby groups in India and Pakistan were involved and discussed military affairs.')
    result, _ = collect(monkeypatch, [article(1, lead + '\n\n' + background, title='Interfaith award withdrawn')])
    assert result['documents'] == []


def test_empty_language_retries_full_query_without_relaxing_filters(monkeypatch):
    calls = []

    def search(_client, **kwargs):
        calls.append(kwargs['query'])
        return {'results': [article(1, HINDI)] if kwargs['query'] == 'full hindi query' else []}

    monkeypatch.setattr(TavilyClient, 'search', search)
    result = OSINTCollector(api_key='test').collect_plan(
        {'event': '인도 파키스탄 충돌', 'queries': [{'language': 'hi', 'query': 'full hindi query',
         'search_query': 'short hindi query'}], 'selected_languages': ['hi'], 'relevance_context': CONTEXT})
    assert calls == ['short hindi query', 'full hindi query']
    assert result['documents'][0]['language'] == 'hi'
    assert result['filtering']['search_attempts'][-1]['kind'] == 'full_query_retry'
