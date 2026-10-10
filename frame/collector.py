# -*- coding: utf-8 -*-
"""
DefenseOSINTCollector (v2.3)
----------------------------
다국어 안보 정보 수집 및 다중 검증 파이프라인 수집 모듈.
- Tavily 검색 API 연동 (고급 다국어 심층 검색)
- 내장 .env 자동 로더 (TAVILY_API_KEY 자동 감지)
- 한국어 자연어 질문 1개 입력 시 7대 주요 안보 행위자(CN, TW, JP, KR, IN, PK, US) 1:1 자동 변환
- 화이트리스트 기반 자동 필터링 및 티어(Tier 1, 2, 3) 메타데이터 태깅
- 순환 보고(Circular Reporting / 인용) 자동 탐지
- 스마트 문단 분할 (단어 잘림 없는 문장 단위 청킹)
- 다중 중복 제거 (URL Canonicalization, Title 정규화, Content Fingerprint)
- 기사 본문 정제 (사이드바, 추천 기사, 댓글, 마크다운 이미지, 구독 배너 완전 절단)
- Tavily score 검색 관련도 메타데이터 및 min_score(기본 0.7) 필터링
- JSON 내보내기/불러오기 지원 (export_json, load_json)
"""

import os
import sys
import time
import uuid
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Union
from urllib.parse import urlparse, parse_qsl, urlencode

try:
    from .article_filters import detect_body_language, topic_evidence
except ImportError:
    from article_filters import detect_body_language, topic_evidence

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None

try:
    from .config import (
        OSINT_WHITELIST,
        COUNTRY_DOMAINS,
        DEFENSE_LEXICON,
        MAX_RAW_CHARS,
        MAX_PARAGRAPH_CHARS,
        MIN_PARAGRAPH_CHARS,
        DEFAULT_MIN_SCORE,
        LANGUAGE_SEARCH_DOMAINS,
        MIN_SCORE_FLOOR,
        DEFAULT_MAX_DOCS_PER_COUNTRY,
        MAX_GREATER_CHINA_TOTAL,
    )
except ImportError:
    from config import (
        OSINT_WHITELIST,
        COUNTRY_DOMAINS,
        DEFENSE_LEXICON,
        MAX_RAW_CHARS,
        MAX_PARAGRAPH_CHARS,
        MIN_PARAGRAPH_CHARS,
        DEFAULT_MIN_SCORE,
        LANGUAGE_SEARCH_DOMAINS,
        MIN_SCORE_FLOOR,
        DEFAULT_MAX_DOCS_PER_COUNTRY,
        MAX_GREATER_CHINA_TOTAL,
    )


def auto_load_dotenv(env_path: Optional[str] = None) -> None:
    """별도 패키지 설치 없이 .env 파일을 읽어 환경변수에 자동 등록하는 경량 로더"""
    paths_to_check = [
        Path(env_path) if env_path else None,
        Path.cwd() / ".env",
        Path(__file__).parent / ".env",
        Path(__file__).parent.parent / ".env",
    ]
    for p in paths_to_check:
        if p and p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip().strip("'\""))
                break
            except Exception:
                pass


auto_load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


