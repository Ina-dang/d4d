"""LLM은 문장 번호를 선택하고 인용 원문은 코드가 그대로 보존한다."""

import re
from datetime import date
from typing import Literal

from pydantic import Field

from app.claims.source_analysis import QUOTE_CHARS, ClaimDraft, Extraction, Schema
from app.core.errors import AnalysisError


class SnippetClaim(Schema):
    quote_id: int = Field(ge=1, strict=True)
    translated_quote: str = Field(min_length=1, max_length=QUOTE_CHARS)
    expression: Literal['예정', '추정', '부정', '미확인', '가능', '발표']
    event_date: date | None


class SnippetExtraction(Schema):
    claims: list[SnippetClaim] = Field(max_length=5)


def substantive_quotes(quotes):
    """링크만 있는 문장과 명시적인 참고 링크 목록은 주장 후보가 아니다."""
    result = []
    for quote in quotes:
        text = quote['original_quote'].strip()
        if re.fullmatch(r'(?:https?://|www\.)\S+|(?:com|org|net|cn|tw|hk|jp|kr|edu|gov|io)/\S+',
                        text, re.I):
            continue
        if re.match(r'^(?:References?|Sources?|참고\s*자료|출처|参考资料|參考資料)\s*[:：]', text, re.I):
            continue
        result.append(quote)
    return result


def snippet_quotes(block, *, reject_oversize=True):
    quotes = []
    for paragraph in block:
        text = paragraph['raw_text']
        start = 0
        for match in re.finditer(r'[。！？][」』”\"]*|[.!?][”’\"\)\]]*(?=\s|$)', text):
            end = match.end()
            prefix = text[:end].rstrip('”’")]').lower()
            # 일부 수집 snippet은 U.S.를 U. S.로 보존한다. 이 경우도 약어다.
            if (re.search(r'\b[a-z]\.$', prefix)
                    and re.match(r'\s*[A-Za-z]\.', text[end:])):
                continue
            if re.search(r'\b(?:[a-z]\.\s*){2,}$|\b(?:mr|mrs|ms|dr|prof|inc|corp|ltd|co|'
                         r'jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|vs|etc|no)\.$', prefix):
                continue
            span = text[start:end].strip()
            if span:
                quotes.append({'quote_id': len(quotes) + 1,
                               'paragraph_id': paragraph['paragraph_id'], 'original_quote': span})
            start = end
        tail = text[start:].strip()
        if tail:
            quotes.append({'quote_id': len(quotes) + 1,
                           'paragraph_id': paragraph['paragraph_id'], 'original_quote': tail})
    if reject_oversize and any(len(quote['original_quote']) > QUOTE_CHARS for quote in quotes):
        raise AnalysisError('snippet의 단일 문장이 인용 한도 1,600자를 초과했습니다.')
    return quotes


def grounded_extraction(selected, quotes):
    by_id = {quote['quote_id']: quote for quote in quotes}
    if len({claim.quote_id for claim in selected.claims}) != len(selected.claims):
        raise AnalysisError('동일한 snippet 문장 번호를 중복 선택했습니다.')
    claims = []
    for claim in selected.claims:
        quote = by_id.get(claim.quote_id)
        if quote is None:
            raise AnalysisError('응답에 요청하지 않은 snippet 문장 번호가 있습니다.')
        claims.append(ClaimDraft(
            paragraph_id=quote['paragraph_id'], original_quote=quote['original_quote'],
            translated_quote=claim.translated_quote, expression=claim.expression,
            event_date=claim.event_date))
    return Extraction(claims=claims)
