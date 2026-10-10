import pytest

from app.source_quotes import restore_markdown_quote, restore_transcript_quote


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
    ('[Taiwan](https://example.com) and [PLA](https://example.com/p) spoke.',
     '[Taiwan] and [PLA] spoke.', '[Taiwan](https://example.com) and [PLA](https://example.com/p) spoke.'),
    ('[Taiwan](https://example.com) and [PLA](https://example.com/p) spoke.',
     '[Taiwan] and PLA spoke.', '[Taiwan](https://example.com) and [PLA](https://example.com/p) spoke.'),
    ('[Taiwan](https://example.com) had seen changes.', '[Taiwan] has seen changes.', None),
])
def test_only_unique_unchanged_visible_words_restore_a_raw_span(source, quote, expected):
    assert restore_markdown_quote(source, quote) == expected


@pytest.mark.parametrize('source,quote,expected', [
    ('[0:00] They had seen\n\n[0:08] 15 aircraft.', 'They had seen 15 aircraft.',
     'They had seen\n\n[0:08] 15 aircraft.'),
    ('[0:00] They had seen\n\n[0:08] 15 aircraft.', 'They have seen 15 aircraft.', None),
    ('[0:00] They had seen\n\n[0:08] 15 aircraft.', 'They had seen 12 aircraft.', None),
    ('[0:00] They spoke.\n\n[0:08] They spoke.', 'They spoke.', None),
    ('[0:00] 군사 활동이\n\n[0:08] 늘 수 있다.', '군사 활동이 늘 수 있다.',
     '군사 활동이\n\n[0:08] 늘 수 있다.'),
])
def test_transcript_restoration_changes_only_time_markers_and_whitespace(source, quote, expected):
    assert restore_transcript_quote(source, quote) == expected
