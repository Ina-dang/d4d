# 🛡️ KoreanDefense / frame - 안보 OSINT 수집 및 검증 프레임워크

이 저장소(`frame`)는 **해커톤 Track T2-1 (Fusion OSINT Copilot)**의 **데이터 수집 및 전처리 파이프라인** 모듈입니다.
기존 코드베이스에 종속되지 않는 독립 모듈로 개발되었으며, 팀원(신엽님, 나현님, 다슬님)의 분석 엔진 및 오케스트레이터와 완벽하게 연동됩니다.

---

## 📁 파일 구성

| 파일명 | 역할 | 설명 |
| :--- | :--- | :--- |
| `config.py` | **설정 및 도메인 티어 정의** | 7개국 화이트리스트 도메인(Tier 1~3), `COUNTRY_DOMAINS`, 신뢰도 가중치, `DEFENSE_LEXICON`(안보 전문 번역 사전), 순환 보고 감지 정규식 |
| `schemas.py` | **데이터 스키마 정의** | Pydantic 기반 표준 데이터 규격 (`DocumentData`, `ParagraphData`, `SearchPlanRequest`, `OSINTCollectionResponse`) |
| `collector.py` | **핵심 수집 엔진 (`OSINTCollector`)** | Tavily 연동, 한국어 질문 -> 7개국 1:1 직역 변환, 국가별 타깃 도메인 검색, **나라별 최대 5건 그룹화 수집**, 언어 판별, 티어 태깅, 순환 보고 감지 |
| `demo_run.py` | **검증 및 데모 실행 스크립트** | 모의 데이터 테스트 및 실제 Tavily 기반 7개국 라이브 수집(총 35건) 단일 실행 검증 스크립트 |

---

## 🌐 핵심 기능

### 1. 질문 문장 1:1 자연어 직역 (불필요한 키워드 샐러드 배제)
인위적인 하드코딩 키워드 뭉치(`解放军 演习 战备警巡 东部战区 军机` 등)를 일절 배제하고, 사용자가 입력한 질문 문장을 안보 전문 사전(`DEFENSE_LEXICON`)을 통해 각 국가 언어로 **1:1 충실하게 직역**하여 검색합니다:

- 🇰🇷 **한국 (KR)**: `'대만해협 군사활동'` *(질문 원문 그대로 전달)*
- 🇨🇳 **중국 (CN)**: `'台湾海峡 军事活动'` *(중문 간체 1:1 직역)*
- 🇹🇼 **대만 (TW)**: `'台灣海峽 軍事活動'` *(중문 번체 1:1 직역)*
- 🇯🇵 **일본 (JP)**: `'台湾海峡 軍事活動'` *(일본어 1:1 직역)*
- 🇺🇸 **미국 (US)**: `'Taiwan Strait military activity'` *(영어 1:1 직역)*
- 🇮🇳 **인도 (IN)**: `'Taiwan Strait military activity'` *(영어 1:1 직역)*
- 🇵🇰 **파키스탄 (PK)**: `'Taiwan Strait military activity'` *(영어 1:1 직역)*

> **💡 문장형 질문 지원**: `"최근 카슈미르 국경 충돌"`, `"북한 탄도미사일 발사 동향"` 등 어떤 형태의 문장형 질문이 입력되어도 조사 및 어미를 정리하고 핵심 군사/지정학 엔티티를 정밀 치환하여 변환합니다.

### 2. 7개국 국가별 타깃 도메인 수집 (`COUNTRY_DOMAINS`)
전체 도메인을 한 번에 검색하여 특정 국가가 결과를 독점하는 현상을 원천 방지하기 위해, 각 국가 검색 시 해당 국가의 공식 국방 기관 및 검증 언론 도메인을 직접 타기팅합니다:
- **KR**: `mnd.go.kr`, `jcs.mil.kr`, `yna.co.kr`
- **CN**: `mod.gov.cn`, `ccg.gov.cn`, `news.cn`
- **TW**: `mnd.gov.tw`, `cna.com.tw`
- **JP**: `mod.go.jp`, `kyodonews.net`, `nhk.or.jp`
- **IN**: `mod.gov.in`, `pib.gov.in`, `thehindu.com`
- **PK**: `ispr.gov.pk`, `dawn.com`
- **US**: `defense.gov`, `apnews.com`, `reuters.com`, `channelnewsasia.com`

### 3. 나라별 그룹화 반환 (`by_country`)
수집 결과는 사용자가 가장 다루기 편하도록 **나라별로 묶인 형태**(`by_country`)로 반환되며, 각 국가마다 **최대 5건씩 균등하게** 선별됩니다:
- `result["by_country"]["TW"]` 또는 `result["TW"]`로 직관적인 인덱싱 지원.
- 7개국 × 최대 5건 = 총 35건의 다국어 교차 검증 데이터 확보.

---

## 🏛️ 7개국 출처 티어(Tier) 체계 및 가중치

국방·안보 OSINT에서는 **"누가 말했는가"**에 따라 신뢰도와 성격이 완전히 달라집니다. 수집기에서 각 문서에 아래 메타데이터를 자동으로 부착합니다.

