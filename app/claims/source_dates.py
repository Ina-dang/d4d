"""Only retain complete dates literally supported by the quoted evidence."""
import calendar
import re
from datetime import date


def explicit_date(quote: str, value: date) -> bool:
    year, month, day = value.year, value.month, value.day
    # Ambiguous numeric day/month ordering and relative dates remain unknown.
    patterns = [
        rf'(?<!\d){year}[-/.]0?{month}[-/.]0?{day}(?!\d)',
        rf'{year}\s*(?:년|年)\s*0?{month}\s*(?:월|月)\s*0?{day}\s*(?:일|日)',
    ]
    months = f'(?:{calendar.month_name[month]}|{calendar.month_abbr[month]}\\.?)'
    patterns.extend([
        rf'\b{months}\s+0?{day}(?:st|nd|rd|th)?(?:,\s*|\s+){year}\b',
        rf'\b0?{day}\s+{months}\s+{year}\b',
    ])
    return any(re.search(pattern, quote, re.IGNORECASE) for pattern in patterns)
