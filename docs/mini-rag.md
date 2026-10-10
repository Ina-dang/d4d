# 선정 APAC 사건 미니 RAG · 팀 전달용

현재 구현은 **선정 사건에 저장한 공개 원문의 근거 검색 모듈**이다. 국방 지식 전체를 학습한 챗봇이나 자동 진위 판정기가 아니다. 기존 수집·LLM·검증·통계 모듈 사이에 재사용할 근거 검색 단계를 제공한다.

## 바로 실행

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8766
```

`http://127.0.0.1:8766/rag`에서 **가상 자료로 바로 시험하기**를 누른다. 외부 API나 모델 호출 없이 한국어·영어·중국어 원문 검색과 JSON 다운로드를 확인한다. 모든 시연 자료는 가상이다.

실제 자료는 사건 ID·이름·자료 범위를 등록한 뒤 수집 JSON을 업로드한다. 기존 수집 화면의 완료된 작업 ID로도 가져올 수 있다. JSON은 `documents`, `all_documents`, Tavily `results`, 수집 작업의 `output` 래퍼를 받는다. 사건 적합성은 팀에서 확인한 뒤 적재한다.

## 기존 담당자와의 연결

```text
LLM 검색 계획 → Tavily 수집 JSON → 사건 ID별 적재
사용자 질문 + LLM 언어별 검색어 → RAG 검색 → 원문 인용·출처·점수
→ 기존 LLM 주장 분석 → 코드 검증·통계 → 보고서
```

이 버전은 검색·인용 반환까지 구현한다. 검색 결과를 분석 LLM에 자동 투입하거나 보고서를 생성하지 않는다. `evidence`를 기존 분석 호출의 자료 입력으로 전달하고, 분석 결과가 인용한 `event_id/doc_id/chunk_id/paragraph_id`와 `quote`를 검증 담당자가 대조한다. 원문은 비신뢰 자료로 전달하고 원문 안의 명령을 실행하지 않도록 기존 분석 프롬프트를 유지한다.

## API 예시

1. `PUT /api/rag/events/selected-event` — `{ "label": "선정한 사건과 시기", "description": "자료 포함/제외 범위" }`
2. `POST /api/rag/events/selected-event/import` — 수집 JSON 전체.
3. `POST /api/rag/search`:

```json
{
  "event_id": "selected-event",
  "question": "대만해협 항공기 활동에 관해 어떤 원문 근거가 있는가?",
  "query_variants": ["Taiwan Strait aircraft activity", "台湾海峡 飞机 活动"],
  "countries": ["TW", "CN"],
  "languages": [],
  "published_start": null,
  "published_end": null,
  "event_start": null,
  "event_end": null,
  "top_k": 5,
  "include_demo": false,
  "include_snippets": false
}
```

직접 규격 적재는 `POST /api/rag/events/{event_id}/documents`에 `{ "documents": [...] }`를 보낸다. 예시 문서는 `app/static/rag-demo.json`, 상세 계약은 `app/rag/rag_schemas.py`, Swagger는 `/docs`에서 확인한다. 기존 보고서는 `POST /api/rag/events/{event_id}/reports/{report_id}`로 적재한다. 보고서 문서 ID는 보고서 ID와 원래 Source ID를 묶어 충돌을 막고 원래 문단 ID는 보존한다.

검색 상태는 `evidence_found`, `empty_event`, `no_eligible_documents`, `no_match`를 구분한다. 자료가 없거나 검색이 실패한 경우 해당 사건이 없다는 뜻이 아니다.

## 점수와 검증

| 필드 | 의미 | 사용 |
| --- | --- | --- |
| `retrieval_score` | 이 사건의 검색 대상 청크에서 계산한 BM25 문자열 관련도 | 원문 검색 순위. 0~1 확률이 아니며 서로 다른 검색의 값도 직접 비교하지 않음 |
| `tavily_score` / `tavily_query` | 수집 당시 검색어 관련도 | 수집 메타데이터. 현재 질문의 의미 관련도를 대신하지 않음 |
| `source_tier` / `credibility_weight` | 수집팀의 출처 분류·정책 가중치 | 그대로 전달. 검색 순위·진위 확률에 곱하지 않음 |
| `llm_relevance` | 입력 문서에 제공된 LLM 관련도 값 | 없으면 null. 이 모듈에서 LLM을 호출하거나 보정하지 않음 |

`quote == text[start_char:end_char]`를 보장한다. 문자 위치는 UTF-8 바이트나 JavaScript UTF-16 인덱스가 아니라 Python Unicode 문자 위치다. `raw_quote_verified`는 수집 원본 안에 동일한 인용 문자열이 있는지 표시할 뿐, 사건 대응·번역·주장 진위를 검증한 값이 아니다. 정제 본문에는 있으나 보관 원본이 잘렸다면 false가 될 수 있다.

게시일과 사건일은 구분하고 수집 요청의 사건 날짜를 각 문서의 사건일로 복사하지 않는다. 날짜 조건이 있을 때 미확인 날짜는 제외하며 이유별 건수를 반환한다. 시간대가 있는 게시 시각은 제공된 시각의 달력 날짜로 필터링한다. 시각 단위 기간 검색은 미구현이다.

동일 본문과 입력된 `source_cluster`는 결과에서 중복 억제한다. 문서별로 가장 높은 청크 1개를 반환한다. `quoted_source`와 `is_reprint_likely`는 표시만 하며 원 발언 주체가 같다는 이유로 다른 사건·발표까지 자동 합치지 않는다. 반환 문서 수·도메인 수를 독립 근거 수로 사용하면 안 된다.

## 현재 제한과 팀 보완 요청

- **LLM 담당:** 기존 언어별 검색어를 `query_variants`로 전달하고, 반환 원문의 사건·당사자·의미 관련성을 검토한다. 현재 검색은 단어/CJK 문자 bigram BM25이며 다국어 임베딩·자동 번역은 없다.
- **수집 담당:** 실제 본문/검색 요약 구분, 수집 시각, 출처 국가·기관, 문단 ID, 게시일, Tier 설명·정의의 일관성을 보완한다. upstream의 `success_full`은 수집기 선언이며 전체 페이지 확보를 보증하지 않는다. 추정 국가·등급·가중치를 RAG에서 새로 만들지 않는다.
- **검증 담당:** 인용·ID·날짜·사건 적합성을 검사하고 정제 본문과 수집 원본 간 차이를 검토한다. 등록된 사건 범위는 자료 적합성 인증이 아니다.
- **통계 담당:** 사람 평가 세트로 Recall@k·Precision@k와 언어별 누락을 측정하고 재인용 그룹을 검토한다. 현재 자동 테스트 통과를 실제 검색 품질 수치로 사용하지 않는다.

사건당 500문서, 요청당 100문서, 문서당 60,000자, 청크 900자/겹침 120자, 결과 최대 20개를 사용한다. 동일 사건·문서 ID를 재적재하면 본문과 청크를 갱신한다. SQLite의 `rag_*` 테이블에 저장하며 서버를 다시 시작해도 유지한다. 실제 API·모델 호출을 추가하지 않았고 실제 사건 검색 품질은 아직 평가하지 않았다.
