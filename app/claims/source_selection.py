"""Repeated copy failures use source IDs; approximate matching only proposes candidates."""
import re
from bisect import bisect_left, bisect_right
from datetime import date
from difflib import SequenceMatcher
from typing import Literal

from pydantic import Field

from app.claims.source_analysis import QUOTE_CHARS, ClaimDraft, Schema
from app.core.errors import AnalysisError


class SourceSelection(Schema):
    claim_index: int = Field(ge=1, le=12, strict=True)
    quote_id: int | None = Field(ge=1, strict=True)
    translated_quote: str = Field(min_length=1, max_length=QUOTE_CHARS)
    expression: Literal['예정', '추정', '부정', '미확인', '가능', '발표']
    event_date: date | None


class SourceSelections(Schema):
    selections: list[SourceSelection] = Field(min_length=1, max_length=12)


def source_candidates(block, quote):
    # Anchor around the longest matching source fragments first. Do not compare
    # every possible sentence combination (quadratic for many short sentences).
    anchors = []
    for paragraph in block:
        for match in SequenceMatcher(None, quote, paragraph['raw_text'], autojunk=False).get_matching_blocks():
            if match.size:
                anchors.append((match.size, match.b, paragraph))
    candidates = {}
    for size, offset, paragraph in sorted(anchors, key=lambda a: a[0], reverse=True)[:8]:
        text = paragraph['raw_text']
        boundaries = sorted({0, len(text), *[m.end() for m in re.finditer(
            r'\n+|[。！？]|[.!?](?=\s|$)', text)]})
        first = bisect_right(boundaries, offset) - 1
        last = bisect_left(boundaries, offset + size)
        for start in boundaries[max(0, first - 1):first + 1]:
            for end in boundaries[last:last + 2]:
                span = text[start:end].strip()
                if span and len(span) <= QUOTE_CHARS:
                    candidates[(paragraph['paragraph_id'], span)] = SequenceMatcher(
                        None, quote, span, autojunk=False).ratio()
    ranked = sorted(candidates, key=candidates.get, reverse=True)[:3]
    return [{'quote_id': i, 'paragraph_id': pid, 'original_quote': span}
            for i, (pid, span) in enumerate(ranked, 1)]


def selected_claim(selection, candidates):
    if selection.quote_id is None:
        return None
    candidate = next((c for c in candidates if c['quote_id'] == selection.quote_id), None)
    if candidate is None:
        raise AnalysisError('응답에 요청하지 않은 원문 인용 후보 번호가 있습니다.')
    return ClaimDraft(paragraph_id=candidate['paragraph_id'],
        original_quote=candidate['original_quote'], translated_quote=selection.translated_quote,
        expression=selection.expression, event_date=selection.event_date)