class OSINTCollector:
    """7대 주요 안보 행위자 다국어 OSINT 정보 수집 및 신뢰도 검증 수집기"""

    def __init__(self, api_key: Optional[str] = None, raise_on_error: bool = False):
        self.raise_on_error = raise_on_error
        key = api_key or os.getenv("TAVILY_API_KEY")
        if not key:
            print(
                "[!] 경고: TAVILY_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요."
            )
            self.client = None
        elif TavilyClient is None:
            print(
                "[!] 경고: tavily-python 패키지가 설치되지 않았습니다. (pip install tavily-python)"
            )
            self.client = None
        else:
            self.client = TavilyClient(api_key=key)

        self.allowed_domains = list(OSINT_WHITELIST.keys())
        self.filter_rejections = []
        self.body_recovery = {'attempted': 0, 'recovered': 0, 'failed': 0}
        self._body_cache = {}
        self.search_attempts = []

    def _recover_search_bodies(self, items: List[Dict], context: Optional[Dict]) -> List[Dict]:
        """One bounded extraction batch for missing, potentially relevant bodies."""
        items = [dict(item) for item in items]
        pending = {}
        for item in items:
            if (item.get('raw_content') or '').strip() or not self._is_article_url(item.get('url', '')):
                continue
            url = item['url']
            canonical = self._canonicalize_url(url)
            if canonical in self._body_cache:
                continue
            if context:
                reason, _ = topic_evidence(item.get('title', '') + '\n' + (item.get('content') or ''),
                                          {**context, 'security_topic': False})
                if reason:
                    continue
            if len(pending) < 8:
                pending[canonical] = url
        if pending:
            self.body_recovery['attempted'] += len(pending)
            self._body_cache.update(dict.fromkeys(pending))
            try:
                response = self.client.extract(urls=list(pending.values()), extract_depth='advanced',
                                               format='text', timeout=15)
                for entry in response.get('results', []):
                    canonical = self._canonicalize_url(entry.get('url', ''))
                    body = entry.get('raw_content') or ''
                    if canonical in pending and body.strip():
                        self._body_cache[canonical] = body
            except Exception:
                # A blocked article must not fail the whole collection or expose provider details.
                pass
            recovered = sum(bool(self._body_cache[key]) for key in pending)
            self.body_recovery['recovered'] += recovered
            self.body_recovery['failed'] += len(pending) - recovered
        for item in items:
            body = self._body_cache.get(self._canonicalize_url(item.get('url', '')))
            if not (item.get('raw_content') or '').strip() and body:
                item.update(raw_content=body, _body_method='tavily_extract')
        return items

    @staticmethod
    def _canonicalize_url(url: str) -> str:
        """URL 정규화: 슬러그/추적 파라미터 차이를 통합하여 동일 기사 중복 방지"""
        if not url:
            return ""
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parsed.path.rstrip("/")
        # 뉴스 기사 id 슬러그 패턴 정규화 (예: /news/12345/slug -> /news/12345)
        path = re.sub(
            r"/(news|article|articles|story)/(\d+)(/[^/]+)?$", r"/\1/\2", path
        )
        query_pairs = parse_qsl(parsed.query)
        clean_pairs = [
            (k, v)
            for k, v in query_pairs
            if not k.lower().startswith(
                ("utm_", "fbclid", "ref", "source", "spm", "from", "ncid")
            )
        ]
        query = urlencode(clean_pairs)
        return f"{netloc}{path}" + (f"?{query}" if query else "")

    @staticmethod
    def _canonicalize_title(title: str) -> str:
        """기사 제목 정규화: 언론사명 접미사/특수문자/공백을 정규화하여 중복 감지"""
        if not title:
            return ""
        t = title.lower()
        t = re.sub(
            r"\s*[-|–—]\s*(dawn\.com|newspaper|reuters|bbc|cnn|nhk|asahi|yomiuri|nikkei|kyodo|연합뉴스|동아일보|조선일보|중앙일보|cctv|global times).*$",
            "",
            t,
        )
        t = re.sub(r"[^\w\s\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", "", t)
        return " ".join(t.split())

    @staticmethod
    def _content_fingerprint(text: str) -> str:
        """Compare normalized complete bodies; site headers cannot collapse different articles."""
        clean = re.sub(
            r"[^\w\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", "", text.lower()
        )
        return hashlib.sha256(clean.encode('utf-8')).hexdigest() if clean else ''

    def _resolve_tier_meta(self, url: str) -> Dict:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()

        for domain, meta in OSINT_WHITELIST.items():
            if hostname == domain or hostname.endswith("." + domain):
                return meta

        return {
            "tier": 3,
            "name": hostname or "미분류 출처",
            "country": "UNKNOWN",
            "category": "commercial_media",
            "weight": 0.50,
        }

    def _detect_language(self, url: str, text: str) -> str:
        return detect_body_language(text)['language']

    def _reject_article(self, item: dict, reason: str, detection: dict | None = None):
        self.filter_rejections.append({'url': item.get('url', ''),
                                       'title': item.get('title', ''), 'reason': reason,
                                       'language_detection': detection})

    def _extract_attribution_hint(self, text: str) -> Optional[str]:
        sample = text[:1000]
        attribution_patterns = [
            r"(?:according to|reported by|citing|cited by)\s+([A-Z][a-zA-Z\s]{2,25})",
            r"(?:인용한|보도한 바에 따르면|에 따르면|발표에 따르면)\s*([가-힣A-Za-z]{2,15})",
            r"(?:据|援引|转引自)\s*([A-Za-z\u4e00-\u9fff]{2,15})\s*(?:报道|消息|称)",
            r"(?:によると|によれば|が報じたところによれば)\s*([A-Za-z\u4e00-\u9fff\u3040-\u30ff]{2,15})",
        ]
        for pattern in attribution_patterns:
            match = re.search(pattern, sample)
            if match:
                hint = match.group(1).strip()
                if 2 <= len(hint) <= 40:
                    return hint
        return None

    def _split_into_paragraphs(self, text: str) -> List[str]:
        """단어 잘림 없는 스마트 문단 청킹 (문장 종결자 및 공백 기준 분할)"""
        raw_blocks = [b.strip() for b in re.split(r"\n\s*\n|\n", text) if b.strip()]
        paragraphs = []

        for block in raw_blocks:
            if (
                re.match(r"^!\[.*?\]\(.*?\)$", block)
                or re.match(r"^\s*(\*|\-)?\s*\*{0,2}\[.*?\]\(.*?\)\*{0,2}\s*$", block)
                or re.match(r"^#{1,6}\s+", block)
            ):
                continue

            if len(block) <= MAX_PARAGRAPH_CHARS:
                if len(block) >= MIN_PARAGRAPH_CHARS:
                    paragraphs.append(block)
                continue

            # 400자 초과 시 문장 단위로 분할
            sentences = re.split(r"(?<=[.!?。！？])\s+", block)
            curr = ""
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                if not curr:
                    curr = s
                elif len(curr) + 1 + len(s) <= MAX_PARAGRAPH_CHARS:
                    curr = f"{curr} {s}"
                else:
                    if len(curr) >= MIN_PARAGRAPH_CHARS:
                        paragraphs.append(curr)
                    if len(s) > MAX_PARAGRAPH_CHARS:
                        words = s.split()
                        sub_curr = ""
                        for w in words:
                            if not sub_curr:
                                sub_curr = w
                            elif len(sub_curr) + 1 + len(w) <= MAX_PARAGRAPH_CHARS:
                                sub_curr = f"{sub_curr} {w}"
                            else:
                                if len(sub_curr) >= MIN_PARAGRAPH_CHARS:
                                    paragraphs.append(sub_curr)
                                sub_curr = w
                        curr = sub_curr
                    else:
                        curr = s

            if curr and len(curr) >= MIN_PARAGRAPH_CHARS:
                paragraphs.append(curr)

        return paragraphs

    def _extract_published_date(self, url: str, text: str, api_date: Optional[str] = None) -> Optional[str]:
        """Tavily API, URL 패턴, 본문 앞부분을 대조하여 정확한 발행일자(YYYY-MM-DD)를 3단계로 추출"""
        if api_date and re.match(r'^\d{4}-\d{2}-\d{2}', str(api_date)):
            return str(api_date)[:10]

        # 1. URL 패턴에서 추출 (/2026/09/25/, /AKR20260930181100089, -2026-09-21)
        m_url = re.search(r'/(20\d{2})[-/](\d{2})[-/](\d{2})', url)
        if m_url:
            return f"{m_url.group(1)}-{m_url.group(2)}-{m_url.group(3)}"

        m_url_compact = re.search(r'(?:AKR|/|_)(20\d{2})(\d{2})(\d{2})\d{4,}', url)
        if m_url_compact:
            return f"{m_url_compact.group(1)}-{m_url_compact.group(2)}-{m_url_compact.group(3)}"

        m_url_hyphen = re.search(r'-(20\d{2})-(\d{2})-(\d{2})\b', url)
        if m_url_hyphen:
            return f"{m_url_hyphen.group(1)}-{m_url_hyphen.group(2)}-{m_url_hyphen.group(3)}"

        # 2. 본문 앞 400자에서 추출
        sample = text[:400]
        m_ko = re.search(r'(?:송고|수정|입력|발행)?\s*(20\d{2})[-년\.]\s*(\d{1,2})[-월\.]\s*(\d{1,2})', sample)
        if m_ko:
            y, m, d = m_ko.group(1), m_ko.group(2).zfill(2), m_ko.group(3).zfill(2)
            return f"{y}-{m}-{d}"

        m_en = re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(20\d{2})', sample, re.I)
        if m_en:
            months = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
                      "jul": "07", "aug": "08", "sep": "09", "sept": "09", "oct": "10", "nov": "11", "dec": "12"}
            mon_str = m_en.group(1).lower()
            mon = months.get(mon_str, "01")
            day = m_en.group(2).zfill(2)
            year = m_en.group(3)
            return f"{year}-{mon}-{day}"

        m_zh = re.search(r'(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日', sample)
        if m_zh:
            return f"{m_zh.group(1)}-{m_zh.group(2).zfill(2)}-{m_zh.group(3).zfill(2)}"

        return None

    def _build_clean_5_sentence_snippet(self, article_text: str, title: str = "") -> str:
        """
        [수집_데이터_변경_요청.md 기준 구현]
        1. 본문 외 요소(제목 중복, 송고 시각, 바이라인, 사진 설명, 제보/이메일, 광고/안내, 소제목) 제거
        2. 마크다운 서식 및 링크 주소 제거 (링크 표시 문구는 보존)
        3. 한/중/영 다국어 문장 경계 기준 첫 5문장 연결 (문장 중간 자름 없음, 400자 제한 없음)
        """
        if not article_text or not article_text.strip():
            return ""

        raw_lines = article_text.splitlines()
        clean_lines = []

        norm_title = re.sub(r'[^\w\u4e00-\u9fff\uac00-\ud7af]', '', title.lower())

        for line in raw_lines:
            line_str = line.strip()
            if not line_str:
                continue

            # 0. 마크다운 링크 서식 정제: [표시문구](URL) -> 표시문구만 추출
            proc = re.sub(r'\[([^\]]+)\]\(https?://[^\)]+\)', r'\1', line_str)
            proc = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', proc)
            # 마크다운 헤더 기호(#), 볼드/이탤릭(*, _), 인라인코드(`) 제거
            is_heading = proc.startswith("#")
            proc = re.sub(r'^#+\s*', '', proc)
            proc = re.sub(r'[*_`~]', '', proc).strip()

            if not proc:
                continue

            # 1. 제목 중복 제거
            norm_line = re.sub(r'[^\w\u4e00-\u9fff\uac00-\ud7af]', '', proc.lower())
            if norm_title and len(norm_line) > 5 and norm_line == norm_title:
                continue
            if is_heading and norm_title and norm_title in norm_line:
                continue
            if re.match(r'^(title|headline|제목)\s*:\s*', proc, re.I):
                continue

            # 2. 송고·수정 시각만 있는 줄 제거
            if re.match(r'^(송고|수정|등록|발행|입력|updated|published)\s*[:\d\-\s\./년월일시분초]+$', proc, re.I):
                continue
            if re.match(r'^(송고|수정)\s*\d{4}[-년\.]\s*\d{1,2}[-월\.]\s*\d{1,2}[-일\.]?\s*\d{1,2}시?\d{1,2}분?(\d{1,2}초)?$', proc, re.I):
                continue

            # 3. 기자명·바이라인만 있는 줄 제거
            if re.match(r'^\s*(\*|\-)?\s*([가-힣A-Za-z\s]{2,15})(기자|특파원|기고자|선임기자)\s*$', proc):
                continue
            if re.match(r'^\s*(by|written by|author:?)\s+[A-Za-z\s]{2,30}$', proc, re.I):
                continue
            if re.match(r'^\s*撰文[：:]\s*[\u4e00-\u9fff\s]{2,10}\s*$', proc):
                continue
            if re.match(r'^\s*(出版|更新)[：:]\s*.*$', proc):
                continue

            # 4. 언론사 포털/앱 UI 및 AI 요약 안내문 제거 (연합뉴스 등)
            if any(kw in proc for kw in [
                "인공지능이 자동으로 줄인", "세 줄 요약 기술을 사용합니다",
                "기사 본문과 함께 읽어야 합니다", "연합뉴스 기사를 우선적으로 보여줍니다",
                "재판매 및 DB 금지", "기자 프로필", "구독하기", "포토 슬라이드",
                "listen to article", "join our whatsapp channel", "all rights reserved"
            ]):
                continue

            # 5. 사진 설명, 캡션 및 사진 출처 제거
            if re.match(r'^\s*(\[자료사진\]|\[사진\s*출처.*?\]|▲\s*.*?|▼\s*.*?|photo\s*:.*?|사진\s*=.*?)\s*$', proc, re.I):
                continue
            if re.match(r'^\s*이미지\s*확대\s*.*$', proc):
                continue
            if re.match(r'^\s*(\[.*?\]|\(.*?\))\s*$', proc) and any(w in proc for w in ["사진", "연합뉴스", "로이터", "EPA", "AFP", "자료사진", "Graphic", "그래픽"]):
                continue

            # 6. 이메일 및 제보 안내 제거
            if re.search(r'(제보는\s*카카오톡|okjebo|\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b)', proc):
                continue

            # 7. 광고·추천 기사·메뉴·검색 안내 제거
            if re.match(r'^\s*(세\s*줄\s*요약|search|cancel|email|listen to article|join our whatsapp)\s*$', proc, re.I):
                continue

            # 8. 단독 소제목 라인 제거 (마침표 없이 끝나는 30자 미만의 헤더성 짧은 줄)
            if is_heading and len(proc) < 30 and not re.search(r'[.!?。！？]$', proc):
                continue

            clean_lines.append(proc)

        unified_text = " ".join(clean_lines)

        # 약어 및 소수점의 마침표 임시 치환 (___DOT___)
        DOT_TOKEN = "___DOT___"
        unified_text = re.sub(r'(\d+)\.(\d+)', r'\g<1>' + DOT_TOKEN + r'\g<2>', unified_text)
        unified_text = re.sub(
            r'(?i)\b(u\.s|mr|mrs|ms|dr|prof|inc|corp|ltd|co|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|vs|etc|no)\.',
            r'\g<1>' + DOT_TOKEN,
            unified_text
        )

        # 다국어 문장 경계 종결자: . ! ? 。 ！？ (공백 유무와 무관하게 분리)
        raw_sentences = re.split(r'(?<=[.!?。！？])\s*', unified_text)

        valid_sentences = []
        for s in raw_sentences:
            s_restored = s.replace(DOT_TOKEN, ".").strip()
            # 노이즈 문장 거르기
            if len(s_restored) < 6 and not re.search(r'[\u4e00-\u9fff]', s_restored):
                continue
            if len(s_restored) < 4:
                continue
            # 안내문 찌꺼기 문장 배제
            if any(kw in s_restored for kw in ["세 줄 요약", "기사 본문과 함께 읽어야", "구글 검색에서"]):
                continue
            valid_sentences.append(s_restored)

        if not valid_sentences:
            return ""

        # 첫 5문장을 원문 순서대로 공백으로 연결! (400자 제한 없음, 문장 중간 자름 없음)
        first_5 = valid_sentences[:5]
        return " ".join(first_5)

    def _is_article_url(self, url: str) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        path = parsed.path.lower().rstrip("/")
        query = parsed.query.lower()

        if not path or path in (
            "",
            "/index.html",
            "/index.htm",
            "/home",
            "/default.aspx",
            "/index",
        ):
            return False

        blacklist_patterns = [
            r"/index(_\d+)?\.(html?|php|jsp|aspx?)$",
            r"pageindex=\d+",
            r"/overview(\.html?|\.aspx?)?$",
            r"/sitemap",
            r"/wzdt_",
            r"sakuin\.pdf$",
            r"/category/",
            r"/channel/",
            r"/tag/",
            r"/topic/",
        ]
        for pat in blacklist_patterns:
            if re.search(pat, path) or re.search(pat, query):
                return False

        return True

    def _clean_content(self, text: str) -> tuple:
        if not text or not text.strip():
            return "", []

        cleaned = text
        removed_blocks = []

        if "### Transcript" in cleaned:
            cleaned = cleaned.split("### Transcript")[-1]
            removed_blocks.append("유튜브 메타데이터(설명란 등) 배제 및 자막 우선 추출")

        if (
            "<html" in cleaned.lower()
            or "<body" in cleaned.lower()
            or "<div" in cleaned.lower()
            or "<p" in cleaned.lower()
        ):
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(cleaned, "html.parser")

                has_boilerplate_tags = bool(
                    soup.find_all(
                        ["script", "style", "nav", "header", "footer", "aside"]
                    )
                )
                for tag in soup(
                    [
                        "script",
                        "style",
                        "nav",
                        "header",
                        "footer",
                        "aside",
                        "noscript",
                        "iframe",
                        "svg",
                    ]
                ):
                    tag.decompose()
                if has_boilerplate_tags:
                    removed_blocks.append("내비게이션/헤더/푸터 태그")

                has_img = bool(soup.find_all(["img", "picture", "figure"]))
                for tag in soup(["img", "picture", "figure"]):
                    tag.decompose()
                if has_img:
                    removed_blocks.append("광고/이미지 태그")

                best_tag = soup.body if soup.body else soup
                articles = soup.find_all("article")
                if articles:
                    best_tag = max(articles, key=lambda a: len(a.get_text(strip=True)))
                else:
                    mains = soup.find_all(["main", "div", "section"])
                    valid_mains = []
                    for m in mains:
                        cls = m.get("class", [])
                        if not isinstance(cls, list):
                            cls = [cls]
                        attrs = str(m.get("id", "")) + " " + " ".join(cls)
                        if any(
                            x in attrs.lower()
                            for x in [
                                "content",
                                "article",
                                "main",
                                "body",
                                "news",
                                "post",
                            ]
                        ):
                            valid_mains.append(m)
                    if valid_mains:
                        best_tag = max(
                            valid_mains, key=lambda m: len(m.get_text(strip=True))
                        )

                cleaned = best_tag.get_text(separator="\n")
            except Exception:
                pass

        cleaned = re.sub(
            r"<script.*?>.*?</script>", "", cleaned, flags=re.DOTALL | re.IGNORECASE
        )
        cleaned = re.sub(
            r"<style.*?>.*?</style>", "", cleaned, flags=re.DOTALL | re.IGNORECASE
        )
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)

        if re.search(r"!\[.*?\]\(.*?\)", cleaned):
            removed_blocks.append("마크다운 이미지 블록")
        cleaned = re.sub(r"\[!\[.*?\]\(.*?\)\]\(.*?\)", "", cleaned)
        cleaned = re.sub(r"!\[.*?\]\(.*?\)", "", cleaned)

        if re.search(r"^\s*[\*\+\-]\s*\[.*?\]\(.*?\)\s*$", cleaned, flags=re.MULTILINE):
            removed_blocks.append("메뉴/링크 목록")
        cleaned = re.sub(
            r"^\s*[\*\+\-]\s*\[.*?\]\(.*?\)\s*$", "", cleaned, flags=re.MULTILINE
        )
        cleaned = re.sub(r"\[.*?\]\(#[^\)]*\)", "", cleaned)

        footer_patterns = [
            r"^\s*(?:#{1,6}\s*)?\*{0,2}(?:에디터스\s*(?:픽|바)|editor['’]?s['’]?\s*(?:picks?|bar))\b",
            r"^#+\s*(\[)?(read more|most popular|latest stories|related (stories|articles|news)|popular stories|opinion|editorial|top stories|trending|recommended)",
            r"^#+\s*(\[)?(관련\s*기사|추천\s*기사|인기\s*기사|관련\s*뉴스|인기\s*뉴스|핫뉴스|에디터스\s*픽|editor'?s\s*picks?|많이\s*본\s*뉴스|주요\s*뉴스|랭킹뉴스|헤드라인|주요이슈)",
            r"^\s*(에디터스\s*픽|editor'?s\s*picks?|많이\s*본\s*뉴스|주요\s*뉴스|유튜브\s*채널|랭킹뉴스|핫뉴스|추천뉴스|실시간\s*인기)\b",
            r"^\s*\*{0,2}(공유하기|본문\s*글자\s*크기\s*조정|댓글|뉴스\+?|트렌드뉴스|외국어\s*뉴스|뉴스상품|출판물|서비스안내|SNS)\*{0,2}\s*$",
            r"^\s*comments closed\s*$",
            r"^\s*0\s*$",
            r"저작권자\(c\)",
            r"무단\s*전재[-–—\s]*재배포",
            r"(\*\[제보는|\b제보는\s*카카오톡|\bokjebo\b)",
        ]

        boilerplate_kws = [
            "본문 바로가기", "메뉴 바로가기", "기사제보", "all rights reserved",
            "copyright", "epaper", "live tv", "gift a subscription", "you are logged in",
            "english", "繁體版", "网站地图", "跳到中央內容區塊", "點這裡瞭解", "privacy statement",
            "本網站使用相關技術", "share this article", "follow us on", "subscribe to",
            "active subscription", "구독하기", "get the latest news", "whatsapp channel",
            "story comments", "공유하기", "url이 복사되었습니다", "본문 글자 크기 조정",
            "다양한 채널에서 연합뉴스를 만나보세요", "세 줄 요약 기술을 사용합니다",
            "not now allow notifications", "allow notifications", "subscribe to notifications",
            "get the latest news and updates from dawn", "recipient email", "your name*",
            "listen to article", "join our whatsapp channel", "dawnnews urdu",
            "subscribed with another email", "logout and login", "account subscription benefits",
            "premium stories", "editorials, opinions", "additional subscription benefits",
            "account settings", "need help with your subscription", "voluntary subscription fee",
            "your 'subscription' and 'like'", "products you've access to", "see all newsletters",
            "newsletter-international", "newslettersignup", "first day first show",
            "the view from india", "looking at world affairs"
        ]

        def _is_link_line(l_str: str) -> bool:
            return bool(re.match(r"^\s*(\*|\-)?\s*\*{0,2}\[.*?\]\(https?://.*?\)\*{0,2}\s*$", l_str))

        lines = cleaned.splitlines()
        clean_lines = []
        consecutive_links = 0

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            if any(
                re.search(pat, line_str, flags=re.IGNORECASE) for pat in footer_patterns
            ):
                removed_blocks.append("하단 추천기사/사이드바/댓글 블록 절단")
                break

            if len(clean_lines) >= 3 and sum(len(l) for l in clean_lines) > 200:
                if _is_link_line(line_str):
                    consecutive_links += 1
                    if consecutive_links >= 2:
                        removed_blocks.append("연속 추천링크 블록 감지 절단")
                        if clean_lines and _is_link_line(clean_lines[-1]):
                            clean_lines.pop()
                        break
                else:
                    consecutive_links = 0

            lower_line = line_str.lower()
            strong_kws = ["subscribe", "newsletter", "logout", "logged in", "products you've access to"]
            if any(kw in lower_line for kw in boilerplate_kws):
                if len(line_str) < 150 or any(skw in lower_line for skw in strong_kws):
                    removed_blocks.append("구독/광고/안내 배너")
                    continue

            if re.match(r"^\s*search\s*$", line_str, flags=re.IGNORECASE):
                removed_blocks.append("검색창 UI")
                continue

            if re.match(r"^\s*cancel\s*$", line_str, flags=re.IGNORECASE):
                removed_blocks.append("취소 버튼 UI")
                continue

            if re.match(r"^\s*#+\s*email\s*$", line_str, flags=re.IGNORECASE):
                removed_blocks.append("이메일 공유 폼")
                continue

            if re.match(r"^\s*\[audio\s*\d+\].*?$", line_str, flags=re.IGNORECASE):
                removed_blocks.append("오디오 플레이어 UI")
                continue

            if re.match(r"^\s*published\s+[a-zA-Z]+\s+\d+,\s+\d{4}\s*$", line_str, flags=re.IGNORECASE):
                removed_blocks.append("단독 발행일자 라인")
                continue

            if re.match(r"^\s*_\s*published in dawn.*?\s*_\s*$", line_str, flags=re.IGNORECASE):
                removed_blocks.append("언론사 바이라인 푸터")
                continue

            if re.match(r"^\s*e-paper\s*\|\s*[a-zA-Z]+\s+\d+,\s+\d{4}\s*$", line_str, flags=re.IGNORECASE):
                removed_blocks.append("전자신문 헤더")
                continue

            if re.match(r"^#+\s*\[.*?\]\(.*?\)\s*$", line_str):
                removed_blocks.append("헤더 기사링크")
                continue

            if re.match(
                r"^\[.*?\]\(.*?\)\s*(published)?$", line_str, flags=re.IGNORECASE
            ):
                removed_blocks.append("바이라인 링크")
                continue

            if _is_link_line(line_str):
                removed_blocks.append("단독 링크 라인")
                continue

            if re.match(r"^(\s*(\[.*?\]\(.*?\)|[>/»›\|·\-])\s*)+(/정문|/正文|/)?$", line_str):
                removed_blocks.append("경로 탐색(브레드크럼)")
                continue

            clean_lines.append(line_str)

        unique_removed = sorted(list(set(removed_blocks)))
        return "\n\n".join(clean_lines), unique_removed

    def collect(
        self,
        query: str,
        days_back: int = 3,
        max_results: int = 5,
        min_score: float = DEFAULT_MIN_SCORE,
        strict_min_score: bool = False,
        include_domains: Optional[List[str]] = None,
        selected_languages: Optional[List[str]] = None,
        relevance_context: Optional[Dict] = None,
    ) -> List[Dict]:
        if self.client is None:
            print("[-] Tavily 클라이언트가 준비되지 않았습니다.")
            return []

        time_range = "day" if days_back <= 1 else "week" if days_back <= 7 else "month"
        domains_to_use = (
            include_domains if include_domains is not None else self.allowed_domains
        )

        fetch_count = min(max(max_results * 2, 10), 20)
        try:
            response = self.client.search(
                query=query,
                search_depth="advanced",
                include_domains=domains_to_use,
                time_range=time_range,
                include_raw_content=True,
                max_results=fetch_count,
            )
        except Exception as e:
            if self.raise_on_error:
                raise RuntimeError("Tavily 검색 요청 실패") from None
            print(f"[-] Tavily 검색 실패 (Query: '{query}'): {e}")
            return []

        processed_candidates = []
        seen_urls = set()
        seen_titles = set()
        seen_fingerprints = set()

        items = response.get('results', [])
        if selected_languages is not None:
            items = self._recover_search_bodies(items, relevance_context)
        for item in items:
            url = item.get("url", "")
            if not self._is_article_url(url):
                continue

            canon_url = self._canonicalize_url(url)
            if canon_url in seen_urls:
                continue

            canon_title = self._canonicalize_title(item.get("title", ""))
            if canon_title and canon_title in seen_titles:
                continue

            score = round(float(item.get("score") or 0.0), 4)
            if selected_languages is not None and not (item.get('raw_content') or '').strip():
                self._reject_article(item, 'body_unavailable')
                continue
            raw_text = item.get("raw_content") or item.get("content") or ""
            cleaned_text, removed_blocks = self._clean_content(raw_text)

            if selected_languages is None and len(cleaned_text.strip()) < 80 and item.get("content"):
                alt_cleaned, alt_blocks = self._clean_content(item.get("content"))
                if len(alt_cleaned) > len(cleaned_text):
                    cleaned_text = alt_cleaned
                    removed_blocks = sorted(list(set(removed_blocks + alt_blocks)))

            if len(cleaned_text.strip()) < 40:
                if selected_languages is not None:
                    self._reject_article(item, 'body_unavailable')
                continue

            detection = detect_body_language(cleaned_text)
            language = detection['language']
            if selected_languages is not None:
                if language == 'unknown':
                    self._reject_article(item, 'language_uncertain', detection)
                    continue
                if language not in selected_languages:
                    self._reject_article(item, 'language_not_selected', detection)
                    continue
            reason, relevance = topic_evidence(cleaned_text, relevance_context, item.get('title', ''))
            if reason:
                self._reject_article(item, reason, detection)
                continue

            fingerprint = self._content_fingerprint(cleaned_text)
            if fingerprint and fingerprint in seen_fingerprints:
                continue

            seen_urls.add(canon_url)
            if canon_title:
                seen_titles.add(canon_title)
            if fingerprint:
                seen_fingerprints.add(fingerprint)

            tier_info = self._resolve_tier_meta(url)
            doc_id = f"doc_{uuid.uuid4().hex[:8]}"

            is_truncated = len(cleaned_text) > MAX_RAW_CHARS
            status = "success_truncated" if is_truncated else "success_full"

            clipped_text = cleaned_text[:MAX_RAW_CHARS]
            paragraphs_text = self._split_into_paragraphs(clipped_text)
            if not paragraphs_text:
                continue
            quoted_source = self._extract_attribution_hint(clipped_text)

            paywall_keywords = [
                "subscribe to read",
                "active subscription",
                "로그인 후",
                "구독회원 전용",
                "有料会員",
            ]
            is_paywall_likely = (
                any(pw in raw_text.lower() for pw in paywall_keywords)
                and len(cleaned_text) < 400
            )
            needs_review = bool(len(cleaned_text) < 200 or is_paywall_likely)

            published_date = self._extract_published_date(url, cleaned_text, item.get("published_date"))
            text_snippet = self._build_clean_5_sentence_snippet(cleaned_text, item.get("title", ""))

            if not text_snippet:
                status = "failure_empty_snippet"

            doc_entry = {
                "doc_id": doc_id,
                "title": item.get("title", ""),
                "url": url,
                "score": score,
                "score_notice": None,
                "language": language,
                "language_detection": detection,
                "body_acquisition": {'method': item.get('_body_method', 'tavily_search')},
                "relevance": relevance,
                "tier": tier_info["tier"],
                "source_name": tier_info["name"],
                "country": tier_info["country"],
                "published_date": published_date,
                "text_snippet": text_snippet,
                "source_category": tier_info["category"],
                "credibility_weight": tier_info["weight"],
                "query": query,
                "status": status,
                "article_text": cleaned_text,
                # Existing analysis consumers still use these detailed source fields.
                "is_reprint_likely": bool(quoted_source),
                "quoted_source": quoted_source,
                "event_date": None,
                "raw_content": raw_text[:MAX_RAW_CHARS],
                "cleaning": {
                    "removed_blocks": removed_blocks,
                    "needs_review": needs_review,
                    "score_notice": None,
                },
                "paragraphs": [
                    {
                        "paragraph_id": f"{doc_id}_p{idx + 1}",
                        "raw_text": p_text,
                        "id": f"{doc_id}_p{idx + 1}",
                        "text": p_text,
                    }
                    for idx, p_text in enumerate(paragraphs_text)
                ],
            }
            processed_candidates.append(doc_entry)

        # 🎯 Tavily Score 메타데이터 및 적응형 랭킹 (Adaptive Ranking)
        # 1차: min_score(기본 0.7) 이상인 고관련도 문서 선별 (점수 내림차순 정렬)
        primary_docs = [d for d in processed_candidates if d.get("score", 0.0) >= min_score]
        primary_docs.sort(key=lambda x: x.get("score", 0.0), reverse=True)

        if strict_min_score:
            return primary_docs[:max_results]

        # strict 모드가 아닐 때: 0.7 이상 문서 우선 채택 후, 부족 시 타깃 도메인 내 최고점 순으로 보충
        # 단, 절대 하한선(MIN_SCORE_FLOOR=0.35) 미만인 문서는 무관한 검색 노이즈이므로 절대 보충하지 않고 폐기(Drop)!
        documents = primary_docs[:max_results]
        if len(documents) < max_results:
            remaining = [
                d for d in processed_candidates
                if d not in documents and d.get("score", 0.0) >= MIN_SCORE_FLOOR
            ]
            remaining.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            for d in remaining:
                if len(documents) >= max_results:
                    break
                d["score_notice"] = f"기본 임계값({min_score}) 미만이나 도메인 내 최고 관련도(score: {d.get('score')})로 보충 선별됨"
                d["cleaning"]["needs_review"] = True
                d["cleaning"]["score_notice"] = d["score_notice"]
                documents.append(d)

        return documents

    def _translate_to_actor_query(self, question: str, target: str) -> str:
        """
        [다국어 양방향 교차 변환 엔진]
        입력 질문이 한국어(ko), 중국어(zh), 영어(en), 일본어(ja) 중 어떤 언어여도
        대상 행위자(KR, CN, HK, TW, JP, US, IN, PK)에 맞는 공식 군사 전문 용어로 양방향 1:1 변환
        """
        cleaned = question.strip()
        for ch in [',', '/', '·', '・', '~', '?', '!', '"', "'", '`']:
            cleaned = cleaned.replace(ch, ' ')
        target_lang = "EN" if target in ("US", "IN", "PK") else ("TW" if target == "HK" else target)

        # 1. 다국어 교차 매핑: 한국어뿐 아니라 중국어, 영어, 일본어 원문 구문도 타깃 언어로 치환
        sorted_lexicon = sorted(DEFENSE_LEXICON, key=lambda x: len(x[0]), reverse=True)
        for ko_phrase, trans_map in sorted_lexicon:
            candidates = [ko_phrase]
            for phrase in trans_map.values():
                if phrase and phrase not in candidates:
                    candidates.append(phrase)

            for cand in sorted(candidates, key=len, reverse=True):
                clean_cand = cand
                for ch in [',', '/', '·', '・', '~', '?', '!', '"', "'", '`']:
                    clean_cand = clean_cand.replace(ch, ' ')
                if clean_cand in cleaned or cand in cleaned:
                    target_val = ko_phrase if target == "KR" else trans_map.get(target_lang, trans_map.get("EN", ko_phrase))
                    if clean_cand in cleaned:
                        cleaned = cleaned.replace(clean_cand, f" {target_val} ")
                    elif cand in cleaned:
                        cleaned = cleaned.replace(cand, f" {target_val} ")
                    break

        # 2. 타깃 언어별 잔여 문자 및 조사/어미 정리
        if target in ("US", "IN", "PK"):
            cleaned = re.sub(r'[가-힯一-鿿぀-ヿ]', ' ', cleaned)
        elif target in ("CN", "HK", "TW", "JP"):
            # 중국어/일본어 타깃일 때 남은 한국어 잔여 문자(조사, 미매핑 단어 등) 깔끔히 제거
            cleaned = re.sub(r'[가-힯]', ' ', cleaned)
        elif target == "KR":
            removals = [
                r'현재\b', r'관련\b', r'선포한\b', r'일대\b', r'(?<!시)간\b', r'여부\b', r'분석\b',
                r'에\s*대한\b', r'에\s*관한\b', r'관한\b', r'내역은\b', r'있나요\b', r'알려줘\b',
                r'은\b', r'는\b', r'이\b', r'가\b', r'을\b', r'를\b', r'의\b',
                r'에\b', r'에서\b', r'및\b', r'과\b', r'와\b', r'로\b', r'으로\b',
            ]
            for r in removals:
                cleaned = re.sub(r, ' ', cleaned)

        final_query = " ".join(cleaned.split())
        return final_query if final_query else question.strip()

    def _expand_korean_to_7_actors(
        self, question: str, event_date: Optional[str] = None
    ) -> Dict[str, str]:
        clean_q = question.strip()
        queries = {
            "KR": self._translate_to_actor_query(clean_q, "KR"),
            "CN": self._translate_to_actor_query(clean_q, "CN"),
            "HK": self._translate_to_actor_query(clean_q, "HK"),
            "TW": self._translate_to_actor_query(clean_q, "TW"),
            "JP": self._translate_to_actor_query(clean_q, "JP"),
            "US": self._translate_to_actor_query(clean_q, "US"),
            "IN": self._translate_to_actor_query(clean_q, "IN"),
            "PK": self._translate_to_actor_query(clean_q, "PK"),
        }
        return queries

    @staticmethod
    def _country_limits(requested: int) -> Dict[str, int]:
        """Same country caps for the legacy and LLM-plan entry points."""
        limit = max(0, min(requested, DEFAULT_MAX_DOCS_PER_COUNTRY))
        limits = dict.fromkeys(('CN', 'HK', 'TW', 'JP', 'KR', 'IN', 'PK', 'US'), limit)
        base, extra = divmod(min(limit, MAX_GREATER_CHINA_TOTAL), 3)
        limits.update(CN=base + (extra >= 1), TW=base + (extra >= 2), HK=base)
        return limits

    def collect_from_korean(
        self,
        question: str,
        event_date: Optional[str] = None,
        reference_date: Optional[str] = None,
        max_docs_per_country: int = DEFAULT_MAX_DOCS_PER_COUNTRY,
        days_back: int = 30,
        min_score: float = DEFAULT_MIN_SCORE,
        strict_min_score: bool = False,
        **kwargs,
    ) -> Dict:
        ref_date = reference_date or event_date
        if "max_total_docs" in kwargs and kwargs["max_total_docs"] is not None:
            max_docs_per_country = kwargs["max_total_docs"]

        print(f"\n[🌐] 한국어 질문 감지: '{question}' (기준일: {ref_date or '전체'})")
        print(f"[+] 7개국(중국, 대만, 일본, 한국, 인도, 파키스탄, 미국) 맞춤 쿼리 변환 및 국가별 최대 {max_docs_per_country}건 수집 시작...")

        query_map = self._expand_korean_to_7_actors(question, ref_date)
        by_country = {
            "CN": [],  # 중국 본토
            "HK": [],  # 홍콩
            "TW": [],  # 대만
            "JP": [],  # 일본
            "KR": [],  # 한국
            "IN": [],  # 인도
            "PK": [],  # 파키스탄
            "US": [],  # 미국 / 글로벌
        }
        country_limits = self._country_limits(max_docs_per_country)

        seen_urls = set()
        seen_titles = set()
        seen_fingerprints = set()
        all_documents = []

        for country_key, q in query_map.items():
            req_count = country_limits[country_key]
            if req_count == 0:
                continue

            print(f"  [>] 검색 중 ({country_key}, 목표: {req_count}건): '{q}'...")
            t_country_start = time.time()
            target_domains = COUNTRY_DOMAINS.get(country_key, self.allowed_domains)
            docs = self.collect(
                query=q,
                days_back=days_back,
                max_results=req_count,
                min_score=min_score,
                strict_min_score=strict_min_score,
                include_domains=target_domains,
            )
            t_country_elapsed = time.time() - t_country_start
            print(f"      ㄴ [✓] {country_key} 완료 ({t_country_elapsed:.1f}초 소요, 유효 문서 {len(docs)}건 확보)")
            for d in docs:
                canon_url = self._canonicalize_url(d["url"])
                if canon_url in seen_urls:
                    continue

                canon_title = self._canonicalize_title(d.get("title", ""))
                if canon_title and canon_title in seen_titles:
                    continue

                fingerprint = self._content_fingerprint(d.get("article_text", ""))
                if fingerprint and fingerprint in seen_fingerprints:
                    continue

                seen_urls.add(canon_url)
                if canon_title:
                    seen_titles.add(canon_title)
                if fingerprint:
                    seen_fingerprints.add(fingerprint)

                if d.get("country") in ("UNKNOWN", "GLOBAL") and country_key != "US":
                    d["country"] = country_key

                if len(by_country[country_key]) < req_count:
                    by_country[country_key].append(d)

        for c_key, c_docs in by_country.items():
            all_documents.extend(c_docs)

        print(f"\n[🔒] 국가별 최대 {max_docs_per_country}건 선별 완료 (총 {len(all_documents)}건):")

        by_country_clean = {
            c_key: [
                {
                    "doc_id": d["doc_id"],
                    "title": d["title"],
                    "url": d["url"],
                    "score": d["score"],
                    "score_notice": d.get("score_notice"),
                    "language": d["language"],
                    "tier": d["tier"],
                    "source_name": d["source_name"],
                    "country": d["country"],
                    "published_date": d.get("published_date"),
                    "text_snippet": d.get("text_snippet", ""),
                    "source_category": d.get("source_category", "reputable_media"),
                    "credibility_weight": d.get("credibility_weight", 0.75),
                    "query": d.get("query", ""),
                    "status": d.get("status", "success_full"),
                    "article_text": d.get("article_text", ""),
                }
                for d in c_docs
            ]
            for c_key, c_docs in by_country.items()
        }

        return {
            "reference_date": ref_date,
            "korean_question": question,
            "total_count": len(all_documents),
            "by_country": by_country_clean,
        }

    def collect_plan(
        self,
        plan: dict,
        days_back: int = 7,
        max_docs_per_country: int = DEFAULT_MAX_DOCS_PER_COUNTRY,
        max_results_per_query: int = DEFAULT_MAX_DOCS_PER_COUNTRY,
        min_score: float = DEFAULT_MIN_SCORE,
        strict_min_score: bool = False,
        **kwargs,
    ) -> Dict:
        if "max_total_docs" in kwargs and kwargs["max_total_docs"] is not None:
            max_docs_per_country = kwargs["max_total_docs"]

        country_limits = self._country_limits(max_docs_per_country)
        event = plan.get("event", "")
        ref_date = plan.get("reference_date") or plan.get("event_date")
        raw_queries = plan.get("queries", [])

        query_map = {}
        for item in raw_queries:
            if isinstance(item, dict):
                lang = item.get("language", "unknown")
                q = item.get('search_query') or item.get("query", "")
                if q:
                    query_map[lang] = q
            elif isinstance(item, str):
                query_map[f"q_{len(query_map)+1}"] = item

        selected_languages = plan.get('selected_languages')
        if selected_languages is None:
            selected_languages = list(query_map)
        query_map = {lang: query for lang, query in query_map.items() if lang in selected_languages}
        self.filter_rejections = []
        self.body_recovery = {'attempted': 0, 'recovered': 0, 'failed': 0}
        self._body_cache = {}
        self.search_attempts = []

        all_docs = self.collect_multilingual(
            queries=query_map,
            days_back=days_back,
            max_results_per_query=min(max_results_per_query, DEFAULT_MAX_DOCS_PER_COUNTRY),
            min_score=min_score,
            strict_min_score=strict_min_score,
            selected_languages=selected_languages,
            relevance_context=plan.get('relevance_context'),
            fallback_queries={item['language']: item['query'] for item in raw_queries
                              if isinstance(item, dict) and item.get('search_query')
                              and item['search_query'] != item.get('query')},
        )

        by_country = {
            "CN": [], "HK": [], "TW": [], "JP": [], "KR": [], "IN": [], "PK": [], "US": []
        }
        for d in all_docs:
            c = d.get("country", "UNKNOWN")
            if c in by_country:
                by_country[c].append(d)
            else:
                by_country["US"].append(d)

        # Within each country, make room for each represented selected language before filling slots.
        for country, candidates in by_country.items():
            limit = country_limits[country]
            queues = {language: sorted([doc for doc in candidates if doc['language'] == language],
                                      key=lambda doc: doc['score'], reverse=True)
                      for language in selected_languages}
            language_order = sorted((language for language in queues if queues[language]),
                                    key=lambda language: queues[language][0]['score'], reverse=True)
            retained = []
            while len(retained) < limit and any(queues.values()):
                for language in language_order:
                    if queues[language] and len(retained) < limit:
                        retained.append(queues[language].pop(0))
            by_country[country] = retained

        selected_docs = [doc for docs in by_country.values() for doc in docs]
        unique_rejected = {entry['url']: entry for entry in self.filter_rejections}
        rejected_counts = {}
        for entry in unique_rejected.values():
            reason = entry['reason']
            rejected_counts[reason] = rejected_counts.get(reason, 0) + 1
        return {
            "reference_date": ref_date,
            "event": event,
            "event_date": ref_date,
            "queries": query_map,
            "total_count": len(selected_docs),
            "documents": selected_docs,
            "all_documents": selected_docs,
            "filtering": {'selected_languages': selected_languages,
                          'language_method': 'body_langdetect',
                          'topic_method': 'body_anchors',
                          'body_recovery': self.body_recovery,
                          'search_attempts': self.search_attempts,
                          'language_counts': {
                              'candidates': {lang: sum(d['language'] == lang for d in all_docs)
                                             for lang in selected_languages},
                              'retained': {lang: sum(d['language'] == lang for d in selected_docs)
                                           for lang in selected_languages}},
                          'rejected_counts': rejected_counts,
                          'rejected': list(unique_rejected.values())},
            "by_country": by_country,
            **by_country,
        }

    def collect_multilingual(
        self,
        queries: Union[List[str], Dict[str, str]],
        days_back: int = 3,
        max_results_per_query: int = 5,
        min_score: float = DEFAULT_MIN_SCORE,
        strict_min_score: bool = False,
        selected_languages: Optional[List[str]] = None,
        relevance_context: Optional[Dict] = None,
        fallback_queries: Optional[Dict[str, str]] = None,
    ) -> List[Dict]:
        if isinstance(queries, dict):
            query_items = list(queries.items())
        else:
            query_items = [(f"query_{i+1}", q) for i, q in enumerate(queries)]

        all_docs = []
        seen_urls = set()
        seen_titles = set()
        seen_fingerprints = set()

        for lang_key, q in query_items:
            print(f"  [>] 검색 중 ({lang_key}): '{q}'...")
            docs = self.collect(
                query=q,
                days_back=days_back,
                max_results=max_results_per_query,
                min_score=min_score,
                strict_min_score=strict_min_score,
                selected_languages=selected_languages,
                relevance_context=relevance_context,
                include_domains=LANGUAGE_SEARCH_DOMAINS.get(lang_key),
            )
            self.search_attempts.append({'language': lang_key, 'query': q, 'kind': 'primary',
                                         'language_matches': sum(d['language'] == lang_key for d in docs)})
            fallback = (fallback_queries or {}).get(lang_key)
            if fallback and not any(d['language'] == lang_key for d in docs):
                additional = self.collect(query=fallback, days_back=days_back,
                    max_results=max_results_per_query, min_score=min_score,
                    strict_min_score=strict_min_score, selected_languages=selected_languages,
                    relevance_context=relevance_context,
                    include_domains=LANGUAGE_SEARCH_DOMAINS.get(lang_key))
                self.search_attempts.append({'language': lang_key, 'query': fallback,
                    'kind': 'full_query_retry',
                    'language_matches': sum(d['language'] == lang_key for d in additional)})
                docs.extend(additional)
            for d in docs:
                canon_url = self._canonicalize_url(d["url"])
                if canon_url in seen_urls:
                    continue

                canon_title = self._canonicalize_title(d.get("title", ""))
                if canon_title and canon_title in seen_titles:
                    continue

                fingerprint = self._content_fingerprint(d.get("article_text", ""))
                if fingerprint and fingerprint in seen_fingerprints:
                    continue

                seen_urls.add(canon_url)
                if canon_title:
                    seen_titles.add(canon_title)
                if fingerprint:
                    seen_fingerprints.add(fingerprint)

                all_docs.append(d)

        return all_docs

    def export_json(
        self, data: Union[Dict, List[Dict]], filepath: Union[str, Path]
    ) -> str:
        import json

        out_path = Path(filepath)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[+] 수집 데이터 저장 완료: {out_path.resolve()}")

        parent_collected = Path(r"c:\KoreanDefense\collected_live.json")
        try:
            with open(parent_collected, "w", encoding="utf-8") as pf:
                json.dump(data, pf, ensure_ascii=False, indent=2)
            print(
                "  [동기화] c:\\KoreanDefense\\collected_live.json 최신 업데이트 완료"
            )
        except Exception:
            pass

        return str(out_path.resolve())

    def load_json(self, filepath: Union[str, Path]) -> Union[Dict, List[Dict]]:
        import json

        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
