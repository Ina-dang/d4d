# 🛡️ KoreanDefense / frame - 안보 OSINT 수집 및 검증 프레임워크

이 모듈(`frame`)은 **해커톤 Track T2-1 (Fusion OSINT Copilot)**의 **다국어 OSINT 데이터 수집, 정제 및 전처리 파이프라인** 엔진입니다.
팀원(신엽님, 나현님, 다슬님)의 분석 엔진(`d4d`) 및 오케스트레이터와 완벽하게 연동되며 독립 패키지로도 즉시 실행 가능합니다.

---

## 📁 파일 구성 및 역할

| 파일명 | 역할 | 설명 |
| :--- | :--- | :--- |
| `config.py` | **설정 및 도메인 티어 정의** | 8대 관측 행위자 화이트리스트 도메인(Tier 1~3), 공식 SNS 도메인 및 가중치, `COUNTRY_DOMAINS`, `DEFAULT_MIN_SCORE`(0.7), `MIN_SCORE_FLOOR`(0.35), `DEFAULT_MAX_DOCS_PER_COUNTRY`(20), `MAX_GREATER_CHINA_TOTAL`(20), `DEFENSE_LEXICON`(안보 전문 교차 번역 사전) |
| `schemas.py` | **데이터 스키마 정의** | Pydantic 기반 표준 데이터 규격 (`DocumentData`, `ParagraphData`, `CleaningMeta`, `OSINTCollectionResponse`) |
| `collector.py` | **핵심 수집 엔진 (`OSINTCollector`)** | Tavily 연동, 다국어(한/중/영/일) 질문 감지 및 양방향 1:1 변환, **국가별 최대 20건 / 중화권 3대 진영 합산 20건 쿼터 캡**, 3중 중복 방지, 본문 사이드바/에디터스픽/UI위젯 완전 절단, 스마트 문단 분할, Tavily Score 적응형 랭킹 및 `MIN_SCORE_FLOOR`(0.35) 노이즈 차단 |
| `demo_run.py` | **검증 및 데모 실행 스크립트** | 실시간 라이브 수집 및 파일 동기화(`collected_live.json`) 단일 실행 검증 스크립트 |

---

## 🏛️ 출처 티어(Tier) 체계 및 신뢰도 가중치

국방·안보 OSINT에서는 **"누가 발표했는가"**에 따라 신뢰도와 객관성이 완전히 다릅니다. 우리 수집기는 도메인을 엄격한 티어로 자동 분류하고 신뢰도 가중치(`credibility_weight`)를 부여합니다:

| Tier | 분류명 | 포함 도메인 | 기본 언어 | 가중치 | 역할 및 성격 |
| :---: | :--- | :--- | :---: | :---: | :--- |
| **Tier 1** | **역내 제3국 감시기구**<br>(Regional Observers) | `mod.go.jp` (일본 방위성·레이더 항적)<br>`coastguard.gov.ph` (필리핀 해경)<br>`mnd.go.kr` (한국 국방부) | `ja` / `en` / `ko` | **`0.95`** | **최고 신뢰도 (1순위)!** 직접 이해관계가 없는 제3국이 레이더/초계기로 직접 확인한 객관적 물리 팩트. |
| **Tier 2** | **당사국 공식 발표**<br>(Primary Parties) | `mnd.gov.tw` (대만 국방부)<br>`mod.gov.cn` (중국 국방부)<br>`ccg.gov.cn` (중국 해경) | `zh` | **`0.85`** | **공식 2순위**. 공식성은 높으나 자국에 유리하게 왜곡/선전(Propaganda)·일방 주장 가능성 감안. |
| **Tier 3** | **공신력 검증 언론**<br>(Reputable Media) | `yna.co.kr` (한국 연합뉴스)<br>`cna.com.tw` (대만 중앙통신사)<br>`kyodonews.net` (일본 교도통신)<br>`nhk.or.jp` (일본 NHK)<br>`thehindu.com` (인도 The Hindu)<br>`dawn.com` (파키스탄 Dawn)<br>`scmp.com` (홍콩 SCMP)<br>`mingpao.com` (홍콩 명보)<br>`channelnewsasia.com` (싱가포르 CNA)<br>`reuters.com` (로이터 통신)<br>`apnews.com` (AP 통신) | `ko`<br>`zh`<br>`ja`<br>`en` | **`0.75`** | **취재 3순위**. 신속한 팩트 보도. 사건 발생 개요 파악 및 2차 교차 보도 확인. 홍콩 매체는 본문 검열 완충 2차 분석 제공. |
| **Tier 3** | **OSINT 공식 SNS**<br>(Official SNS) | `x.com` / `twitter.com` (미국 DoD, 대만 MND 등 속보)<br>`weibo.com` (인민해방군 동부전구 공식 웨이보)<br>`facebook.com` (대만 국방부 브리핑)<br>`youtube.com` (국방부 공식 기자회견/브리핑) | `en`<br>`zh`<br>`ja` | **`0.55` ~ `0.60`** | **속보성 팩트 (Flash Intel)**. 정부/군 기관의 공식 계정 발표문 신속 수집. 단순 탐색/홈 제외 상세 본문 정제. |

