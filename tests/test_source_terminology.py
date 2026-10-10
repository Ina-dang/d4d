from app.claims.source_terminology import normalize_source_terminology


def result(original, translated):
    return {'claims': [{'claim_id': 'a-c1', 'original_quote': original,
                        'translated_quote': translated}], 'warnings': []}


def test_consensus_name_is_not_changed_into_september_second_agreement():
    data = result('拒不承认体现一个中国原则的“九二共识”', '하나의 중국 원칙을 구현하는 9·2 합의를 인정하지 않는다.')
    corrections = normalize_source_terminology(data)
    assert data['claims'][0]['translated_quote'] == '하나의 중국 원칙을 구현하는 92 컨센서스(1992년 합의)를 인정하지 않는다.'
    assert corrections[0]['source_terms'] == ['九二共识']
    assert '9·2 합의' in corrections[0]['before']
    assert normalize_source_terminology(data) == []


def test_actual_september_second_date_without_source_term_is_untouched():
    data = result('9月2日签署协议', '9월 2일 합의를 체결했다.')
    assert normalize_source_terminology(data) == []
    assert data['claims'][0]['translated_quote'] == '9월 2일 합의를 체결했다.'


def test_person_names_are_normalized_only_with_corresponding_original_name():
    data = result('張晗表示，頼清徳当局', '장한잉은 뤄칭덕 당국을 비판했다.')
    normalize_source_terminology(data)
    assert data['claims'][0]['translated_quote'] == '장한은 라이칭더 당국을 비판했다.'
    data = result('其他人表示', '장한잉은 뤄칭덕 당국을 비판했다.')
    assert normalize_source_terminology(data) == []


def test_source_guard_corrects_new_lai_and_aircraft_mistranslations():
    data = result('台湾の頼清徳当局', '대만의 뤄징더 당국')
    normalize_source_terminology(data)
    assert data['claims'][0]['translated_quote'] == '대만의 라이칭더 당국'
    data = result('偵獲共機3架次', '공습기 3대를 탐지했다.')
    normalize_source_terminology(data)
    assert data['claims'][0]['translated_quote'] == '중국 군용기 3대를 탐지했다.'
    data = result('台湾は不分の一部である', '대만은 분할될 수 있는 일부이다.')
    normalize_source_terminology(data)
    assert data['claims'][0]['translated_quote'] == '대만은 불가분의 일부이다.'
