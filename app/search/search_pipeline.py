"""공통 의미 추출 → 언어별 항목 번역. 분석 목적은 별도로 보존한다."""

import json
import re
import time
from datetime import date

from pydantic import Field

from app.core.errors import AnalysisError
from app.core.paths import PROMPTS
from app.search.search_schemas import Language, Schema, SearchPlan, SearchQuery, Target

PURPOSE_KEYS = ('comparison', 'both_sides', 'major_reports', 'positions',
                'matching', 'conflicting', 'unverified', 'sources')
# 사건별 사전이 아니라 검색 계획의 고정된 작업 의도를 표시하는 현지화 문구다.
PURPOSES = {
    'ko': ('비교', '양측', '주요 보도', '입장', '일치하는 주장', '상충하는 주장', '미확인 주장', '출처 포함'),
    'zh': ('对比', '双方', '主要新闻报道', '立场', '一致的主张', '相互矛盾的主张', '未经证实的主张', '附来源'),
    'zh-Hant': ('對比', '雙方', '主要新聞報導', '立場', '一致的主張', '相互矛盾的主張', '未經證實的主張', '附來源'),
    'ja': ('比較', '双方', '主要報道', '立場', '一致する主張', '矛盾する主張', '未確認の主張', '出典付き'),
    'en': ('comparison', 'both sides', 'major news reports', 'positions', 'matching claims', 'conflicting claims', 'unverified claims', 'with sources'),
    'hi': ('तुलना', 'दोनों पक्ष', 'प्रमुख समाचार रिपोर्ट', 'रुख', 'मिलते-जुलते दावे', 'परस्पर विरोधी दावे', 'अपुष्ट दावे', 'स्रोतों सहित'),
    'ur': ('موازنہ', 'دونوں فریق', 'اہم خبری رپورٹس', 'مؤقف', 'مطابقت رکھنے والے دعوے', 'متضاد دعوے', 'غیر مصدقہ دعوے', 'ذرائع کے ساتھ'),
}
LANGUAGE_NAMES = {'zh': 'Simplified Chinese (简体中文)', 'ja': 'Japanese (日本語)',
                  'zh-Hant': 'Traditional Chinese (繁體中文)',
                  'en': 'English', 'hi': 'Hindi (हिन्दी, Devanagari script)',
                  'ur': 'Urdu (اردو, Urdu script)'}


class CommonMeaning(Schema):
    event: str = Field(min_length=2, max_length=120,
                       description='사건/활동 이름만 한국어로 짧게. 비교·분석 요청 전체를 제목으로 쓰지 않는다.')
    event_date: str | None
    place: str = Field(max_length=80)
    parties: list[str] = Field(max_length=6)
    focus: list[str] = Field(min_length=1, max_length=3,
                            description='비교할 내용/측정값. 발표 내용·입장·항공기 수 등. 일치/상충/미확인/출처는 이 필드가 아니다.')
    targets: list[Target] = Field(min_length=1, max_length=2)


class Translation(Schema):
    translations: list[str]


def requirements(question: str) -> dict[str, bool]:
    """명시된 한국어 작업 의도를 보존한다. 일반 자연어 의미 판정기는 아니다."""
    compact = re.sub(r'\s+', '', question)
    return {
        'comparison': '비교' in compact,
        'both_sides': any(s in compact for s in ('양측', '양쪽', '두당사자')),
        'major_reports': any(s in compact for s in ('주요보도', '주요뉴스')),
        'positions': '입장' in compact,
        'matching': bool(re.search(r'(?<!불)일치', compact)),
        'conflicting': any(s in compact for s in ('상충', '불일치', '모순')),
        'unverified': any(s in compact for s in ('미확인', '확인되지않', '검증되지않')),
        'sources': any(s in compact for s in ('출처', '근거자료')),
    }


def stage_request(model: str, schema: dict, system: str, data: dict) -> dict:
    return {
        'model': model, 'stream': False, 'think': False, 'keep_alive': '30s',
        'truncate': False, 'shift': False, 'format': schema,
        'options': {'temperature': 0.3, 'top_p': 0.9, 'top_k': 20, 'seed': 43,
                    'repeat_penalty': 1.05, 'num_ctx': 2048,
                    'num_batch': 256, 'num_predict': 768},
        'messages': [{'role': 'system', 'content': system},
                     {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}],
    }


