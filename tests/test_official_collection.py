"""실제 누락 원인: 台海 약칭, 다주제 정부 기자회견, SNS만 남은 검색."""

import pytest

from frame.article_filters import topic_evidence
from frame.collector import OSINTCollector, TavilyClient
from frame.official_sources import missing_official_countries

CONTEXT = {'anchor_groups': [['대만해협', 'Taiwan Strait'], ['중국', 'China'], ['대만', 'Taiwan']],
           'security_topic': True}
ANSWER = ('国防部：台湾是中国的一部分。我们坚决反对台独分裂活动，维护台海和平稳定。'
          '中国人民解放军将采取必要措施，保卫国家主权和领土完整，坚决反对外部势力干涉。')
BRIEFING = ('国防部举行例行记者会，介绍国际军事交流情况，通报近期人员培训计划、'
            '国际合作活动安排和部队后勤保障工作，并回答各媒体记者提出的多个问题。\n\n'
            '记者：请介绍与其他国家的军事交流情况？\n国防部：本月开展多项交流活动。\n\n'
            '记者：请评论最近的台湾局势和台海和平稳定问题？\n' + ANSWER + '\n\n'
            '记者：请介绍部队的训练保障工作？\n国防部：有关工作正在按计划开展。')


@pytest.mark.parametrize('body', [
    '美國官員表示，中國武力犯台會付出重大代價，台海衝突風險可以透過嚇阻降低。台灣當局強調國防的重要性。',
    '北京表示反对台湾独立，要求维护台海和平稳定。中国国防部强调军队将维护国家主权。',
])
def test_strait_abbreviation_and_security_positions_are_topic_evidence(body):
    reason, evidence = topic_evidence(body, CONTEXT, title='台海衝突與嚇阻')
    assert reason is None
    assert evidence['security_term']


def test_generic_official_briefing_uses_grounded_question_answer_section():
    assert topic_evidence(BRIEFING, CONTEXT, title='国防部例行记者会')[0] == 'topic_background_only'
    reason, evidence = topic_evidence(BRIEFING, CONTEXT, title='国防部例行记者会', briefing=True)
    assert reason is None
    assert evidence['briefing_section'] in BRIEFING
    assert ANSWER in evidence['briefing_section']
    assert '训练保障' not in evidence['briefing_section']


def test_markdown_question_markers_are_recognized_without_changing_original_quotes():
    text = BRIEFING.replace('记者：', '**记者：**')
    reason, evidence = topic_evidence(text, CONTEXT, title='国防部例行记者会', briefing=True)
    assert reason is None
    assert evidence['briefing_section'] in text


@pytest.mark.parametrize('body', [
    '中国和台湾讨论贸易投资及旅游交流，两地企业签订合作协议，增加就业。',
    '中国军队与其他国家举行联合演习，讨论国际合作，国防部介绍训练工作。',
])
def test_official_source_does_not_override_missing_place_or_topic(body):
    assert topic_evidence(body, CONTEXT, title='国防部例行记者会', briefing=True)[0] is not None


def item(url, body, title, score=.8):
    return dict(url=url, title=title, raw_content=body, score=score)


def test_social_matches_trigger_official_search_and_keep_existing_documents(monkeypatch):
    social = item('https://x.com/commentator/status/123456789',
                  'China and Taiwan described military activities in the Taiwan Strait. '
                  'The two parties gave separate statements about naval movements and troops.',
                  'Taiwan Strait activities')
    chinese = item('http://www.mod.gov.cn/gfbw/qwfb/123456.html', BRIEFING, '国防部例行记者会', .55)
    taiwan = item('https://www.mnd.gov.tw/Publish.aspx?p=123456',
                  '國防部表示，中國軍隊在台海的軍事活動持續。台灣國軍正在監視有關活動，'
                  '並依照防衛計畫採取必要措施，維護區域的和平穩定。', '台海軍事活動')
    unrelated = item('https://www.mod.gov.cn/news/12345.html',
                     '中国国防部介绍国际交流和联合军事演习，讨论其他国家的训练保障计划。', '国际军事交流')
    calls = []

    def search(_self, **kwargs):
        calls.append(kwargs)
        if 'mod.gov.cn' in kwargs['include_domains'] and len(kwargs['include_domains']) <= 3:
            return {'results': [chinese, unrelated]}
        if 'mnd.gov.tw' in kwargs['include_domains'] and len(kwargs['include_domains']) <= 3:
            return {'results': [taiwan]}
        return {'results': [social]}

    monkeypatch.setattr(TavilyClient, 'search', search)
    result = OSINTCollector(api_key='test').collect_plan({
        'queries': [{'language': 'en', 'query': 'China Taiwan Strait statements'}],
        'selected_languages': ['en', 'zh', 'zh-Hant'], 'relevance_context': CONTEXT})
    assert {d['url'] for d in result['documents']} == {social['url'], chinese['url'], taiwan['url']}
    assert len(calls) == 3
    assert all(c['time_range'] == 'week' for c in calls)
    assert all(c['max_results'] <= 20 for c in calls)
    assert {r['country'] for r in result['filtering']['search_attempts']
            if r['kind'] == 'official_coverage_retry'} == {'CN', 'TW'}
    assert result['filtering']['official_coverage']['TW']['retained'] == 1
    china, = result['CN']
    assert '训练保障' not in china['text_snippet']
    assert '台湾' in china['text_snippet'] and '台海' in china['text_snippet']
    assert '训练保障' in china['article_text']
    assert china['score'] == .55
    assert unrelated['url'] in {r['url'] for r in result['filtering']['rejected']}


