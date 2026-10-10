# 수집 snippet → 신뢰도 함수 입력

수집 결과의 `text_snippet`으로 `docs`·`claims`를 만든다. snippet에서 주장이 없는 문서만 `article_text`의 관련 문장으로 보완한다. 새 `by_country` 형식과 저장된 수집 작업의 `output` 형식을 모두 읽는다. 원본 수집 파일은 수정하지 않는다. 신뢰도 함수 호출과 최종 보고서 작성은 별도 단계다.

## 실행

Ollama 로컬 모델 기본값은 주장 추출·한국어 번역용 `gemma4:e2b`, 다국어 임베딩용 `bge-m3`다. 두 모델을 순차적으로 실행하며 생성 모델을 해제한 뒤 임베딩 모델을 사용한다.

```powershell
ollama pull gemma4:e2b
ollama pull bge-m3
.\.venv\Scripts\python.exe -m app.cli.analyze_collection 수집.json --output data/verification-input.json
```

`.env`의 `OLLAMA_MODEL`, `OLLAMA_EMBEDDING_MODEL`, `OLLAMA_TIMEOUT`으로 기본값을 바꿀 수 있다. 모델이 없으면 자동 다운로드하지 않고 오류를 알려준다. 검색어 생성과 snippet 분석은 기본적으로 Ollama의 GPU 자동 선택을 사용한다. GPU가 없는 환경에서는 CPU로 실행된다. 화면에서도 CPU 실행을 강제하려면 `OLLAMA_FORCE_CPU=1`로 설정한다.

CLI에서 `--cpu`를 붙이면 추출·검토·임베딩 모두 GPU 사용을 끈다. `--question`, `--model`, `--embedding-model`로 실행 입력을 바꿀 수 있다. `--details`를 생략하면 결과 옆에 `verification-input-details.json`을 저장한다. 결과·상세 기록·수집 원본은 서로 다른 파일이어야 한다.

화면에서는 수집 완료 후 **주장·유사도 분석**을 누르고 **신뢰도 함수 입력 JSON 내려받기**를 선택한다.

- 분석: `POST /api/collections/{수집ID}/analysis`
- 진행 상태: `GET /api/collections/{수집ID}/analysis/status`
- 함수 입력 다운로드: `GET /api/collections/{수집ID}/analysis/download?format=verification`
- 전체 진단 결과 다운로드: `GET /api/collections/{수집ID}/analysis/download`

## 출력 계약

```json
{
  "docs": [
    {"id": "doc_a", "country": "CN", "weight": 0.5, "sim": {"doc_b": 0.6}},
    {"id": "doc_b", "country": "TW", "weight": 0.8, "sim": {"doc_a": 0.6}}
  ],
  "claims": [
    {"claim_id": "doc_a-c1", "document_id": "doc_a", "tier": 2,
     "event_date": null, "paragraph_id": "doc_a-snippet-p1",
     "translated_quote": "통제는 종료될 예정이다."}
  ]
}
```

수치·인용은 형식 설명용이다. `id`·`document_id`는 수집 doc_id, weight는 credibility_weight, country·tier는 수집 값을 보존한다. 국가 필드가 없을 때만 수집 그룹을 사용한다. sim은 다른 문서 ID별 분석 근거의 코사인 유사도 딕셔너리다. 일반 문서는 snippet, 원문 보완 문서는 보완한 원문 인용의 벡터를 사용한다. 모든 문서 쌍을 한 번씩 비교해 양방향 동일한 값을 저장하며 자기 자신은 제외한다. 질문 관련도는 question_relevance에 별도 보존한다. 검색 score·제목·한국어 번역은 이 임베딩에 추가하지 않는다.

함수 입력에는 요청 필드와 **기사당 대표 주장 최대 1개**만 들어간다. 검토된 번역 중 질문 어휘가 가장 많이 겹치는 것을 선택하고 동점이면 추출 순서를 따른다. 한국어는 두 글자 단위, 영문·숫자는 단어 단위로 비교하는 어휘 기준이며 LLM 중요도 판단은 아니다. 선택에 추가 모델 호출은 없다. claim_id는 재번호를 매기지 않고 보존한다. 전체 검토 주장·원문·표현·경고는 상세 기록에 둔다. 원문 보완에서 LLM은 대표 주장 하나만 추출한다.