def meaning_request(data: dict, model: str) -> dict:
    system = (PROMPTS / 'search_meaning.txt').read_text(encoding='utf-8')
    return stage_request(model, CommonMeaning.model_json_schema(), system,
                         {'question': data['question'], 'requirements': requirements(data['question'])})


def parse_stage(raw: dict, schema):
    if raw.get('done') is not True or raw.get('done_reason') != 'stop':
        raise AnalysisError('검색 단계 응답이 미완료이거나 출력 한도에 도달했습니다.')
    return schema.model_validate_json(raw['message']['content'])


def check_meaning(meaning: CommonMeaning, question: str) -> None:
    compact = re.sub(r'\s+', '', question)
    dates = set()
    for year, month, day in re.findall(r'(\d{4})(?:년|[-./])(\d{1,2})(?:월|[-./])(\d{1,2})일?', compact):
        try:
            dates.add(date(int(year), int(month), int(day)).isoformat())
        except ValueError:
            pass
    if meaning.event_date and meaning.event_date not in dates:
        raise AnalysisError('공통 의미의 날짜가 원문에 명시된 날짜와 일치하지 않습니다.')
    if dates and not meaning.event_date:
        raise AnalysisError('공통 의미에서 원문에 명시된 날짜가 누락됐습니다.')
    # 별도 지역 없이 당사자 목록을 place에 반복한 경우만 제거한다.
    # 각 당사자가 사용자 입력에 있어야 하며, 새 지역·국경 표현은 허용하지 않는다.
    party_anchors = {re.sub(r'측$', '', re.sub(r'\s+', '', name))
                     for name in meaning.parties}
    place_anchors = [re.sub(r'측$', '', re.sub(r'\s+', '', name))
                     for name in re.split(r'[,，、·]', meaning.place)]
    if (len(place_anchors) > 1 and len(set(place_anchors)) == len(place_anchors)
        and set(place_anchors) == party_anchors
        and all(anchor and anchor in compact for anchor in party_anchors)):
        meaning.place = ''
    for name in [meaning.place, *meaning.parties]:
        anchor = re.sub(r'\s+', '', name)
        if name in meaning.parties:
            anchor = re.sub(r'측$', '', anchor)
        if name and (not anchor or anchor not in compact):
            raise AnalysisError('공통 의미의 지역·당사자가 사용자 입력에서 확인되지 않습니다: ' + name)
    if requirements(question)['both_sides'] and len(set(meaning.parties)) < 2:
        raise AnalysisError('공통 의미에서 양측 당사자가 누락됐습니다.')
    if '공동' not in question and '공동' in ' '.join(meaning.focus):
        raise AnalysisError('양측 발표가 공동 발표로 변경됐습니다.')
    if '전쟁' not in question and '전쟁' in meaning.event:
        raise AnalysisError('공통 의미의 충돌 범위가 전쟁으로 변경됐습니다.')
    labels = [t.id for t in meaning.targets]
    if len(labels) != len(set(labels)) or any(
        not re.search(r'[가-힣]', t.label) or not re.search(r'[가-힣]', t.subject)
        for t in meaning.targets
    ):
        raise AnalysisError('공통 비교 항목의 ID 또는 한국어 표기를 확인하세요.')


