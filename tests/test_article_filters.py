import pytest

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
    result = OSINTCollector(api_key='test').collect_plan(
        {'event': '인도 파키스탄 충돌', 'queries': [{'language': 'en', 'query': 'India Pakistan conflict'}],
         'selected_languages': list(languages), 'relevance_context': context},
        max_results_per_query=5, max_docs_per_country=5)
    return result, calls


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