주장이 없는 문서도 docs에 유지한다. 빈 인용을 만들어 개수를 채우지 않는다. `verification_selection`은 선택 ID·개수·주장 없는 문서를 기록한다. URL·제목은 수집 doc_id로 연결한다.

근거 ID는 snippet의 `${doc_id}-snippet-p1`, 원문 보완의 `${doc_id}-article-at{시작 위치}`다. 수집기 문단 ID가 아닌 분석 근거 식별자다. `analysis_paragraphs`에는 근거 문맥과 origin을 저장한다. 원문 보완은 origin이 article_text이며 source_start/source_end와 quote_start/quote_end를 Python 문자열 인덱스로 기록한다. 해당 구간은 저장된 article_text와 정확히 일치한다.

## 처리·검증

1. snippet의 원문 문장 후보 중 질문 관련 문장 최대 5개를 LLM이 선택·번역한다. 코드가 문장 번호로 정확한 원문을 연결한다. 짧은 문서 최대 두 개를 묶으며 문자 수 + CJK 문자 수 × 2가 2,200 이하인 경우에만 묶는다. 문서 ID는 고정 객체 키로 강제한다.
2. 원문 인용·날짜 근거를 코드로 확인하고 별도 LLM 호출로 주체·발언 주체·수치·조건·부정·예정·추정 등 번역 의미 보존을 검토한다. 실패한 주장만 최대 두 번 수정·검토한다. 확인되지 않으면 실패하며 주장을 지어내지 않는다. 수정 출력에는 번역·표현·날짜만 받고 코드가 원문·근거 ID를 보존한다. 수정은 최대 세 주장씩 나눈다. 사건 날짜가 직접 명시되지 않으면 null이며 게시일로 대체하지 않는다.
3. 생성 모델을 해제한 뒤 사용자 질문과 snippet을 최대 4개씩 임베딩한다. snippet이 누락·null·빈 문자열이거나 추출 결과가 비어 있으면 해당 문서의 article_text 문장 후보를 검색한다. 영상은 Transcript 영역을 우선 사용한다. 구독·로그인·홍보·조회수·링크·질문만 있는 후보는 제외한다.
4. 원문 문장별 질문 관련도로 순위를 매긴다. 입력 예산 내 상위 후보 최대 3개와 주변 문맥을 LLM에 전달해 대표 주장 하나를 추출·번역·검토한다. 원문 전체를 생성 LLM에 넣지 않는다. 후보가 48개를 넘으면 질문과 수집기의 해당 언어 검색어에 대한 어휘 겹침으로 48개를 먼저 선택한다. 이 경우 전체 원문 문장 중 정확한 최대 유사도를 찾았다고 표시하지 않는다. 너무 긴 문장은 자르지 않고 후보 전체를 제외하고 진단에 남긴다. 원문에도 근거가 없으면 문서와 실패 사유를 보존한다.
5. 문서별 분석 근거 간 코사인 유사도를 sim 딕셔너리로 저장한다. 일반 문서는 snippet, 보완 성공 문서는 선택한 원문 인용이다. 보완 후보 벡터를 재사용하므로 같은 인용을 다시 임베딩하지 않는다. 후보 임베딩 후 임베딩 모델을 해제하고 보완 추출 후 생성 모델을 해제한다.

기본 sim 대상은 other_documents다. 질문 관련도 숫자 계약은 CLI에서 `--similarity-target user_question`을 명시할 때만 사용한다. 두 계약은 검증 함수에서 동일하게 취급하면 안 된다. 코사인은 음수를 0으로 제한하고 소수점 여섯 자리로 저장한다. 진실 확률·주장 일치율·출처 독립성을 뜻하지 않는다. 벡터 누락·차원 불일치·0벡터·비정상 값은 오류다. 임베딩할 근거 문자열도 없으면 sim은 null이다. 보완 실패 문서에 유효한 snippet 문자열이 남아 있으면 그 문자열의 관련도와 실패 경고를 남긴다.

snippet은 최대 6,000자, 인용은 최대 1,600자다. 컨텍스트는 4,096이며 snippet 출력 상한은 2,048토큰, 원문 보완 출력 상한은 768토큰이다. 실제 토큰 한도가 먼저 걸릴 수도 있다. 문장 중간을 자르거나 실패를 성공으로 표시하지 않는다.