async def generate_search(ollama, data: dict, model: str, trace: dict) -> dict:
    languages: list[Language] = data.get('languages', [])
    if not languages or len(languages) != len(set(languages)) or any(language not in PURPOSES for language in languages):
        raise AnalysisError('검색어 언어는 지원 언어를 중복 없이 지정하세요.')
    request_log = trace['request']
    response_log = trace['response']
    request_log.update(pipeline='common-meaning-v1', model=model, stages=[])
    response_log.update(pipeline='common-meaning-v1', stages=[])
    cache = getattr(ollama, 'cache', None)
    total = 1 + sum(language != 'ko' for language in languages)
    completed = 0

    def emit(detail):
        progress = getattr(ollama, 'progress', None)
        if progress:
            progress({'completed': completed, 'total': total, 'detail': detail,
                      'received_chars': 0})

    async def call(name: str, payload: dict) -> dict:
        if getattr(ollama, 'force_cpu', False):
            payload['options']['num_gpu'] = 0
        emit('질문의 공통 의미 분석 중' if name == 'meaning' else name.removeprefix('translate_') + ' 검색어 번역 중')
        request_log['stages'].append({'name': name, 'request': payload})
        record = {'name': name, 'response': None, 'cache_hit': False}
        response_log['stages'].append(record)
        started = time.perf_counter()
        try:
            raw = cache.read(payload) if cache else None
            if cache and raw is None and 'num_gpu' not in payload['options']:
                raw = cache.read({**payload, 'options': {**payload['options'], 'num_gpu': 0}})
                record['cpu_cache_reused'] = raw is not None
            if raw and raw.get('done') is True and raw.get('done_reason') == 'stop':
                record['cache_hit'] = True
            else:
                raw = await ollama.chat(payload)
            record['response'] = raw
            return raw
        finally:
            record['elapsed_seconds'] = round(time.perf_counter() - started, 3)

    meaning = parse_stage(await call('meaning', meaning_request(data, model)), CommonMeaning)
    original_place = meaning.place
    check_meaning(meaning, data['question'])
    completed += 1
    emit('질문의 공통 의미 확인 완료')
    if original_place != meaning.place:
        response_log['meaning_normalizations'] = [{'field': 'place', 'original': original_place,
                                                  'normalized': meaning.place,
                                                  'reason': 'explicit_party_list_duplicate'}]
    needed = requirements(data['question'])
    response_log.update(common_meaning=meaning.model_dump(), requirements=needed)
    fragments = [meaning.event, *([meaning.place] if meaning.place else []),
                 *meaning.parties, *meaning.focus]
    anchors = [*([meaning.place] if meaning.place else []), *meaning.parties]
    anchor_groups = [[value] for value in anchors]
    queries = []
    retrieval_queries = {}
    glossary = json.loads((PROMPTS / 'search_glossary.json').read_text(encoding='utf-8'))
    for language in languages:
        if language == 'ko':
            translated = fragments
        else:
            schema = Translation.model_json_schema()
            schema['properties']['translations'].update(minItems=len(fragments), maxItems=len(fragments))
            terms = {k: v[language] for k, v in glossary.items()
                     if k in data['question'] and language in v}
            system = (PROMPTS / 'search_translate.txt').read_text(encoding='utf-8')
            system += '\nThe ONLY target language is ' + LANGUAGE_NAMES[language] + '.'
            if language == 'ja':
                system += '\n出力は必ず自然な日本語。中国語の簡体字と中国語の文法を使わない。'
            payload = stage_request(model, schema, system, {
                'language': language, 'target_language': LANGUAGE_NAMES[language],
                'fragments': fragments, 'glossary': terms,
            })
            result = parse_stage(await call('translate_' + language, payload), Translation)
            translated = result.translations
            if len(translated) != len(fragments) or any(not t.strip() for t in translated):
                raise AnalysisError('번역 항목이 누락되거나 추가됐습니다: ' + language)
            if language in ('en', 'hi', 'ur') and any(re.search(r'[가-힣\u0400-\u04ff]', t) for t in translated):
                raise AnalysisError('번역 항목에 다른 언어 문자가 섞였습니다: ' + language)
            if language == 'ja' and any(re.search(r'[军场对较发说]', t) for t in translated):
                raise AnalysisError('일본어 번역 항목에 중국어 간체자가 섞였습니다.')
        parts = [*translated, *[text for key, text in zip(PURPOSE_KEYS, PURPOSES[language], strict=True)
                               if needed[key]]]
        if meaning.event_date:
            parts.append(meaning.event_date)
        query = '; '.join(dict.fromkeys(p.strip() for p in parts))
        for term, translations in glossary.items():
            translation = translations.get(language)
            alternatives = translations.get('alternatives', {}).get(language, [])
            allowed = [translation, *alternatives] if translation else []
            if term in data['question'] and allowed and not any(
                value.casefold() in query.casefold() for value in allowed
            ):
                raise AnalysisError('검색어 용어 보존 검사 실패: ' + language + ' / ' + term)
        if '항공기' in data['question'] and not any(word in data['question'] for word in ('군용', '전투')):
            narrowed = {'zh': ('军用', '军机', '战斗机'), 'zh-Hant': ('軍用', '軍機', '戰鬥機'),
                        'ja': ('軍用', '軍機', '戦闘機'),
                        'en': ('military aircraft', 'combat aircraft', 'fighter', 'warplane')}
            if any(word.casefold() in query.casefold() for word in narrowed.get(language, ())):
                raise AnalysisError('일반 항공기가 군용기로 변경됐습니다: ' + language)
        if len(query) > 600:
            raise AnalysisError('검색어가 600자를 초과했습니다. 항목을 자동으로 자르지 않았습니다.')
        if language != 'ko':
            completed += 1
            emit(language + ' 검색어 검증 완료')
        queries.append(SearchQuery(language=language, query=query))
        # Keep each party and substantive focus. Substring dedup would discard
        # Taiwan when Taiwan Strait was already present, and drop statement searches.
        retrieval_parts = []
        for value in translated:
            if value.strip().casefold() not in {part.casefold() for part in retrieval_parts}:
                retrieval_parts.append(value.strip())
        retrieval_queries[language] = ' '.join(retrieval_parts)
        if meaning.event_date:
            retrieval_queries[language] += ' ' + meaning.event_date
        for index, group in enumerate(anchor_groups, start=1):
            if translated[index] not in group:
                group.append(translated[index])
    # 모델의 항목 후보가 분석 상태만 나열해도 명시된 비교 대상을 잃지 않는다.
    targets = []
    if needed['positions']:
        targets.append(Target(id='positions', label='입장', subject='양측 입장' if needed['both_sides'] else '당사자의 입장'))
    if needed['major_reports']:
        targets.append(Target(id='statements_reports', label='발표·주요 보도 내용',
                              subject='양측 발표와 주요 보도의 내용' if needed['both_sides'] else '주요 보도의 내용'))
    if not targets:
        targets = list(meaning.targets)
    states = [label for key, label in (('matching', '일치하는 주장'),
              ('conflicting', '상충하는 주장'), ('unverified', '미확인 주장')) if needed[key]]
    reserved = set(t.id for t in targets)
    def add_target(base: str, label: str, subject: str):
        name = base
        while name in reserved:
            name += '_'
        reserved.add(name)
        targets.append(Target(id=name, label=label, subject=subject))
    if states:
        add_target('claim_states', ' · '.join(states), '양측 발표·보도의 주장 비교' if needed['major_reports'] else '양측 주장의 비교')
    if needed['sources']:
        add_target('sources', '출처', '각 주장에 대응하는 원문 출처')
    plan = SearchPlan(event=meaning.event, event_date=meaning.event_date, queries=queries, targets=targets)
    response_log.update(done=True, done_reason='stop',
                        message={'role': 'assistant', 'content': plan.model_dump_json()},
                        assembled_output=plan.model_dump(),
                        retrieval_queries=retrieval_queries,
                        relevance_context={'anchor_groups': anchor_groups,
                                           'security_topic': any(term in data['question'] for term in
                                               ('충돌', '군사', '분쟁', '전쟁', '교전', '공습'))})
    for key in ('prompt_eval_count', 'eval_count', 'total_duration', 'load_duration', 'eval_duration'):
        response_log[key] = sum(stage['response'].get(key, 0) for stage in response_log['stages']
                                if not stage['cache_hit'])
    # 날짜·용어·언어·스키마 검사와 계획 조립까지 통과한 요청만 재사용한다.
    if cache:
        for sent, received in zip(request_log['stages'], response_log['stages'], strict=True):
            if not received['cache_hit']:
                cache.write(sent['request'], received['response'])
    return response_log
