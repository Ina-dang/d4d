"""미니 RAG의 사건·원문·검색 계약. 세 종류의 점수는 서로 다른 필드다."""

from datetime import date
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from app.core.schemas import Schema


class RagEventInput(Schema):
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    start_date: date | None = None
    end_date: date | None = None
    is_demo: bool = False

    @field_validator("label")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("사건 이름이 비어 있습니다.")
        return value.strip()

    @model_validator(mode="after")
    def date_order(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("사건 범위의 시작일이 종료일보다 늦습니다.")
        return self


class RagParagraph(Schema):
    id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=60000)


class RagDocument(Schema):
    doc_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    url: str | None = Field(default=None, max_length=2000)
    text: str = Field(min_length=1, max_length=60000)
    raw_content: str | None = Field(default=None, max_length=60000)
    text_origin: Literal["raw", "cleaned", "paragraphs"] = "raw"
    paragraphs: list[RagParagraph] = Field(default_factory=list, max_length=500)
    language: str = Field(default="unknown", min_length=1, max_length=20)
    source_country: str = Field(default="UNKNOWN", min_length=1, max_length=40)
    publisher_group: str = Field(default="unknown", min_length=1, max_length=200)
    source_category: str | None = Field(default=None, max_length=100)
    source_cluster: str | None = Field(default=None, max_length=200)
    source_tier: int | None = Field(default=None, ge=1, le=10)
    tier_reason: str | None = Field(default=None, max_length=1000)
    credibility_weight: float | None = Field(default=None, ge=0, le=1)
    tavily_score: float | None = Field(default=None, ge=0, le=1)
    tavily_query: str | None = Field(default=None, max_length=1200)
    llm_relevance: float | None = Field(default=None, ge=0, le=1)
    published_date: date | None = None
    event_date: date | None = None
    collected_at: str | None = Field(default=None, max_length=100)
    content_kind: Literal["full", "truncated", "snippet", "unknown"] = "unknown"
    is_demo: bool = False
    needs_review: bool = False
    is_reprint_likely: bool = False
    quoted_source: str | None = Field(default=None, max_length=500)
    warnings: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("text", "doc_id", "title")
    @classmethod
    def not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("원문·문서 ID·제목은 비어 있을 수 없습니다.")
        return value

    @field_validator("url")
    @classmethod
    def public_link(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                    or parsed.password or parsed.port not in (None, 443)):
                raise ValueError("원문 링크는 사용자 정보 없는 HTTPS 주소여야 합니다.")
        except ValueError:
            raise ValueError("유효한 HTTPS 원문 링크가 필요합니다.") from None
        return value


class RagIngest(Schema):
    documents: list[RagDocument] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_ids(self):
        ids = [doc.doc_id for doc in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("한 적재 요청에 같은 문서 ID를 두 번 넣을 수 없습니다.")
        return self


class RagSearch(Schema):
    event_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    question: str = Field(min_length=2, max_length=1200)
    query_variants: list[str] = Field(default_factory=list, max_length=8)
    countries: list[str] = Field(default_factory=list, max_length=20)
    languages: list[str] = Field(default_factory=list, max_length=20)
    published_start: date | None = None
    published_end: date | None = None
    event_start: date | None = None
    event_end: date | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    include_snippets: bool = False
    include_demo: bool = False

    @field_validator("question")
    @classmethod
    def question_nonblank(cls, value: str) -> str:
        if len(value.strip()) < 2:
            raise ValueError("질문을 입력하세요.")
        return value.strip()

    @field_validator("query_variants")
    @classmethod
    def bounded_queries(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 1200 for value in values):
            raise ValueError("언어별 검색어는 1~1200자로 입력하세요.")
        return list(dict.fromkeys(value.strip() for value in values))

    @model_validator(mode="after")
    def date_order(self):
        for start, end in [(self.published_start, self.published_end),
                           (self.event_start, self.event_end)]:
            if start and end and start > end:
                raise ValueError("검색 시작일이 종료일보다 늦습니다.")
        return self


class RagEvidence(RagDocument):
    """문서 정보와 정확한 청크 인용. text는 저장 문서 본문으로 인용 위치 검증에 사용한다."""

    chunk_id: str
    event_id: str
    paragraph_id: str | None
    quote: str
    start_char: int
    end_char: int
    content_hash: str
    retrieval_score: float
    matched_query: str
    raw_quote_verified: bool


class RagResult(Schema):
    event_id: str
    question: str
    status: Literal["evidence_found", "empty_event", "no_eligible_documents", "no_match"]
    retrieval_method: str = "lexical_bm25_v1"
    total_documents: int
    eligible_documents: int
    excluded: dict[str, int]
    duplicates_suppressed: int = 0
    evidence: list[RagEvidence]
    warnings: list[str]
