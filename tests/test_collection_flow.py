import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from frame.collector import OSINTCollector, TavilyClient

QUESTION = '대만해협 군사활동에 관한 중국과 대만 당국의 양측 입장을 비교하고 일치·상충·미확인 주장을 출처와 함께 정리해줘'


def connect_providers(monkeypatch, *, incomplete=False, search_error=False, incorrect_translation=False):
    calls = {'ollama': [], 'tavily': []}
    real_client = httpx.AsyncClient

    def ollama(request):
        payload = json.loads(request.content) if request.content else {}
        calls['ollama'].append((request.url.path, payload))
        if request.url.path == '/api/tags':
            data = {'models': [{'name': 'gemma4:e2b'}]}
        elif request.url.path == '/api/generate':
            data = {'done': True, 'done_reason': 'unload'}
        else:
            user = json.loads(payload['messages'][1]['content'])
            if 'question' in user:
                data = {'event': '대만해협 군사활동', 'event_date': None,
                        'place': '대만해협', 'parties': ['중국', '대만 당국'],
                        'focus': ['입장'], 'targets': [{'id': 'positions', 'label': '입장',
                                                       'subject': '양측 입장'}]}
            else:
                translations = {
                    'en': ['Taiwan Strait military activities', 'Taiwan Strait',
                           'China', 'Taiwan authorities', 'positions'],
                    'ja': ['台湾海峡の軍事活動', '台湾海峡', '中国', '台湾当局', '立場'],
                }
                data = {'translations': translations[user['language']]}
                if incorrect_translation:
                    data['translations'][3] = 'Chinese mainland government'
            data = {'done': True, 'done_reason': 'length' if incomplete else 'stop',
                    'message': {'role': 'assistant', 'content': json.dumps(data)}}
        return httpx.Response(200, json=data)

    def search(_client, **kwargs):
        calls['tavily'].append(kwargs)
        if search_error:
            raise RuntimeError('provider-secret-detail')
        return {'results': [{'url': 'https://www.reuters.com/world/asia-pacific/test-2026-10-10/',
                             'title': 'Authorities report Taiwan Strait military activities',
                             'score': 0.9, 'published_date': '2026-10-10',
                             'raw_content': 'Taiwan authorities described military activities in the Taiwan Strait. '
                                            'China issued a separate statement about the same activities.',
                             'content': 'Taiwan Strait military activities were reported by both sides.'}]}

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(
        **kw, transport=httpx.MockTransport(ollama)))
    monkeypatch.setattr(TavilyClient, 'search', search)
    return calls


def await_collection(client, rid):
    for _ in range(100):
        result = client.get('/api/collections/' + rid).json()
        if result['status'] != 'running':
            return result
        time.sleep(0.01)
    pytest.fail('수집 작업이 종료되지 않았습니다.')


def test_user_question_becomes_real_frame_request_and_downloadable_result(tmp_path, monkeypatch):
    calls = connect_providers(monkeypatch)
    with TestClient(create_app(Settings(openai_key='', tavily_key='test-key',
                                       database=tmp_path / 'db.sqlite3'))) as client:
        started = client.post('/api/collections', json={'question': QUESTION,
                              'languages': ['ko', 'ja', 'en'], 'event_date': '2026-10-01',
                              'days_back': 30, 'max_docs_per_country': 2})
        assert started.status_code == 202
        result = await_collection(client, started.json()['id'])
        assert result['status'] == 'completed', result.get('error')
        assert result['input']['question'] == QUESTION
        request = result['collection_request']
        assert request['event'] == '대만해협 군사활동'
        assert request['event_date'] == '2026-10-01'
        assert request['selected_languages'] == ['ko', 'ja', 'en']
        assert ['China', '中国', '중국'] == sorted(request['relevance_context']['anchor_groups'][1])
        english = next(q['query'] for q in request['queries'] if q['language'] == 'en')
        retrieval = next(q['search_query'] for q in request['queries'] if q['language'] == 'en')
        assert 'Taiwan Strait' in retrieval and 'China' in retrieval
        assert '2026-10-01' in retrieval
        assert 'unverified claims' not in retrieval
        assert 'Taiwan authorities' in english
        assert '2026-10-01' in english
        assert all(term in english for term in ('both sides', 'positions', 'matching claims',
                                                'conflicting claims', 'unverified claims', 'with sources'))
        assert retrieval in [call['query'] for call in calls['tavily']]
        assert all(call['time_range'] == 'month' for call in calls['tavily'])
        output = result['output']
        assert output['total_count'] == 1  # 같은 기사 재검색은 실제 frame이 중복 제거한다.
        assert output['by_country']['US'][0]['url'].startswith('https://www.reuters.com/')
        assert output['documents'][0]['paragraphs'][0]['raw_text']
        assert output['queries']['en'] == retrieval
        assert result['llm_trace']['response']['model_release']['released'] is True
        paths = [path for path, _ in calls['ollama']]
        assert paths.index('/api/generate') > paths.index('/api/chat')
        downloaded = client.get('/api/collections/' + result['id'] + '/download')
        assert downloaded.status_code == 200
        assert downloaded.json()['output'] == output
        assert 'test-key' not in downloaded.text


