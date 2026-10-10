"""로컬 검색 계획 및 frame 수집 요청의 입력 계약."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Language = Literal['ko', 'zh', 'zh-Hant', 'ja', 'en', 'hi', 'ur']


class Schema(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class SearchQuery(Schema):
    language: Language
    query: str = Field(min_length=2, max_length=600)


class Target(Schema):
    id: str
    label: str
    subject: str


class SearchPlan(Schema):
    event: str
    event_date: str | None
    queries: list[SearchQuery]
    targets: list[Target]


class CollectionRequest(Schema):
    question: str = Field(min_length=8, max_length=1200)
    languages: list[Language] = Field(default_factory=lambda: ['ko', 'zh', 'zh-Hant', 'ja', 'en'],
                                      min_length=1, max_length=7)
    event_date: date | None = None
    days_back: int = Field(default=30, ge=1, le=30)
    max_docs_per_country: int = Field(default=20, ge=1, le=20)
    min_score: float = Field(default=0.7, ge=0, le=1)
    strict_min_score: bool = False

    @field_validator('question')
    @classmethod
    def trim_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 8:
            raise ValueError('질문은 공백을 제외하고 8자 이상 입력하세요.')
        return value

    @field_validator('languages')
    @classmethod
    def unique_languages(cls, value: list[Language]) -> list[Language]:
        if len(value) != len(set(value)):
            raise ValueError('검색 언어를 중복 없이 지정하세요.')
        return value
