# 🛡️ KoreanDefense / frame - 안보 OSINT 수집 및 검증 프레임워크

이 모듈(`frame`)은 **해커톤 Track T2-1 (Fusion OSINT Copilot)**의 **다국어 OSINT 데이터 수집, 정제 및 전처리 파이프라인** 엔진입니다.  
팀원(신엽님, 나현님, 다슬님)의 분석 엔진(`d4d`) 및 오케스트레이터와 완벽하게 연동되며 독립 패키지로도 실행 가능합니다.

---

## 📁 파일 구성

| 파일명 | 역할 | 설명 |
| :--- | :--- | :--- |
| `config.py` | **설정 및 도메인 티어 정의** | 8대 관측 행위자 화이트리스트 도메인(Tier 1~3), 공식 SNS 도메인 및 가중치, `COUNTRY_DOMAINS`, `DEFAULT_MIN_SCORE`(0.7), `DEFAULT_MAX_DOCS_PER_COUNTRY`(20), `MAX_GREATER_CHINA_TOTAL`(20), `DEFENSE_LEXICON`(안보 전문 교차 번역 사전) |
| `schemas.py` | **데이터 스키마 정의** | Pydantic 기반 표준 데이터 규격 (`DocumentData`, `ParagraphData`, `CleaningMeta`, `OSINTCollectionResponse`) |
| `collector.py` | **핵심 수집 엔진 (`OSINTCollector`)** | Tavily 연동, 다국어(한/중/영/일) 질문 감지 및 양방향 1:1 변환, **국가별 최대 20건 / 중화권 3대 진영 합산 20건 쿼터 캡**, 3중 중복 방지, 본문 사이드바 절단, 스마트 문단 분할, SNS 게시글 수집 |
| `demo_run.py` | **검증 및 데모 실행 스크립트** | 실시간 라이브 수집 및 파일 동기화 단일 실행 검증 스크립트 |

---

## 🌐 핵심 기능 및 정책

### 1. 수집 건수 및 쿼터 캡 정책 (중국어 쏠림 방지)
- **기본 수집 한도**: 각 국가별 최대 **20건** (`DEFAULT_MAX_DOCS_PER_COUNTRY = 20`)
- **🇨🇳 🇭🇰 🇹🇼 중화권 3대 진영 합산 20건 쿼터 캡 (`MAX_GREATER_CHINA_TOTAL = 20`)**:
  - 중국어 문서의 과도한 범람을 막고 중화권 내 균형 잡힌 다각도 시각을 확보하기 위해, **중국 본토(CN) + 홍콩(HK) + 대만(TW) 합계 20건 상한선**을 엄격 적용합니다.
  - 기본 배분:
    - **중국 본토 (`CN`)**: 최대 7건 (국방부, 관영 매체 - 공식 선전 및 발표문)
    - **대만 (`TW`)**: 최대 7건 (대만 국방부, 중앙통신사 - 실측 대응 및 민주 진영 시각)
    - **홍콩 (`HK`)**: 최대 6건 (SCMP, 명보 - 본토 선전 검열을 완충하는 2차 심층 분석 보고서)
- **기타 주요국**: 한국(`KR`), 일본(`JP`), 미국(`US`), 인도(`IN`), 파키스탄(`PK`)은 각각 독립적으로 최대 20건씩 충실하게 수집됩니다.

---

### 2. 📱 OSINT 공식 SNS 도메인 지원 및 신뢰도 가중치 체계
기존 언론사/정부 공식 사이트 외에 빠른 속보성 팩트(Flash Intel)를 제공하는 **공식 SNS 도메인**을 화이트리스트에 탑재하고 차별화된 가중치를 부여합니다:

| 도메인 | 출처 구분 | 티어 | 신뢰도 가중치 | 대상 기관 / 설명 |
| :--- | :--- | :---: | :---: | :--- |
| `x.com` / `twitter.com` | `official_sns` | **Tier 3** | **0.60** | 미국 국방부(DoD), 대만 국방부(MND), 일본 방위성 통합막료감부 공식 트위터 속보 |
| `weibo.com` | `official_sns` | **Tier 3** | **0.60** | 중국 인민해방군 동부전구(@东部战区), 중국 국방부 공식 웨이보 발표 |
| `facebook.com` | `official_sns` | **Tier 3** | **0.55** | 대만 국방부 공식 페이스북 등 브리핑 계정 |
| `youtube.com` | `social_media` | **Tier 3** | **0.55** | 각국 국방부 공식 브리핑 영상 및 기자회견 라이브 |

