"""Restore omitted link markup only when visible words identify one exact source span."""
import re

# Unsupported/nested markup stays on the normal LLM repair path.
_LINK = re.compile(r'(?<![!\\])\[([^\[\]\\\n]+)\]\(https?://[^\s()]+\)')


def restore_markdown_quote(source: str, quote: str) -> str | None:
    labels = {match.group(1) for match in _LINK.finditer(source)}
    # Some models keep [label] but omit only (url); accept only labels of actual source links.
    quote = re.sub(r'(?<![!\\])\[([^\[\]\\\n]+)\](?!\()',
                   lambda match: match.group(1) if match.group(1) in labels else match.group(0),
                   quote)
    visible, spans = [], []
    cursor = 0
    for match in _LINK.finditer(source):
        for index in range(cursor, match.start()):
            visible.append(source[index])
            spans.append((index, index + 1))
        label = match.group(1)
        for index, char in enumerate(label):
            visible.append(char)
            spans.append((match.start() if index == 0 else match.start(1) + index,
                          match.end() if index == len(label) - 1 else match.start(1) + index + 1))
        cursor = match.end()
    if not cursor or not quote:
        return None
    for index in range(cursor, len(source)):
        visible.append(source[index])
        spans.append((index, index + 1))
    text = ''.join(visible)
    start = text.find(quote)
    if start < 0 or text.find(quote, start + 1) >= 0:
        return None
    exact = source[spans[start][0]:spans[start + len(quote) - 1][1]]
    # The candidate must contain complete link labels and unchanged words/whitespace.
    return exact if _LINK.sub(r'\1', exact) == quote else None