---

## 🌐 핵심 수집 정책 및 파이프라인 기능

### 1. 수집 건수 및 쿼터 캡 정책 (중국어 쏠림 방지)
- **기본 수집 한도**: 각 국가별 최대 **20건** (`DEFAULT_MAX_DOCS_PER_COUNTRY = 20`)
- **🇨🇳 🇭🇰 🇹🇼 중화권 3대 진영 합산 20건 쿼터 캡 (`MAX_GREATER_CHINA_TOTAL = 20`)**:
  - 중국어 문서의 과도한 범람을 막고 중화권 내 균형 잡힌 다각도 시각을 확보하기 위해, **중국 본토(CN) + 홍콩(HK) + 대만(TW) 합계 20건 상한선**을 엄격 적용합니다.
  - 기본 배분:
    - **중국 본토 (`CN`)**: 최대 7건 (국방부, 관영 매체 - 공식 선전 및 발표문)
    - **대만 (`TW`)**: 최대 7건 (대만 국방부, 중앙통신사 - 실측 대응 및 민주 진영 시각)
    - **홍콩 (`HK`)**: 최대 6건 (SCMP, 명보 - 본토 선전 검열을 완충하는 2차 심층 분석 보고서)
- **기타 주요국**: 한국(`KR`), 일본(`JP`), 미국(`US`), 인도(`IN`), 파키스탄(`PK`)은 각각 독립적으로 최대 20건씩 수집됩니다.
- 이 제한은 한국어 직접 수집과 LLM 검색 계획(`collect_plan`) 모두에 적용됩니다. 사용자가 더 작은 한도를 선택하면 중화권 합산 한도도 함께 줄이며, 국가별로 선택 언어의 문서를 균형 있게 배분합니다.
- LLM 검색 계획 경로는 실제 본문으로 언어와 주제 관련성을 확인합니다. 우르두어 매체 검색, 누락 본문 복구, 해당 언어의 결과가 없을 때 전체 검색어 재시도도 유지합니다.

---

### 2. 🌐 다국어 질문 직접 입력 및 양방향 교차 변환
한국어·중국어·영어·일본어 질문의 용어를 `DEFENSE_LEXICON`에서 찾아 8대 관측 행위자의 언어에 맞는 검색어로 변환합니다:
- **중국어 질문 입력 시** (`台湾海峡 解放军 东部战区 军事演习 航行警告`):
  - 🇰🇷 **KR**: `대만 해협 군사 훈련 중국 동부전구 항행 통제` (한국어로 역변환)
  - 🇺🇸 **US**: `Taiwan Strait PLA Eastern Theater Command navigation restrictions` (영어로 역변환)
  - 🇯🇵 **JP**: `台湾海峡 中国軍 東部戦区 航行警報` (일본어로 역변환)
  - 🇭🇰 **HK** / 🇹🇼 **TW**: 번체 군사 용어로 변환
- **영어 질문 입력 시**: 한국어, 중국어 간체, 대만 번체, 일본어로 완벽 교차 변환 지원.

---

### 3. 🎯 Tavily Score 적응형 랭킹 및 절대 하한선 (`MIN_SCORE_FLOOR = 0.35`)
- 각 문서에 Tavily 검색 관련도 점수(`score`)를 기본 메타데이터로 부여.
- `min_score` 기본값은 **`0.7`**로 설정되어 고관련도 문서를 최우선 채택.
- **적응형 보충 (Adaptive Fallback)**: 정부/군 공식 화이트리스트 특성상 점수가 0.4~0.65에 집중될 경우, 최고 점수순으로 보충하되 `cleaning.needs_review = True` 및 `score_notice`를 기록하여 데이터팀이 검토할 수 있도록 안전장치 마련.
- **🛡️ 절대 품질 하한선 (`MIN_SCORE_FLOOR = 0.35`) 원천 차단**:
  - 관련성이 극히 떨어지는 기사(예: 파키스탄 검색 시 대만해협과 무관한 0.07~0.08점짜리 호르무즈 해협/이란 기사 등)는 보충 대상에서도 **완전 폐기(Drop)**하여 파이프라인의 데이터 무결성을 보장합니다.

---

