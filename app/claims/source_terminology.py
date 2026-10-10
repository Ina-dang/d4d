"""원문에 있는 고유명칭의 알려진 오역만 보정한다. 새 주장을 생성하지 않는다."""

import re

RULES = (
    (('九二共识', '九二共識', '92年コンセンサス'),
     r'9\s*[·.]\s*2\s*합의|9월\s*2일\s*합의', '92 컨센서스(1992년 합의)'),
    (('赖清德', '賴清德', '頼清徳', 'Lai Ching-te'),
     r'뤄칭덕|라칭덕|라이칭덕|뤄징더', '라이칭더'),
    (('共機', '共机'), r'공습기', '중국 군용기'),
    (('不可分の一部', '不分の一部'), r'분할될\s*수\s*있는\s*일부', '불가분의 일부'),
    (('张晗', '張晗'), r'장한잉', '장한'),
    (('国务院台办', '國務院臺辦', '国務院台湾事務弁公室'),
     r'국무원\s*대만총국', '중국 국무원 대만사무판공실'),
)


def normalize_source_terminology(result):
    corrections = []
    for claim in result['claims']:
        original = claim['original_quote']
        before = claim['translated_quote']
        translated = before
        matched_terms = []
        for terms, pattern, replacement in RULES:
            term = next((term for term in terms if term.casefold() in original.casefold()), None)
            if term:
                updated = re.sub(pattern, replacement, translated)
                if updated != translated:
                    matched_terms.append(term)
                    translated = updated
        if translated != before:
            claim['translated_quote'] = translated
            corrections.append({'claim_id': claim['claim_id'], 'source_terms': matched_terms,
                                'before': before, 'after': translated, 'method': 'source_term_glossary'})
    if corrections:
        result.setdefault('terminology_normalizations', []).extend(corrections)
        result['warnings'].append(f'원문 고유명칭의 알려진 오역 {len(corrections)}개를 용어표로 보정했습니다. '
                                  '보정 전후를 상세 결과에 보존하며 전체 번역의 정확성을 보장하지 않습니다.')
    return corrections
