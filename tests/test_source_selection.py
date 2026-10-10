from unittest.mock import patch

from app.source_selection import SequenceMatcher, source_candidates


def test_many_short_sentences_do_not_enumerate_all_sentence_combinations():
    text = '가。' * 3000
    with patch('app.source_selection.SequenceMatcher', wraps=SequenceMatcher) as matcher:
        candidates = source_candidates([{'paragraph_id': 'p1', 'raw_text': text}], '가。' * 8)
    assert matcher.call_count <= 33  # One paragraph scan plus at most 8 * 4 candidate comparisons.
    assert candidates
    assert all(c['original_quote'] in text and c['paragraph_id'] == 'p1' for c in candidates)
