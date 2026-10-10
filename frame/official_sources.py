"""정부 웹사이트의 출처 커버리지. SNS의 도메인 분류는 공식 계정 증명이 아니다."""

from urllib.parse import urlparse

try:
    from .article_filters import anchor_variants, normalize
except ImportError:
    from article_filters import anchor_variants, normalize

OFFICIAL_DOMAINS = {'CN': ('mod.gov.cn', 'ccg.gov.cn', 'gwytb.gov.cn'),
                    'TW': ('mnd.gov.tw', 'president.gov.tw')}
PARTY_NAMES = {'CN': '중국', 'TW': '대만'}


def topic_context_for_source(context: dict | None, url: str) -> tuple[dict | None, str | None]:
    """정부 발표의 발행 주체만 도메인으로 확인한다. 지역·상대국은 본문에서 확인한다."""
    for country, name in PARTY_NAMES.items():
        if context and is_official_source(url, country):
            groups = context.get('anchor_groups', [])
            remaining = [group for group in groups if name not in anchor_variants(group)]
            if remaining and len(remaining) < len(groups):
                return {**context, 'anchor_groups': remaining}, country
    return context, None


def is_official_source(url: str, country: str | None = None) -> bool:
    hostname = (urlparse(url).hostname or '').lower()
    domains = OFFICIAL_DOMAINS.get(country, ()) if country else (
        domain for entries in OFFICIAL_DOMAINS.values() for domain in entries)
    return any(hostname == domain or hostname.endswith('.' + domain) for domain in domains)


def missing_official_countries(documents: list[dict], context: dict | None) -> list[str]:
    # Only countries explicitly present as party anchors trigger additional searches.
    groups = (context or {}).get('anchor_groups', [])
    names = {normalize(term) for group in groups for term in anchor_variants(group)}
    return [country for country, name in PARTY_NAMES.items() if normalize(name) in names
            and not any(is_official_source(doc.get('url', ''), country) for doc in documents)]