@pytest.mark.parametrize('incomplete,search_error', [(True, False), (False, True)])
def test_provider_failures_are_not_reported_as_success(tmp_path, monkeypatch, incomplete, search_error):
    calls = connect_providers(monkeypatch, incomplete=incomplete, search_error=search_error)
    with TestClient(create_app(Settings(openai_key='', tavily_key='test-key',
                                       database=tmp_path / 'db.sqlite3'))) as client:
        response = client.post('/api/collections', json={'question': QUESTION, 'languages': ['en']})
        assert response.status_code == 202
        result = await_collection(client, response.json()['id'])
        assert result['status'] == 'failed'
        assert result['error']
        assert 'provider-secret-detail' not in json.dumps(result)
        if incomplete:
            assert not calls['tavily']
        else:
            assert result['collection_request']['queries']


def test_collection_requires_tavily_key_but_not_openai(tmp_path):
    with TestClient(create_app(Settings(openai_key='', tavily_key='',
                                       database=tmp_path / 'db.sqlite3'))) as client:
        assert client.post('/api/collections', json={'question': QUESTION}).status_code == 503


@pytest.mark.parametrize('count', [6, 20])
def test_collection_accepts_document_counts_offered_by_screen(tmp_path, monkeypatch, count):
    calls = connect_providers(monkeypatch)
    with TestClient(create_app(Settings(openai_key='', tavily_key='test-key',
                                       database=tmp_path / 'db.sqlite3'))) as client:
        response = client.post('/api/collections', json={
            'question': QUESTION, 'languages': ['en'], 'max_docs_per_country': count,
        })
        assert response.status_code == 202, response.text
        result = await_collection(client, response.json()['id'])
        assert result['status'] == 'completed', result.get('error')
        assert result['input']['max_docs_per_country'] == count
        assert calls['tavily']
        assert result['output']['total_count'] == 1


def test_changed_party_translation_stops_before_tavily(tmp_path, monkeypatch):
    calls = connect_providers(monkeypatch, incorrect_translation=True)
    with TestClient(create_app(Settings(openai_key='', tavily_key='test-key',
                                       database=tmp_path / 'db.sqlite3'))) as client:
        response = client.post('/api/collections', json={'question': QUESTION, 'languages': ['en']})
        result = await_collection(client, response.json()['id'])
        assert result['status'] == 'failed'
        assert not calls['tavily']


def test_unselected_korean_query_does_not_reach_collection(tmp_path, monkeypatch):
    calls = connect_providers(monkeypatch)
    with TestClient(create_app(Settings(openai_key='', tavily_key='test-key',
                                       database=tmp_path / 'db.sqlite3'))) as client:
        response = client.post('/api/collections', json={'question': QUESTION, 'languages': ['en']})
        result = await_collection(client, response.json()['id'])
        assert result['status'] == 'completed', result.get('error')
        assert [q['language'] for q in result['collection_request']['queries']] == ['en']
        assert len(calls['tavily']) == 1
        assert result['output']['filtering']['selected_languages'] == ['en']


def test_explicit_date_cannot_disappear_in_common_meaning():
    from app.errors import AnalysisError
    from app.search_pipeline import CommonMeaning, check_meaning
    meaning = CommonMeaning(event='대만해협 군사활동', event_date=None, place='대만해협',
                            parties=['중국', '대만 당국'], focus=['입장'],
                            targets=[{'id': 'positions', 'label': '입장', 'subject': '양측 입장'}])
    with pytest.raises(AnalysisError):
        check_meaning(meaning, '2026년 10월 1일 ' + QUESTION)


def test_frame_response_counts_only_documents_retained_in_country_groups(monkeypatch):
    def search(_client, **_kwargs):
        return {'results': [{'url': f'https://www.reuters.com/world/asia-pacific/item-{n}/',
                             'title': f'Article number {n}', 'score': 0.9,
                             'raw_content': f'Distinct opening for article {n}. ' + 'News about authorities and military activities. ' * 5}
                            for n in range(3)]}
    monkeypatch.setattr(TavilyClient, 'search', search)
    output = OSINTCollector(api_key='test-key').collect_plan(
        {'event': '대만해협 군사활동', 'queries': [{'language': 'en', 'query': 'Taiwan Strait'}]},
        max_results_per_query=3, max_docs_per_country=1)
    assert output['total_count'] == 1
    assert len(output['documents']) == 1
    assert len(output['by_country']['US']) == 1


@pytest.mark.parametrize('extra', [{'languages': ['en', 'en']}, {'languages': []},
                                  {'event_date': '2026-02-30'}, {'max_docs_per_country': 50},
                                  {'question': '        '}])
def test_invalid_collection_input_is_rejected(tmp_path, extra):
    with TestClient(create_app(Settings(openai_key='', tavily_key='test-key',
                                       database=tmp_path / 'db.sqlite3'))) as client:
        assert client.post('/api/collections', json={'question': QUESTION, **extra}).status_code == 422
