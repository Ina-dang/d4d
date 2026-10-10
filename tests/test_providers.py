import pytest

from app.config import Settings
from app.legacy.providers import balanced_candidates, make_source, publisher_group, safe_url

DOMAINS = ("mod.go.jp", "reuters.com")


@pytest.mark.parametrize(
    "url",
    [
        "http://mod.go.jp/a",
        "https://127.0.0.1/a",
        "https://localhost/a",
        "https://mod.go.jp.evil.example/a",
        "https://evilmod.go.jp/a",
        "https://user:password@mod.go.jp/a",
        "https://mod.go.jp:444/a",
        "javascript:alert(1)",
    ],
)
def test_url_guard(url):
    assert safe_url(url, DOMAINS) is None


def test_url_guard_allows_subdomain_and_strips_fragment():
    assert safe_url("https://www.mod.go.jp/a#b", DOMAINS) == "https://www.mod.go.jp/a"
    assert publisher_group("https://www.mod.go.jp/a", DOMAINS) == "mod.go.jp"


def test_source_truncation_is_explicit():
    settings = Settings(max_document_chars=2000)
    source = make_source("S1", "출처", "https://mod.go.jp/a", "a" * 3000, settings)
    assert source.truncated and sum(len(p.text) for p in source.paragraphs) == 2000
    assert len(source.content_hash) == 64 and source.published_at is None


def test_query_round_robin_preserves_language_budget():
    results = [
        [{"url": f"https://mod.go.jp/{lang}/{i}"} for i in range(3)] for lang in ("ko", "zh", "ja")
    ]
    selected = list(balanced_candidates(results, DOMAINS, 6))
    assert [url.split("/")[-2] for url in selected] == ["ko", "zh", "ja", "ko", "zh", "ja"]