def test_social_accounts_and_xinhua_do_not_count_as_government_coverage():
    docs = [{'url': 'https://x.com/mnd/status/123'}, {'url': 'https://www.news.cn/a.html'}]
    assert missing_official_countries(docs, CONTEXT) == ['CN', 'TW']
    assert missing_official_countries(docs + [{'url': 'https://www.mnd.gov.tw/a.aspx'}], CONTEXT) == ['CN']
    assert missing_official_countries(docs, {'anchor_groups': [['인도'], ['파키스탄']]}) == []


def test_country_quota_keeps_one_official_source_even_with_higher_scored_media(monkeypatch):
    docs = [dict(country='TW', language='zh-Hant', score=.99 - i / 100,
                 url=f'https://cna.com.tw/news/{i}', doc_id=str(i)) for i in range(10)]
    docs.append(dict(country='TW', language='zh-Hant', score=.55,
                     url='https://www.mnd.gov.tw/a.aspx', doc_id='official'))
    monkeypatch.setattr(OSINTCollector, 'collect_multilingual', lambda *_a, **_k: docs)
    result = OSINTCollector(api_key='test').collect_plan({
        'queries': [{'language': 'zh-Hant', 'query': '台海'}]}, max_docs_per_country=2)
    assert len(result['TW']) == 1  # Existing CN/TW/HK combined allocation for quota=2.
    assert result['TW'][0]['doc_id'] == 'official'


def test_government_issuer_can_supply_own_party_but_cannot_supply_missing_place(monkeypatch):
    body = ('记者：请问对台湾独立的讨论有何评论？\n'
            '发言人：和平统一是解决台湾问题的基本方针。统一将消除台海战火隐患，'
            '维护区域和平稳定，为台湾同胞筑牢安全屏障，反对分裂活动和外部干涉。')
    source = item('https://www.mod.gov.cn/gfbw/123.html', body, '国防部：反对台独')
    monkeypatch.setattr(TavilyClient, 'search', lambda *_a, **_k: {'results': [source]})
    collector = OSINTCollector(api_key='test')
    doc, = collector.collect('台湾 台海', selected_languages=['zh'], relevance_context=CONTEXT)
    assert doc['relevance']['source_party'] == 'CN'
    assert '台海' in doc['text_snippet']
    source['raw_content'] = body.replace('台海', '区域')
    monkeypatch.setattr(TavilyClient, 'extract', lambda *_a, **_k: {'results': []})
    assert collector.collect('台湾', selected_languages=['zh'], relevance_context=CONTEXT) == []


def test_roc_publication_date_prevents_old_taiwan_announcement_from_becoming_current(monkeypatch):
    source = item('https://www.mnd.gov.tw/publication/123',
                  '區域動態 114.10.01 發布單位：國防部\n\n'
                  '中共解放軍持續在臺海周邊活動，國軍運用任務機艦及岸置飛彈系統監控與應處，'
                  '國防部發布周邊海空域動態，說明相關軍事活動情況。', '臺海周邊海空域動態')
    monkeypatch.setattr(TavilyClient, 'search', lambda *_a, **_k: {'results': [source]})
    collector = OSINTCollector(api_key='test')
    assert collector._extract_published_date(source['url'], source['raw_content']) == '2025-10-01'
    assert collector.collect('臺海', days_back=30, selected_languages=['zh-Hant'],
                             relevance_context=CONTEXT) == []
    assert collector.filter_rejections[-1]['reason'] == 'published_outside_window'


def test_short_menu_fragment_on_official_site_is_recovered_once_with_full_body(monkeypatch):
    source = item('https://www.mod.gov.cn/gfbw/123.html', 'Ministry of Defense Menu', '国防部例行记者会')
    calls = []
    monkeypatch.setattr(TavilyClient, 'search', lambda *_a, **_k: {'results': [source]})

    def extract(_self, **kwargs):
        calls.append(kwargs)
        return {'results': [{'url': source['url'], 'raw_content': BRIEFING}]}

    monkeypatch.setattr(TavilyClient, 'extract', extract)
    collector = OSINTCollector(api_key='test')
    doc, = collector.collect('台海', selected_languages=['zh'], relevance_context=CONTEXT)
    assert doc['body_acquisition']['method'] == 'tavily_extract'
    assert '台湾' in doc['text_snippet']
    collector.collect('台海', selected_languages=['zh'], relevance_context=CONTEXT)
    assert len(calls) == 1


def test_snippet_starts_from_article_not_browser_language_and_privacy_notices():
    article = ('美國官員表示，中國武力犯台會付出重大代價，台海衝突風險可以透過嚇阻降低。'
               '台灣當局強調國防的重要性。中國和台灣當局分別說明軍事活動。')
    full = 'Your browser does not support Chinese. Would you like another language?\n\n隱私權規範\n\n' + article
    source = OSINTCollector._snippet_source(full, CONTEXT, {})
    snippet = OSINTCollector(api_key='test')._build_clean_5_sentence_snippet(source)
    assert 'browser' not in snippet and '隱私' not in snippet
    assert '台海' in snippet and '嚇阻' in snippet


def test_article_lead_can_use_next_paragraph_for_party_context():
    lead = ('美國官員表示，投資人高估台海衝突風險，他強調中國動武面臨重大後果，'
            '將使北京不致在2027年前武力犯台。')
    next_paragraph = '他指出，台灣海峽發生軍事衝突的風險受到高估，中國和台灣都需要確保區域和平穩定。'
    text = '# 台海衝突\n\nYour browser does not support Chinese.\n\n' + lead + '\n\n' + next_paragraph
    snippet = OSINTCollector._snippet_source(text, CONTEXT, {})
    assert snippet.startswith(lead)
    assert 'browser' not in snippet
