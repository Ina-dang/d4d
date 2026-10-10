"""
OSINT 수집 파이프라인 데이터 규격 (Schemas)
팀원(나현님, 신엽님)과의 데이터 교환 및 검증을 위한 표준 규격 정의
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class CleaningMeta(BaseModel):
    """기사 본문 정제 메타데이터 (나현님 제안 규격)"""
    removed_blocks: List[str] = Field(default_factory=list, description="제거된 블록 유형 (구독 안내, 내비게이션 메뉴 등)")
    needs_review: bool = Field(default=False, description="본문 경계 애매 또는 구독 제한으로 수동 검토 필요 여부")


class ParagraphData(BaseModel):
    """개별 문단 데이터 - LLM의 핀포인트 인용(Citation) 단위"""
    paragraph_id: str = Field(description="문서ID_문단번호 (예: doc_1a2b3c_p1)")
    raw_text: str = Field(description="문단 원문 텍스트")
    id: Optional[str] = Field(default=None, description="문단 ID (나현님 파이프라인 호환용)")
    text: Optional[str] = Field(default=None, description="문단 텍스트 (나현님 파이프라인 호환용)")


class DocumentData(BaseModel):
    """수집된 단일 OSINT 문서 데이터 규격"""
    doc_id: str = Field(description="문서 고유 식별자 (예: doc_1a2b3c)")
    url: str = Field(description="출처 원문 URL")
    title: str = Field(description="기사/문서 제목")

    # 🎯 검색 관련도 점수 (Tavily score 파라미터)
    score: float = Field(default=0.0, description="Tavily 검색어 관련도 점수 (0.0 ~ 1.0)")

    # 🌐 언어 식별
    language: str = Field(default="unknown", description="본문 판별 언어: ko, zh, zh-Hant, ja, en, hi, ur 등")
    language_detection: dict = Field(default_factory=dict, description="본문 언어 판별 방법·신뢰도")
    body_acquisition: dict = Field(default_factory=dict, description="Tavily Search/Extract 본문 확보 경로")
    relevance: dict = Field(default_factory=dict, description="본문의 주제 일치 근거")

    # 🎯 티어 및 출처 평가 메타데이터
    tier: int = Field(description="출처 등급: 1(당사국 공식), 2(제3국 중립 관측), 3(검증 언론)")
    source_name: str = Field(description="기관/언론사 명칭 (예: Taiwan MND, Japan MoD)")
    country: str = Field(description="출처 국가/진영 코드 (TW, CN, JP, SG, PH 등)")
    source_category: str = Field(description="출처 유형 (party_official, neutral_observer, reputable_media)")
    credibility_weight: float = Field(description="기본 신뢰도 가중치 (0.0 ~ 1.0)")

    # 🔄 순환 보고(Circular Reporting / 재인용) 방어 메타데이터
    is_reprint_likely: bool = Field(default=False, description="다른 매체를 재인용한 기사일 가능성 여부")
    quoted_source: Optional[str] = Field(default=None, description="본문에서 감지된 원래 발언 주체/인용 매체 (예: Reuters, Taiwan MND)")

    # 🔍 검색 쿼리
    query: str = Field(default="", description="문서 검색에 사용된 검색어")

    # ⏱️ 시간 및 수집 상태
    published_date: Optional[str] = Field(default=None, description="확인된 기사/공문서 발행일시")
    event_date: Optional[str] = Field(default=None, description="사건 발생일 (수집단에서는 절대 임의로 채우지 않고 None 유지)")
    status: str = Field(description="수집 및 절단 상태: success_full 또는 success_truncated")

    # 📦 원본 보존 및 정제 텍스트 (나현님 Ollama 대조용 규격)
    raw_content: str = Field(default="", description="Tavily 수집 원본 (대조 및 원문 검증용)")
    article_text: str = Field(default="", description="광고·구독·메뉴가 제거된 순수 기사 본문 텍스트")
    cleaning: CleaningMeta = Field(default_factory=CleaningMeta, description="정제 작업 메타데이터")

    # 📑 문단 목록 (Ollama 입력용)
    paragraphs: List[ParagraphData] = Field(default_factory=list, description="분할된 문단 목록")


class SearchQueryItem(BaseModel):
    """나현님이 보내주는 개별 언어별 쿼리 항목"""
    language: str
    query: str
    search_query: Optional[str] = None


class SearchPlanRequest(BaseModel):
    """나현님/신엽님이 수집기로 보내는 요청 포맷"""
    event: str
    event_date: Optional[str] = None
    queries: List[SearchQueryItem]
    selected_languages: Optional[List[str]] = None
    relevance_context: Optional[dict] = None


class OSINTCollectionResponse(BaseModel):
    """수집기가 최종 반환하는 7개국 그룹화 응답 규격"""
    event: str
    event_date: Optional[str] = None
    by_country: dict = Field(description="국가별(CN, TW, JP, KR, IN, PK, US) 그룹화된 문서 목록")
    total_count: int = Field(description="전체 수집 문서 수")
    all_documents: List[DocumentData] = Field(description="전체 수집 문서 리스트")

