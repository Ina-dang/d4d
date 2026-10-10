from datetime import date

import pytest

from app.source_dates import explicit_date


@pytest.mark.parametrize('quote,expected', [
    ('Speaking on Wednesday, the official said the timetable could change.', False),
    ('He took office in 2024.', False),
    ('The event is scheduled for 2024-01-01.', True),
    ('The event is scheduled for 2024년 1월 1일.', True),
    ('2024年1月1日に予定されています。', True),
    ('The event is scheduled for January 1, 2024.', True),
    ('The event is scheduled for 1 Jan 2024.', True),
    ('The event is scheduled for 2024-01-02.', False),
    ('The event is scheduled for 01/01/2024.', False),
])
def test_only_explicit_unambiguous_complete_dates_are_retained(quote, expected):
    assert explicit_date(quote, date(2024, 1, 1)) is expected
