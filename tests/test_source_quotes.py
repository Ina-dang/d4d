import pytest

from app.source_quotes import restore_markdown_quote


@pytest.mark.parametrize('source,quote,expected', [
    ('Before [Taiwan](https://example.com/a?q=1) had seen changes.',
     'Taiwan had seen changes.', '[Taiwan](https://example.com/a?q=1) had seen changes.'),
    ('[Taiwan](https://example.com) had seen changes.', 'Taiwan has seen changes.', None),
    ('[the island](https://example.com) had seen changes.', 'Taiwan had seen changes.', None),
    ('[Taiwan](https://example.com/1) spoke. [Taiwan](https://example.com/2) spoke.', 'Taiwan spoke.', None),
    ('[Taiwan](https://example.com) spoke.', 'wan spoke.', None),
    ('[Taiwan](https://example.com) spoke.', 'Tai', None),
    ('[Taiwan](https://example.com) and [China](https://example.com/c) spoke.',
     'Taiwan and China spoke.', '[Taiwan](https://example.com) and [China](https://example.com/c) spoke.'),
    ('[Taiwan](https://example.com/a(b)) spoke.', 'Taiwan spoke.', None),
    ('[Taiwan](https://example.com)\nspoke.', 'Taiwan spoke.', None),
])
def test_only_unique_unchanged_visible_words_restore_a_raw_span(source, quote, expected):
    assert restore_markdown_quote(source, quote) == expected
