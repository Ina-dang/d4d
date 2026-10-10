"""Body-only language detection and conservative topic evidence gates.

Topic anchors come from the search plan's common meaning and translations.
These gates select collection candidates; they do not verify article claims.
"""

import re
import unicodedata

from langdetect import DetectorFactory
from langdetect.detector_factory import PROFILES_DIRECTORY
from langdetect.lang_detect_exception import LangDetectException

_FACTORY = DetectorFactory()
_FACTORY.load_profile(PROFILES_DIRECTORY)
_FACTORY.seed = 0

# A bounded domain vocabulary, rather than a dictionary of individual events.
SECURITY_TERMS = (
    'military', 'army', 'armed forces', 'troops', 'warship', 'navy', 'naval', 'missile',
    'airstrike', 'air strike', 'border', 'terror', 'ceasefire', 'nuclear',
    '군사', '군대', '군함', '해군', '공습', '미사일', '국경', '테러', '휴전', '핵무기',
    '軍事', '军事', '軍隊', '军队', '軍艦', '军舰', '海軍', '海军', '空襲', '空袭',
    '導彈', '导弹', '邊境', '边境', '恐怖', '停火', '核武', '軍用機', '军用机',
    '部隊', '空爆', 'ミサイル', '国境', 'テロ', '停戦', '核兵器',
    'सैन्य', 'सेना', 'सीमा', 'आतंक', 'गोलीबारी', 'युद्धपोत', 'नौसेना', 'मिसाइल',
    'فوج', 'سرحد', 'دہشت', 'فائرنگ', 'جنگی جہاز', 'بحری', 'میزائل',
    'کشیدگی', 'تنازع', 'جارحیت', 'حملہ', 'حملے', 'جنگی', 'ایٹمی جنگ', 'جھڑپ', 'مسلح',
)

# Remove institutional qualifiers so a body mentioning the party still matches.
QUALIFIERS = (' authorities', ' government', ' 당국', ' 정부', '当局', '當局',
              '政府', '当局', ' अधिकारियों', ' सरकार', ' حکام', ' حکومت')
ENTITY_VARIANTS = {
    '인도': ('India', 'Indian', 'भारत', 'हिंदुस्तान', 'بھارت', 'انڈیا', 'ہندوستان'),
    '파키스탄': ('Pakistan', 'Pakistani', 'पाकिस्तान', 'پاکستان'),
}


def normalize(text: str) -> str:
    return unicodedata.normalize('NFKC', text).casefold()


def detect_body_language(text: str) -> dict:
    # Sample across the body; a site's English navigation must not dominate the first page.
    if len(text) > 12000:
        middle = len(text) // 2
        sample = text[:4000] + '\n' + text[middle - 2000:middle + 2000] + '\n' + text[-4000:]
    else:
        sample = text
    result = {'method': 'body_langdetect', 'language': 'unknown', 'confidence': 0.0,
              'sample_chars': len(sample)}
    if sum(char.isalpha() for char in sample) < 40:
        return result
    try:
        detector = _FACTORY.create()
        detector.append(sample)
        candidates = detector.get_probabilities()
    except LangDetectException:
        return result
    if candidates:
        best = candidates[0]
        result.update(raw_language=best.lang, confidence=round(best.prob, 4))
        if best.prob >= 0.8:
            result['language'] = {'zh-cn': 'zh', 'zh-tw': 'zh-Hant'}.get(best.lang, best.lang)
    return result


def contains(text: str, term: str) -> bool:
    term = normalize(term).strip()
    if not term:
        return False
    # Latin names must be words (India must not match Indiana).
    if re.fullmatch(r'[a-z ]+', term):
        endings = '(?:n)?' if term == 'india' else '(?:i)?' if term == 'pakistan' else ''
        return bool(re.search(r'(?<![a-z])' + re.escape(term) + endings + r'(?![a-z])', text))
    return term in text


def anchor_variants(group: list[str]) -> list[str]:
    result = list(group)
    for term in group:
        result.extend(ENTITY_VARIANTS.get(term, ()))
        for suffix in QUALIFIERS:
            if term.endswith(suffix):
                result.append(term[:-len(suffix)])
    return [value for value in dict.fromkeys(result) if value.strip()]


def topic_evidence(text: str, context: dict | None, title: str = '') -> tuple[str | None, dict]:
    if not context:
        return None, {'method': 'body_anchors', 'checked': False}
    groups = [anchor_variants(group) for group in context.get('anchor_groups', []) if group]
    body = normalize(text)
    if not groups:
        return 'topic_context_missing', {'method': 'body_anchors', 'checked': False}
    matched = [next((term for term in group if contains(body, term)), '') for group in groups]
    evidence = {'method': 'body_anchors', 'checked': True, 'matched_anchors': matched}
    if not all(matched):
        return 'topic_anchors_missing', evidence
    if title and context.get('security_topic'):
        # Headline or lead must put the parties/place in focus; later background mentions are insufficient.
        heading = re.search(r'^#{1,2}\s+[^\n]+', text, re.MULTILINE)
        main = text[heading.end():] if heading else text
        blocks = [block.strip() for block in re.split(r'\n\s*\n', main)]
        lead = next((block for block in blocks if sum(char.isalpha() for char in block) >= 60
                     and not block.startswith(('#', '*   ', '*       '))), '')
        lead = re.split(r'(?<=[.!?۔。،])\s*', lead, maxsplit=1)[0][:400]
        headline = normalize(title + ' ' + (heading.group() if heading else ''))
        if not any(contains(headline, term) for group in groups for term in group) and not all(
            any(contains(normalize(lead), term) for term in group) for group in groups
        ):
            return 'topic_background_only', evidence
    # Require co-occurrence near substantive topic evidence, rather than matches far apart in menus.
    for offset in range(0, len(text), 750):
        window = text[offset:offset + 1500]
        normalized = normalize(window)
        if not all(any(contains(normalized, term) for term in group) for group in groups):
            continue
        security = next((term for term in SECURITY_TERMS if contains(normalized, term)), '')
        if context.get('security_topic') and not security:
            continue
        evidence.update(security_term=security, excerpt=window[:1500])
        return None, evidence
    return ('security_topic_missing' if context.get('security_topic')
            else 'topic_anchors_not_connected'), evidence
