"""로컬 실행 설정. API 키는 객체 출력과 API 응답에 포함하지 않는다."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

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
    ollama_model: str = field(default_factory=lambda: os.getenv('OLLAMA_MODEL', 'gemma4:e2b'))
    ollama_url: str = field(default_factory=lambda: os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434'))
    ollama_timeout: float = field(default_factory=lambda: float(os.getenv('OLLAMA_TIMEOUT', '300')))

    def __post_init__(self) -> None:
        url = urlsplit(self.ollama_url)
        if (url.scheme != 'http' or url.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or url.username or url.password or url.path not in {'', '/'} or url.query or url.fragment):
            raise ValueError('OLLAMA_BASE_URL은 HTTP 로컬 루프백 주소여야 합니다.')
        if not 0 < self.ollama_timeout <= 1800:
            raise ValueError('OLLAMA_TIMEOUT은 0~1800초 사이여야 합니다.')
        if not self.ollama_model.strip() or self.ollama_model.endswith((':cloud', '-cloud')):
            raise ValueError('다운로드된 로컬 모델 이름을 지정하세요.')

    @property
    def live_ready(self) -> bool:
        return bool(self.openai_key and self.tavily_key)
