"""로컬 실행 설정. API 키는 객체 출력과 API 응답에 포함하지 않는다."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    """환경변수를 읽는 실행 설정. 테스트에서는 생성자 인자로 값을 주입한다."""

    openai_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""), repr=False)
    tavily_key: str = field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""), repr=False)
    model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    max_documents: int = field(
        default_factory=lambda: max(1, min(8, int(os.getenv("SKYTRACE_MAX_DOCUMENTS", "6"))))
    )
    max_document_chars: int = field(
        default_factory=lambda: max(
            2000, min(16000, int(os.getenv("SKYTRACE_MAX_DOCUMENT_CHARS", "10000")))
        )
    )
    allowed_domains: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            domain.strip().lower()
            for domain in os.getenv(
                "SKYTRACE_ALLOWED_DOMAINS",
                "mod.go.jp,mofa.go.kr,mnd.go.kr,jcs.mil.kr,fmprc.gov.cn,"
                "motc.gov.tw,caa.gov.tw,jaxa.jp,reuters.com,apnews.com,news.cn",
            ).split(",")
            if domain.strip()
        )
    )
    database: Path = field(default_factory=lambda: ROOT / "data" / "skytrace.sqlite3")

    @property
    def live_ready(self) -> bool:
        return bool(self.openai_key and self.tavily_key)
