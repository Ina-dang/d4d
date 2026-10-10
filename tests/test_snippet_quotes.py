import pytest

from app.claims.snippet_quotes import (
    SnippetExtraction,
    grounded_extraction,
    snippet_quotes,
    substantive_quotes,
)
from app.core.errors import AnalysisError


def block(text):
    return [{'paragraph_id': 'doc-snippet-p1', 'raw_text': text}]


def selection(ids):
    return SnippetExtraction.model_validate({'claims': [
        {'quote_id': quote_id, 'translated_quote': '원문 번역',
         'expression': '발표', 'event_date': None} for quote_id in ids]})


def test_sentence_ids_preserve_multilingual_punctuation_and_abbreviations():
    text = 'The U.S. announced 4.2 units. He said “stop.” 중국이 발표했다。 台灣回應了！'
    quotes = snippet_quotes(block(text))
    assert [q['original_quote'] for q in quotes] == [
        'The U.S. announced 4.2 units.', 'He said “stop.”', '중국이 발표했다。', '台灣回應了！']
    assert all(q['original_quote'] in text for q in quotes)
    result = grounded_extraction(selection([2, 4]), quotes)
    assert result.claims[0].original_quote == 'He said “stop.”'
    assert result.claims[1].paragraph_id == 'doc-snippet-p1'


@pytest.mark.parametrize('ids', [[10], [1, 1]])
def test_unknown_or_duplicate_quote_id_is_rejected(ids):
    with pytest.raises(AnalysisError, match='문장 번호'):
        grounded_extraction(selection(ids), snippet_quotes(block('实际原文。')))


def test_oversized_sentence_is_rejected_without_cutting():
    with pytest.raises(AnalysisError, match='1,600'):
        snippet_quotes(block('한' * 1601 + '。'))


def test_spaced_country_abbreviation_is_not_split_into_claim_fragments():
    text = 'Dialogue between China and the U. S. can reduce conflict. Taiwan welcomed it.'
    quotes = snippet_quotes(block(text))
    assert [quote['original_quote'] for quote in quotes] == [
        'Dialogue between China and the U. S. can reduce conflict.', 'Taiwan welcomed it.']


@pytest.mark.parametrize('sentences', [
    ['بھارت اور پاکستان کے درمیان کشیدگی ہے۔', 'اس کی وجہ کیا ہے؟', 'مذاکرات جاری ہیں۔'],
    ['भारत और पाकिस्तान के बीच तनाव है।', 'वार्ता जारी है॥', 'अगली बैठक कल होगी।'],
])
def test_indic_sentence_terminators_preserve_complete_original_quotes(sentences):
    source = ''.join(sentences)
    quotes = snippet_quotes(block(source))
    assert [item['original_quote'] for item in quotes] == sentences
    assert all(item['original_quote'] in source for item in quotes)


def test_pure_links_and_reference_lists_are_not_claim_candidates():
    raw = 'China announced drills. References: https://example.org. com/example/status/. Taiwan denied this.'
    quotes = snippet_quotes(block(raw))
    selected = substantive_quotes(quotes)
    assert [q['original_quote'] for q in selected] == ['China announced drills.', 'Taiwan denied this.']
    assert [q['quote_id'] for q in selected] == [1, 4]
    assert len(quotes) == 4
    assert all(q['original_quote'] in raw for q in quotes)


def test_fragmented_domain_footer_is_not_sent_to_korean_translation():
    text = ('The book discusses the Kashmir dispute. CSS Point | www. thecsspoint. '
            'com\\\\IndiaPakistan #KashmirDispute All reactions: 2. '
            'Both countries resumed negotiations.')
    selected = substantive_quotes(snippet_quotes(block(text)))
    assert [q['original_quote'] for q in selected] == [
        'The book discusses the Kashmir dispute.', 'Both countries resumed negotiations.']
    assert [q['quote_id'] for q in selected] == [1, 5]