상세 결과는 analysis_scope, similarity_target, similarity_sources, analysis_question, question_relevance, article_fallback과 경고를 저장한다. 보완 성공 시 scope는 text_snippet_with_article_text_fallback이다. 보완 진단에는 후보 개수·순위·코사인 값·선택 근거 ID·성공 여부를 기록한다. 정상 snippet 주장이 있는 문서는 원문 보완을 실행하지 않는다. 기사 전체의 모든 주장·날짜를 검토한 분석은 아니다. 같은 모델의 번역 검토는 추가 검사이며 최종 신뢰도 점수가 아니다.

## 캐시·시간·호환

검토된 주장 추출은 `data/analysis-cache/`, 임베딩은 `data/embedding-cache/`에 저장한다. 모델 digest가 바뀌면 캐시도 달라진다. 질문이 바뀌면 추출은 다시 실행하지만 같은 snippet의 임베딩은 재사용하고 새 질문만 임베딩한다. 잘못된 응답은 성공 캐시로 저장하지 않는다. 모델 digest가 없으면 해당 캐시는 사용하지 않는다.

묶음 검토 결과도 문서별로 저장하므로 다음 실행의 문서 조합이 달라도 재사용한다. 과거 CPU 실행과 중복 본문 입력의 검토 완료 캐시는 현재 snippet의 원문·날짜 연결을 다시 확인한 뒤 재사용한다. 묶음 추출 프롬프트가 바뀌면 해당 검토 캐시는 재사용하지 않는다.

`timings`는 단계별 실측 초, `llm_calls`, `embedding_calls`, `cache_hits`를 제공한다. `total_seconds`에는 모델 확인·해제가 포함된다. 캐시 응답의 과거 실행 시간을 현재 시간으로 합산하지 않는다. `OLLAMA_TIMEOUT`은 개별 호출 제한이다. 처리 시간은 문서 수·길이·주장 수·재검토 횟수·CPU·캐시에 따라 달라진다.

화면 입력부터 3분은 성능 목표이며 현재 보장된 제한이 아니다. 모든 기사를 유지하므로 신규 기사 수·snippet 길이·CPU 속도·재검토에 따라 3분을 넘을 수 있다. 별도 Tavily 수집 시간과 아직 연결되지 않은 신뢰도 함수·보고서 시간은 아래 분석 실측에 포함되지 않는다. 실제 CPU·GPU 실행과 캐시 재실행 시간은 [snippet 성능 측정 기록](snippet-analysis-performance.md)을 참고한다.

진행률은 추출을 마친 snippet·원문 보완 확인·문서 쌍 유사도 계산을 기준으로 하며 남은 시간 비율이 아니다. API의 전체 완료율은 저장 성공 이후에만 100%다. 실패 시에도 API는 trace와 timings를 남기며 수집 성공 기록을 덮어쓰지 않는다.

API 진단 결과는 `data/source-analyses/{수집ID}.json`, 호출 기록은 `{수집ID}-trace.json`, 시간은 `{수집ID}-timings.json`에 저장한다. CLI 상세 기록은 결과와 trace를 한 파일에 저장하며, 분석 실패 시에도 오류·trace·단계별 시간을 보존한다.

API는 snippet 필드 또는 문단 목록 없는 article_text가 있으면 snippet·원문 보완 경로를 사용한다. 문단 목록만 있는 과거 수집 작업은 [기존 전체 본문 분석](source-analysis.md)을 유지한다. CLI는 항상 snippet·원문 보완 경로다. 기존 전체 본문 성능을 새 경로의 예상 시간으로 사용하면 안 된다.

과거 전체 본문 경로는 문서 간 sim 딕셔너리, 현재 snippet·원문 보완 경로도 문서 간 sim 딕셔너리이며 분석 입력은 다르다. 계산 입력·방법·성능을 동일하게 취급하지 않는다.

화이트리스트·신뢰도 공식·보고서 생성은 이번 변환 단계에서 실행하지 않는다.

## 신뢰도 반환값과 보고서 연결

2026-10-11 제공된 `result.json`은 `claims`마다 기존 여섯 필드에 `reliability`, `label`을 추가하고, 상위에 `summary`, `thresholds`를 반환한다. `claim_id`로 분석 근거를, `document_id`로 출처 정보를 연결한다. 반드시 **동일한 실행의 입력과 반환값**을 사용한다. ID가 같아도 인용·문서·날짜가 바뀌었거나 `sim` 계약이 바뀌었다면 다시 신뢰도를 계산한다.