> **💡 SNS 수집 필터링**: 단순 홈/탐색 페이지(`/`, `/home`, `/explore`)는 자동 배제하고, 공식 발표 트윗/게시물 상세 본문만 정제하여 수집합니다.

---

### 3. 🌐 다국어 질문 직접 입력 및 양방향 교차 변환
한국어뿐만 아니라 중국어, 영어, 일본어 등 사용자가 어떤 언어로 질문을 입력하더라도 언어를 자동 감지(`_detect_question_language`)하여 8대 전역 맞춤 쿼리로 1:1 양방향 변환합니다:

- **중국어 질문 입력 시** (`台湾海峡 解放军 东部战区 军事演习 航行警告`):
  - 🇰🇷 **KR**: `대만 해협 군사 훈련 중국 동부전구 항행 통제` (한국어로 역변환)
  - 🇺🇸 **US**: `Taiwan Strait PLA Eastern Theater Command navigation restrictions` (영어로 역변환)
  - 🇯🇵 **JP**: `台湾海峡 中国軍 東部戦区 航行警報` (일본어로 역변환)
  - 🇭🇰 **HK** / 🇹🇼 **TW**: 번체 군사 용어로 변환
- **영어 질문 입력 시**: 한국어, 중국어 간체, 대만 번체, 일본어로 완벽 교차 변환 지원.

---

### 4. 🛡️ 3중 중복 방어막 (Deduplication)
- **URL 정규화 (`_canonicalize_url`)**: 뉴스 기사 ID 슬러그(`/news/12345/slug` -> `/news/12345`) 및 트래킹 파라미터(`utm_*` 등)를 정규화하여 동일 기사가 URL만 다르게 들어오는 현상 100% 차단.
- **제목 정규화 (`_canonicalize_title`)**: 언론사 접미사(`- DAWN.COM`, `| 연합뉴스` 등) 제거 후 동일 제목 판별.
- **본문 지문 비교 (`_content_fingerprint`)**: 앞부분 지문 대조로 동일 기사 원천 차단.

---

### 5. 📑 기사 본문 정제 및 스마트 문단 청킹
- **하단 사이드바 완전 절단**: 기사 본문 하단의 `### Read more`, `### [Most Popular]`, `Comments Closed` 등 사이드바/추천 뉴스 수십 개를 감지 즉시 잘라내어 순수 기사 본문만 보존.
- **상단 헤더 제거**: `Get the latest news...`, 기사 제목 마크다운 링크, 바이라인 제거.
- **스마트 문단 청킹 (`paragraphs`)**: 마침표 등 문장 종결자와 공백 기준으로 분할하여 영단어가 `"powe"`와 `"r and influence."`로 잘리는 현상 완전 해결.

---

### 6. 🎯 Tavily Score 메타데이터 및 적응형 랭킹
- 각 문서에 Tavily 검색 관련도 점수(`score`)를 기본 메타데이터로 부여.
- `min_score` 기본값은 **`0.7`**로 설정되어 고관련도 문서를 최우선 채택.
- 정부/군 공식 화이트리스트 특성상 점수가 0.4~0.65에 집중될 경우, 최고 점수순으로 보충하되 `cleaning.needs_review = True` 및 `score_notice`를 기록하여 데이터팀이 검토할 수 있도록 안전장치 마련.

---

## 🚀 빠른 연동 방법

```python
from frame import OSINTCollector

collector = OSINTCollector()

# 어떤 언어로 질문을 입력해도 8대 전역 맞춤 쿼리로 변환되어 수집
result = collector.collect_from_korean(
    question="현재 대만 해협 일대 군사 훈련 관련, 중국 동부전구가 선포한 비행/항행 통제 시간·구역과 대만 국방부 실측 데이터 분석",
    max_docs_per_country=20,  # 국가별 최대 20건 (중화권 CN+HK+TW 합산 20건 캡 자동 적용)
    min_score=0.7,
)

# 결과 확인
print(f"총 수집 문서: {result['total_count']}건")
print(f"중국 본토: {len(result['CN'])}건, 홍콩: {len(result['HK'])}건, 대만: {len(result['TW'])}건")
print(f"한국: {len(result['KR'])}건, 일본: {len(result['JP'])}건, 미국: {len(result['US'])}건")
```