| Tier | 분류명 | 포함 도메인 | 기본 언어 | 가중치 | 역할 및 성격 |
| :---: | :--- | :--- | :---: | :---: | :--- |
| **Tier 1** | **역내 제3국 및 공식 감시기구**<br>(Regional Observers) | `mod.go.jp` (일본 방위성·레이더 항적)<br>`mnd.go.kr` (한국 국방부)<br>`jcs.mil.kr` (한국 합동참모본부)<br>`coastguard.gov.ph` (필리핀 해경)<br>`defense.gov` (미 국방부) | `ja`<br>`ko`<br>`en` | **`0.95`** | **최고 신뢰도 (1순위)!** 직접 이해관계가 배제된 제3국이 레이더/초계기로 직접 확인한 객관적 물리 팩트. |
| **Tier 2** | **당사국 공식 발표**<br>(Primary Parties) | `mnd.gov.tw` (대만 국방부)<br>`mod.gov.cn` (중국 국방부)<br>`ccg.gov.cn` (중국 해경)<br>`news.cn` (신화통신 관영)<br>`mod.gov.in` (인도 국방부)<br>`pib.gov.in` (인도 정부 공보국)<br>`ispr.gov.pk` (파키스탄 군 홍보원) | `zh`<br>`en` | **`0.85`** | **공식 2순위**. 공식성은 높으나 자국에 유리하게 왜곡/선전(Propaganda)·일방 주장 가능성 감안. |
| **Tier 3** | **공신력 검증 언론**<br>(Reputable Media) | `yna.co.kr` (한국 연합뉴스)<br>`cna.com.tw` (대만 중앙통신사)<br>`kyodonews.net` (일본 교도통신)<br>`nhk.or.jp` (일본 NHK)<br>`thehindu.com` (인도 The Hindu)<br>`dawn.com` (파키스탄 Dawn)<br>`channelnewsasia.com` (싱가포르 CNA)<br>`reuters.com` (로이터 통신)<br>`apnews.com` (AP 통신) | `ko`<br>`zh`<br>`ja`<br>`en` | **`0.75`** | **취재 3순위**. 신속한 팩트 보도. 사건 발생 개요 파악 및 2차 교차 보도 확인. |

---

## 🔄 순환 보고(Circular Reporting / 재인용) 방어 메커니즘

- **감지 로직**: 본문 초반에서 다국어 인용 구절(`according to...`, `据...报道`, `~によると`, `~에 따르면`)을 자동 감지하여 `quoted_source` 필드에 인용 주체를 기록하고 `is_reprint_likely: True`를 마킹합니다.
- **분석단 활용**: 동일한 원천(예: "Taiwan MND")을 단순 전재한 기사들이 다수 있더라도 1개의 단일 출처 클러스터로 묶어 가짜 일치(Corroboration Illusion)로 인한 점수 거품을 방지합니다.

---

## 🤝 팀원 연동 규격 (최종 산출물 JSON 포맷)

```json
{
  "by_country": {
    "CN": [ /* 중국 문서 최대 5건 */ ],
    "TW": [ /* 대만 문서 최대 5건 */ ],
    "JP": [ /* 일본 문서 최대 5건 */ ],
    "KR": [ /* 한국 문서 최대 5건 */ ],
    "IN": [ /* 인도 문서 최대 5건 */ ],
    "PK": [ /* 파키스탄 문서 최대 5건 */ ],
    "US": [ /* 미국/글로벌 문서 최대 5건 */ ]
  },
  "korean_question": "대만해협 군사활동",
  "event_date": "2026-10-01",
  "generated_queries": {
    "KR": "대만해협 군사활동",
    "CN": "台湾海峡 军事活动",
    "TW": "台灣海峽 軍事活動",
    "JP": "台湾海峡 軍事活動",
    "US": "Taiwan Strait military activity",
    "IN": "Taiwan Strait military activity",
    "PK": "Taiwan Strait military activity"
  },
  "total_count": 35,
  "all_documents": [ /* 전체 수집 문서 35건 리스트 */ ]
}
```

각 개별 문서는 아래 메타데이터 규격을 준수합니다:

```json
{
  "doc_id": "doc_a1b2c3d4",
  "url": "https://www.mod.go.jp/j/press/news/2026/10/10a.html",
  "title": "中国海軍艦艇の動向について",
  "score": 0.8842,
  "language": "ja",
  "tier": 1,
  "source_name": "Japan MoD / Joint Staff",
  "country": "JP",
  "source_category": "neutral_observer",
  "credibility_weight": 0.95,
  "is_reprint_likely": false,
  "quoted_source": null,
  "query": "台湾海峡 軍事活動",
  "published_date": "2026-10-10",
  "event_date": null,
  "status": "success_full",
  "raw_content": "Tavily 수집 원본 (대조 및 검증용)",
  "article_text": "광고·메뉴·구독안내 등이 정제된 순수 기사 본문 전문",
  "cleaning": {
    "removed_blocks": ["구독/광고/안내 배너", "내비게이션/헤더/푸터 태그"],
    "needs_review": false
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

---

## 🚀 빠른 테스트 방법

```bash
cd c:\KoreanDefense\frame
python demo_run.py
```
- `.env` 파일에 `TAVILY_API_KEY=tvly-...` 설정 시 실제 7개국 라이브 수집 모드(총 35건)로 즉시 동작합니다.
- API 키가 없는 환경에서는 모의 데이터 검증 모드로 자동 동작합니다.
