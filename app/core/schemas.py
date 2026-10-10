"""API·LLM·저장소가 공유하는 자료형. 필드명과 상태 코드는 외부 계약이므로 유지한다."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["ko", "zh", "ja", "en"]
Confidence = Literal["medium", "low", "unassessed", "high"]
StepStatus = Literal["pending", "running", "done", "partial", "failed"]
FindingStatus = Literal["aligned", "conflict", "insufficient", "not_comparable", "revision_review"]
MAX_CLAIMS_PER_SOURCE = 6


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RunRequest(Schema):
    question: str = Field(min_length=8, max_length=1200)
    mode: Literal["demo", "live"] = "demo"
    languages: list[Language] = Field(default=["ko", "zh", "ja"], min_length=1, max_length=4)


class SearchQuery(Schema):
    language: Language
    query: str = Field(min_length=2, max_length=300)


class Target(Schema):
    id: str
    label: str
    subject: str


class SearchPlan(Schema):
    event: str
    event_date: str | None
    queries: list[SearchQuery]
    targets: list[Target]


class ClaimDraft(Schema):
    """LLM이 추출한 미검증 주장. 원문 인용 검사를 통과해야 Claim이 된다."""

    target_id: str
    matches_event: bool
    event_date: str | None
    subject: str
    value: str
    value_number: float | None
    unit: str | None
    time_local: str | None
    timezone: Literal["UTC", "KST", "JST", "Asia/Shanghai"] | None
    certainty: Literal["reported", "estimated", "possible", "planned", "unconfirmed"]
    quantifier: Literal["exact", "approx", "at_least", "at_most"]
    polarity: Literal["positive", "negative", "unknown"]
    attribution: str
    paragraph_id: str
    quote: str = Field(min_length=2, max_length=1200)
    translation: str
    revision_note: str | None


class Extraction(Schema):
    language: Language
    claims: list[ClaimDraft]


class Paragraph(Schema):
    id: str
    text: str


class Source(Schema):
    id: str
    title: str
    url: str | None
    publisher_group: str
    language: str = "unknown"
    collected_at: str
    published_at: str | None = None
    content_hash: str
    paragraphs: list[Paragraph]
    truncated: bool = False
    is_demo: bool = False


class Claim(ClaimDraft):
    """인용 구절이 확인된 주장. 인용의 존재가 주장 내용의 진위를 보증하지는 않는다."""

    id: str
    source_id: str
    normalized: str | None
    normalization_note: str


class Finding(Schema):
    id: str
    target_id: str
    label: str
    subject: str
    status: FindingStatus
    confidence: Confidence
    reason: str
    claim_ids: list[str]
    publisher_groups: int
    review_note: str = ""


class Step(Schema):
    name: str
    status: StepStatus = "pending"
    detail: str = ""


class AuditEntry(Schema):
    at: str
    reviewer: str
    action: str
    note: str
    version: int


class Report(Schema):
    """분석 결과와 진행·검토 이력. 저장소는 이 객체를 JSON으로 보관한다."""

    id: str
    question: str
    mode: Literal["demo", "live"]
    languages: list[Language] = Field(default_factory=lambda: ["ko", "zh", "ja"])
    status: Literal["running", "draft", "failed", "approved", "held"] = "running"
    version: int = 1
    created_at: str
    plan: SearchPlan | None = None
    sources: list[Source] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    audit: list[AuditEntry] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0

    def mark_failed(self, reason: str) -> None:
        """중단 사유를 남기되 이미 완료한 단계와 확보한 근거는 보존한다."""
        self.status = "failed"
        self.warnings.append(reason)
        for step in self.steps:
            if step.status == "running":
                step.status = "failed"


class ReviewRequest(Schema):
    expected_version: int = Field(ge=1)
    reviewer: str = Field(min_length=1, max_length=60)
    action: Literal["approve", "hold", "reopen"]
    note: str = Field(min_length=3, max_length=1000)


class FindingEdit(Schema):
    expected_version: int = Field(ge=1)
    reviewer: str = Field(min_length=1, max_length=60)
    confidence: Confidence
    note: str = Field(min_length=3, max_length=1000)