### 4. ⚡ 도메인 최적화 및 실시간 수집 피드백
- **대용량 파일 병목 제거**: 인도 공보청(`pib.gov.in`)의 수십 MB 대용량 PDF 문서 응답 지연(단일 호출 43.5초) 문제를 확인하고, 핵심 정예 도메인(`mod.gov.in`, `thehindu.com`)으로 최적화하여 수집 시간을 **3.6초로 90% 이상 대폭 단축**했습니다.
- **파키스탄 화이트리스트 정예화**: `ispr.gov.pk` 접속 지연을 배제하고 최대 일간지 `dawn.com` 중심으로 재편.
- **실시간 콘솔 진행도 피드백**: 국가별 쿼리 실행 시 소요 시간과 수집 건수를 실시간으로 시각화 (`ㄴ [✓] {country} 완료 (N.N초, N건 확보)`).

---

### 5. 📑 기사 본문 정제 및 사이드바/에디터스 픽/UI 잔여물 완전 절단
- **하단 사이드바 완전 절단**: `### Read more`, `### [Most Popular]`, `Comments Closed`, `에디터스 픽`, `핫뉴스`, `랭킹뉴스`, `유튜브 채널`, `SNS`, `공유하기`, `저작권자(c)`, `무단 전재`, `제보는 카카오톡` 등을 감지 즉시 잘라내어 순수 기사 본문만 보존.
- **연속 추천링크 위젯 감지**: 본문 누적 후 `**[기사제목](URL)**` 형태의 볼드 마크다운 링크가 2개 이상 연속 등장 시 첫 줄부터 하단 전체 Truncate.
- **언론사 특화 UI 노이즈 정제 (Dawn 등)**:
  - `Search`, `Cancel`, `### Email`, `Not Now Allow Notifications`, `[Audio ...]`, 기자 바이라인 등 웹 레이아웃 잔여물 완벽 제거.
- **스마트 문단 청킹 (`paragraphs`)**: 마침표 등 문장 종결자와 공백 기준으로 분할하여 영단어가 잘리는 현상 해결 및 단독 링크 라인/헤더 라인 문단 생성 배제.

---

### 6. 🛡️ 3중 중복 방어막 (Deduplication)
- **URL 정규화 (`_canonicalize_url`)**: 뉴스 기사 ID 슬러그(`/news/12345/slug` -> `/news/12345`) 및 트래킹 파라미터(`utm_*` 등)를 정규화하여 동일 기사가 URL만 다르게 들어오는 현상 100% 차단.
- **제목 정규화 (`_canonicalize_title`)**: 언론사 접미사(`- DAWN.COM`, `| 연합뉴스` 등) 제거 후 동일 제목 판별.
- **본문 지문 비교 (`_content_fingerprint`)**: 정규화한 전체 본문의 SHA-256 지문으로 동일 기사를 제거합니다. 공통 사이트 머리말만 같은 별개 기사는 보존합니다.

---

## 🔄 순환 보고(Circular Reporting / 재인용) 방어 메커니즘

### 문제 상황
로이터 통신의 한 줄 보도를 여러 언론사(교도통신, CNA 등)가 단순히 재인용하여 받아쓴 경우, 알고리즘이 "여러 언론이 일치했으니 신뢰도 99%다!"라고 잘못 판단하는 **가짜 일치(Corroboration Illusion)** 현상이 발생합니다.

### 우리 프레임워크의 해결책
1. **수집기 (`collector.py`)**:
   - 본문 초반에서 다국어 패턴(`according to...`, `据...报道`, `~によると`, `~에 따르면`)을 감지하여 `quoted_source` 필드에 인용된 원천을 기록합니다.
   - `is_reprint_likely: True` 태그 부여.
2. **뒷단 검증단 (신엽님/나현님)**:
   - 기사가 여러 건이어도 `quoted_source`가 동일한 원천(예: "Taiwan MND")이면, **1개의 단일 출처 클러스터**로 묶어 점수 거품을 제거합니다.
   - **서로 다른 독립된 원천(예: 대만 국방부 성명 + 일본 방위성 레이더)**이 일치할 때만 최고 교차검증 점수를 부여합니다.

---

## 🤝 팀원 연동 규격 (최종 산출물 JSON 포맷)

앞단(Orchestrator)이 다국어 쿼리를 넘겨주면, 수집기는 뒷단(검증/LLM)에 아래 규격의 데이터(`Dict`)를 전달합니다:

```json
{
  "korean_question": "대만해협 군사활동",
  "event_date": "2026-10-01",
  "generated_queries": {
    "CN": "2026-10-01 台湾海峡 解放军 演习 战备警巡 东部战区 军机",
    "TW": "2026-10-01 台灣海峽 國防部 共機 越過中線 演習",
    "HK": "2026-10-01 台灣海峽 解放軍 軍事演習 東部戰區",
    "JP": "2026-10-01 台湾海峡 中国軍機 演習 防衛省 統合幕僚監部",
    "KR": "2026-10-01 대만해협 군사활동 국방부 군용기 동향",
    "IN": "2026-10-01 Taiwan Strait PLA military aircraft exercise China Taiwan",
    "PK": "2026-10-01 Taiwan Strait military activity China Taiwan tension",
    "US": "2026-10-01 Taiwan Strait PLA military exercises median line DoD"
  },
  "by_country": {
    "CN": [ /* 중국 문서 */ ],
    "TW": [ /* 대만 문서 */ ],
    "HK": [ /* 홍콩 문서 */ ],
    "JP": [ /* 일본 문서 */ ],
    "KR": [ /* 한국 문서 */ ],
    "IN": [ /* 인도 문서 */ ],
    "PK": [ /* 파키스탄 문서 (무관 기사는 0.35 하한선으로 자동 탈락) */ ],
    "US": [ /* 미국/글로벌 문서 */ ]
  },
  "total_count": 50,
  "all_documents": [ /* 전체 수집 문서 50건 */ ]
}
```

> **📊 실측 라이브 수집 현황 (질문: '대만해협 군사활동')**
> - **총 확보 문서**: **50건**
> - **국가별 확보 건수**: 
>   - 🇨🇳 **CN**: 1건 (공식 발표)
>   - 🇭🇰 **HK**: 4건 (SCMP 등 2차 검열 완충 분석)
>   - 🇹🇼 **TW**: 7건 (대만 국방부/중앙통신사 실측 대응)
>   - *(중화권 3대 진영 합산: 12건 / 캡 20건 엄격 준수)*
>   - 🇯🇵 **JP**: 11건 (방위성 레이더/교도통신 감시 기구)
>   - 🇰🇷 **KR**: 9건 (연합뉴스 등 정규 안보 기사)
>   - 🇮🇳 **IN**: 1건 (힌두스탄/모드 공식 팩트)
>   - 🇵🇰 **PK**: 0건 (대만해협과 무관한 0.07~0.08점 호르무즈/이란 기사 5건 전량 `MIN_SCORE_FLOOR = 0.35`로 자동 폐기)
>   - 🇺🇸 **US**: 17건 (DoD, 로이터, AP 등 국제 검증)

각 개별 문서는 아래 메타데이터 규격을 완벽하게 준수합니다:

```json
{
  "doc_id": "doc_a1b2c3d4",
  "url": "https://www.mod.go.jp/j/press/news/2026/10/10a.html",
  "title": "中国海軍艦艇の動向について",
  "score": 0.8263,
  "language": "ja",
  "tier": 1,
  "source_name": "Japan MoD / Joint Staff",
  "country": "JP",
  "source_category": "neutral_observer",
  "credibility_weight": 0.95,
  "is_reprint_likely": false,
  "quoted_source": null,
  "query": "2026-10-01 台湾海峡 中国軍機 演習 防衛省 統合幕僚監部",
  "published_date": "2026-10-10",
  "event_date": null,
  "status": "success_full",
  "article_text": "防衛省統合幕僚監部は、本日午前8時頃、中国海軍の艦艇2隻が台湾海峡周辺を航行したことを確認した。...",
  "cleaning": {
    "removed_blocks": ["하단 추천기사/사이드바/댓글 블록 절단", "마크다운 이미지 블록"],
    "needs_review": false,
    "score_notice": null
  },
  "paragraphs": [
    {
      "paragraph_id": "doc_a1b2c3d4_p1",
      "raw_text": "防衛省統合幕僚監部は、本日午前8時頃、中国海軍の艦艇2隻が台湾海峡周辺を航行したことを確認した。",
      "id": "doc_a1b2c3d4_p1",
      "text": "防衛省統合幕僚監部は、本日午前8時頃、中国海軍の艦艇2隻が台湾海峡周辺を航行したことを確認した。"
    }
  ]
}
```

- **`language`**: 원문 언어 코드 (`zh`, `ja`, `ko`, `en`).
- **`event_date: null`**: 나현님 요구사항대로 사건일은 수집단에서 임의로 채우지 않으며, 뒷단 LLM이 본문 문맥을 읽고 채웁니다.
- **`paragraph_id`**: LLM이 최종 보고서를 쓸 때 핀포인트 인용(`Citation`)할 수 있도록 모든 문단에 고유 ID를 부여합니다.
- **`score_notice`**: 점수가 0.7 미만인 경우 `"기본 임계값(0.7) 미만이나 도메인 내 최고 관련도로 보충 선별됨"` 안내가 부착되고 `needs_review: true`로 마킹됩니다.

---

## 🚀 빠른 연동 및 테스트 방법

### 1. 파이썬 코드 연동
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

### 2. 터미널 단독 실행
```bash
cd c:\KoreanDefense\frame
python demo_run.py
```
- `.env` 파일에 `TAVILY_API_KEY=tvly-...` 설정 시 실시간 라이브 수집 모드로 즉시 동작하며 `collected_live.json`에 최신 데이터가 동기화됩니다.
