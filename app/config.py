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
    database: Path = field(default_factory=lambda:
        Path(os.getenv('SKYTRACE_DATA_DIR', str(ROOT / 'data'))) / 'skytrace.sqlite3')
    deployment: bool = field(default_factory=lambda:
        os.getenv('SKYTRACE_DEPLOYMENT', '0').lower() in {'1', 'true', 'yes'})
    allowed_hosts: tuple[str, ...] = field(default_factory=lambda: tuple(
        value.strip() for value in os.getenv(
            'SKYTRACE_ALLOWED_HOSTS', '127.0.0.1,localhost,testserver').split(',') if value.strip()))
    public_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        value.strip().rstrip('/') for value in os.getenv(
            'SKYTRACE_PUBLIC_ORIGINS', '').split(',') if value.strip()))
    access_user: str = field(default_factory=lambda: os.getenv('SKYTRACE_ACCESS_USER', ''), repr=False)
    access_password: str = field(default_factory=lambda: os.getenv('SKYTRACE_ACCESS_PASSWORD', ''), repr=False)
    ollama_model: str = field(default_factory=lambda: os.getenv('OLLAMA_MODEL', 'gemma4:e2b'))
    ollama_embedding_model: str = field(
        default_factory=lambda: os.getenv('OLLAMA_EMBEDDING_MODEL', 'bge-m3'))
    ollama_force_cpu: bool = field(default_factory=lambda:
        os.getenv('OLLAMA_FORCE_CPU', '0').strip().lower() in {'1', 'true', 'yes', 'on'})
    ollama_url: str = field(default_factory=lambda: os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434'))
    ollama_timeout: float = field(default_factory=lambda: float(os.getenv('OLLAMA_TIMEOUT', '300')))
    reliability_function: str = field(default_factory=lambda:
        os.getenv('SKYTRACE_RELIABILITY_FUNCTION', 'analysis.reliability:run'))
    reliability_input_mode: str = field(default_factory=lambda: os.getenv('SKYTRACE_RELIABILITY_INPUT_MODE', 'dict'))
    reliability_timeout: float = field(default_factory=lambda: float(os.getenv('SKYTRACE_RELIABILITY_TIMEOUT', '30')))

    def __post_init__(self) -> None:
        if not self.allowed_hosts or any('*' in host or '/' in host for host in self.allowed_hosts):
            raise ValueError('SKYTRACE_ALLOWED_HOSTS에 정확한 호스트 이름을 지정하세요.')
        for origin in self.public_origins:
            parsed = urlsplit(origin)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or '*' in parsed.netloc):
                raise ValueError('SKYTRACE_PUBLIC_ORIGINS에는 정확한 HTTPS 출처를 지정하세요.')
        if bool(self.access_user) != bool(self.access_password) or ':' in self.access_user:
            raise ValueError('접속 계정과 비밀번호를 모두 설정하고 계정에 콜론을 넣지 마세요.')
        if self.deployment and (not self.access_user or len(self.access_password) < 16):
            raise ValueError('배포 모드에는 접속 계정과 16자 이상의 비밀번호가 필요합니다.')
        if self.deployment and not self.public_origins:
            raise ValueError('배포 모드에는 SKYTRACE_PUBLIC_ORIGINS 설정이 필요합니다.')
        url = urlsplit(self.ollama_url)
        if (url.scheme != 'http' or url.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or url.username or url.password or url.path not in {'', '/'} or url.query or url.fragment):
            raise ValueError('OLLAMA_BASE_URL은 HTTP 로컬 루프백 주소여야 합니다.')
        if not 0 < self.ollama_timeout <= 1800:
            raise ValueError('OLLAMA_TIMEOUT은 0~1800초 사이여야 합니다.')
        if self.reliability_input_mode not in {'dict', 'path'} or not 0 < self.reliability_timeout <= 180:
            raise ValueError('신뢰도 함수 입력 모드는 dict/path, 제한 시간은 0~180초로 설정하세요.')
        if not self.ollama_model.strip() or self.ollama_model.endswith((':cloud', '-cloud')):
            raise ValueError('다운로드된 로컬 모델 이름을 지정하세요.')
        if (not self.ollama_embedding_model.strip()
            or self.ollama_embedding_model.endswith((':cloud', '-cloud'))):
            raise ValueError('다운로드된 로컬 임베딩 모델 이름을 지정하세요.')

    @property
    def live_ready(self) -> bool:
        return bool(self.openai_key and self.tavily_key)