보고서 LLM에는 사용자 질문, 원문 인용·한국어 번역·표현·사건 날짜, 출처 제목·URL·국가, 출처 가중치·질문 관련도, 반환된 신뢰도 점수·라벨, snippet 분석 범위와 경고를 전달한다. 보고서는 핵심 판단, 공통 사실 주장, 상충 후보, 출처별 해석, 분석의 한계의 다섯 항목으로 작성하고 각 판단에 근거 주장 ID를 붙인다. 전체 본문을 매번 다시 전달할 필요는 없으며 근거를 더 확인해야 하는 주장에 한해 본문을 추가로 읽는다.

- 공통 사실 주장은 같은 사건·시점·대상·수치·조건을 실제 인용끼리 대조해 판별한다. 같은 보도 재인용을 독립 확인으로 세지 않는다.
- 상충 후보는 동일 사건에 대해 양립하기 어려운 수치·내용을 제시하는 경우다. 시점·대상·조건 차이는 먼저 구분한다.
- 출처별 해석은 발언 주체와 의견·전망의 귀속을 유지한다. 출처 국가와 발언 주체 국가는 다를 수 있다.
- 신뢰도는 참고 점수다. 질문 관련도와 출처 가중치만으로 주장 내용의 사실 여부나 상충 여부를 확인할 수 없다.

제공된 표본은 19개 문서의 67개 주장이고 점수는 0.535~0.7317, 라벨은 전부 `관점 차이`다. 같은 문서 내 모든 주장에 같은 점수가 붙어 있다. 임계값은 `low: 0.5`, `high: 0.75`이며 이 표본만으로 라벨의 계산 공식을 확정할 수는 없다. 반환값에는 비교한 다른 주장 ID나 판정 근거가 없으므로 `label`을 보고서의 사실 비교 결과로 그대로 사용하지 않는다. 검증 담당자에게 라벨이 점수 구간인지 실제 주장 대조 결과인지 설명을 요청할 수 있다. `summary`도 이 라벨의 개수이며 독립 확인된 사실의 개수가 아니다.

수집 파일의 문서 수와 상세 분석 결과의 주장 수는 다르다. 현재 검증 입력은 기사당 대표 주장 하나만 전달한다. 최신 첨부 17개 문서는 원문 보완 후 상세 주장 46개, 대표 주장 16개다. YouTube 자막에서 한 주장을 보완했고 The Hindu는 article_text도 구독 안내여서 주장 없이 문서를 유지한다. 이전 19개 문서·67개 주장과 제공된 신뢰도 반환 표본은 과거 데이터다. `by_country`, `all_documents`, 국가별 상위 필드가 같은 문서를 반복하는 수집 파일은 `by_country`를 한 번만 읽으며 중복 집계하지 않는다. 현재 작업 폴더의 `frame/collected_live.json`은 별도 질문의 31개 문서다. 서로 다른 수집 실행의 입력과 신뢰도 점수를 결합하면 안 된다.

## 팀원 PC에서 CPU 측정

다음 명령은 GPU와 기존 캐시를 끄고 수집 JSON의 모든 기사를 처리한다. Python·Ollama가 있는 실제 팀원 PC에서 실행한다. 입력 파일의 기사 수, ID, SHA-256, CPU·RAM, 로드된 모델의 GPU 메모리, 단계 시간, 전체 시간, 180초 충족 여부를 기록한다. `--output`은 아직 없는 폴더여야 한다.

```powershell
.\.venv\Scripts\python.exe -m app.cli.benchmark_snippets 수집.json --output data/benchmarks/team-cpu-cold
.\.venv\Scripts\python.exe -m app.cli.benchmark_snippets 수집.json --output data/benchmarks/team-cpu-warm --cache-run data/benchmarks/team-cpu-cold
```

이 도구의 범위는 저장된 snippet → 신뢰도 함수 입력이다. 검색어 생성·Tavily 실시간 수집·아직 연결되지 않은 신뢰도 함수·보고서 생성을 포함한 전체 UI 시간을 측정한 것으로 표시하지 않는다. 캐시 없는 실행과 재실행은 서로 다른 폴더·결과로 남는다. `resources.jsonl`의 RAM은 시스템 전체의 사용량이며 Ollama 단독 메모리나 RAM 16GB 제한을 강제로 재현한 값은 아니다. 모델 파일·운영체제 캐시까지 초기화하는 시험은 아니다.
