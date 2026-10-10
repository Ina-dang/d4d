"""
OSINT 수집 파이프라인 데이터 규격 (Schemas)
팀원(나현님, 신엽님)과의 데이터 교환 및 검증을 위한 표준 규격 정의
(수집_데이터_변경_요청.md 요구사항 반영: raw_content 및 paragraphs 제거, cleaning 제거 및 score_notice 1-depth 승격, text_snippet 탑재)
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class CleaningMeta(BaseModel):
    """기사 본문 정제 메타데이터 (하위 호환 유지용)"""
    removed_blocks: List[str] = Field(default_factory=list, description="제거된 블록 유형")
    needs_review: bool = Field(default=False, description="수동 검토 필요 여부")
    score_notice: Optional[str] = Field(default=None, description="점수 보충 선별 안내")


class ParagraphData(BaseModel):
    """개별 문단 데이터 (후속 처리 단계에서 임시 생성 시 사용)"""
    id: str = Field(description="문단 ID (예: doc_1a2b3c_p1)")
    text: str = Field(description="문단 텍스트")


class DocSnippetItem(BaseModel):
    """유사도 계산용 경량 발췌 문서 규격 (docs[])"""
    doc_id: str = Field(description="문서 고유 식별자")
    title: str = Field(description="기사/문서 제목")
    url: str = Field(description="출처 원문 URL")
    score: float = Field(default=0.0, description="Tavily 관련도 점수")
    score_notice: Optional[str] = Field(default=None, description="점수 보충 선별 안내 (1-depth)")
    language: str = Field(default="unknown", description="문서 언어 코드")
    tier: int = Field(description="출처 등급 (1, 2, 3)")
    source_name: str = Field(description="기관/언론사 명칭")
    country: str = Field(description="국가/진영 코드")
    published_date: Optional[str] = Field(default=None, description="발행일자 (YYYY-MM-DD)")
    text_snippet: str = Field(default="", description="정리된 본문의 첫 5문장 발췌문")


class RawDocItem(BaseModel):
    """상세 본문 확인용 원본 문서 규격 (raw_docs[])"""
    doc_id: str = Field(description="문서 고유 식별자")
    title: str = Field(description="기사/문서 제목")
    url: str = Field(description="출처 원문 URL")
    score: float = Field(default=0.0, description="Tavily 관련도 점수")
    score_notice: Optional[str] = Field(default=None, description="점수 보충 선별 안내 (1-depth)")
    language: str = Field(default="unknown", description="문서 언어 코드")
    tier: int = Field(description="출처 등급 (1, 2, 3)")
    source_name: str = Field(description="기관/언론사 명칭")
    country: str = Field(description="국가/진영 코드")
    source_category: str = Field(default="reputable_media", description="출처 유형")
    credibility_weight: float = Field(default=0.75, description="기본 신뢰도 가중치")
    query: str = Field(default="", description="검색 쿼리")
    published_date: Optional[str] = Field(default=None, description="발행일자 (YYYY-MM-DD)")
    status: str = Field(default="success_full", description="수집 상태: success_full / success_truncated")
    article_text: str = Field(default="", description="광고·사이드바 등이 제거된 순수 기사 본문 텍스트")


class DocumentData(BaseModel):
    """수집된 단일 OSINT 통합 문서 규격"""
    doc_id: str = Field(description="문서 고유 식별자 (예: doc_1a2b3c)")
    url: str = Field(description="출처 원문 URL")
    title: str = Field(description="기사/문서 제목")

    # 🎯 검색 관련도 점수 및 1-depth 안내
    score: float = Field(default=0.0, description="Tavily 검색어 관련도 점수 (0.0 ~ 1.0)")
    score_notice: Optional[str] = Field(default=None, description="임계값 미만 보충 선별 안내 (1-depth)")

    # 🌐 언어 식별
    language: str = Field(default="unknown", description="문서 언어 코드: zh, ja, ko, en, unknown")

    # 🎯 티어 및 출처 평가 메타데이터
    tier: int = Field(description="출처 등급: 1(당사국 공식), 2(제3국 중립 관측), 3(검증 언론)")
    source_name: str = Field(description="기관/언론사 명칭")
    country: str = Field(description="출처 국가/진영 코드")
    source_category: str = Field(default="reputable_media", description="출처 유형")
    credibility_weight: float = Field(default=0.75, description="기본 신뢰도 가중치")

    # 🔍 검색 쿼리 및 날짜
    query: str = Field(default="", description="문서 검색에 사용된 검색어")
    published_date: Optional[str] = Field(default=None, description="확인된 기사/공문서 발행일시 (YYYY-MM-DD)")
    status: str = Field(default="success_full", description="수집 상태: success_full 또는 success_truncated")

    # 📄 발췌문 및 순수 본문
    text_snippet: str = Field(default="", description="정리된 본문의 첫 5문장 발췌문 (유사도 계산용)")
    article_text: str = Field(default="", description="순수 기사 본문 텍스트 (본문 확인용)")


class SearchQueryItem(BaseModel):
    """개별 언어별 쿼리 항목"""
    language: str
    query: str


class SearchPlanRequest(BaseModel):
    """요청 포맷"""
    event: str
    reference_date: Optional[str] = Field(default=None, description="사용자 지정 기준일 (YYYY-MM-DD)")
    event_date: Optional[str] = Field(default=None, description="하위 호환용 (사용자 지정 기준일은 reference_date 권장)")
    queries: List[SearchQueryItem]


class OSINTCollectionResponse(BaseModel):
    """수집기가 최종 반환하는 응답 규격"""
    korean_question: Optional[str] = None
    event: Optional[str] = None
    reference_date: Optional[str] = Field(default=None, description="사용자 지정 기준일 (YYYY-MM-DD)")
    event_date: Optional[str] = Field(default=None, description="하위 호환용 (사용자 지정 기준일은 reference_date 권장)")
    by_country: Dict[str, Any] = Field(description="국가별 그룹화된 문서 목록")
    total_count: int = Field(description="전체 수집 문서 수")
    docs: List[DocSnippetItem] = Field(default_factory=list, description="유사도 계산용 경량 발췌 문서 목록")
    raw_docs: List[RawDocItem] = Field(default_factory=list, description="본문 확인용 상세 문서 목록")
    all_documents: List[DocumentData] = Field(default_factory=list, description="전체 수집 문서 리스트")
