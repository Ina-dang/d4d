# 신뢰도 함수와 보고서 연결

수집 JSON은 `reference_date`, `korean_question`, `total_count`, `by_country` 형태다. 신뢰도 함수에 전달할 파일은 `all-collected_verification-input.json`이다. 최상위는 `docs`, `claims`만 있으며 모든 수집 문서를 유지하고 근거가 있는 기사에서 대표 주장 하나씩 전달한다. `docs[].sim`은 다른 문서 ID를 키로 갖는 문서 간 임베딩 유사도다. 원문 전체에서 추출한 주장들의 사실 일치율은 아니다. 원문·전체 추출 주장·질문 관련도는 상세 기록에 보존한다.

신뢰도 함수는 원래 주장 여섯 필드와 `reliability`를 반환해야 한다. 현재 `analysis.reliability:run`은 `label`, 라벨별 `summary`, `thresholds`도 반환한다. 기존 전달 샘플의 기준대로 0.7 이상은 `값 일치`, 0.6 이상 0.7 미만은 `개연성 있음`, 0.6 미만은 `판단 보류`다. 비교 근거가 없어 점수가 `null`이면 수치를 유지하고 라벨은 `판단 보류`로 반환한다. 이 라벨은 점수 구간의 분류이며 실제 사실 일치나 진실 확률을 뜻하지 않는다. 기존 점수 계산은 바꾸지 않는다. 외부·이전 함수의 `label`, `country`, `summary`, `thresholds`는 여전히 선택 필드이며 라벨 없는 응답을 화면이나 LLM에서 임의로 분류하지 않는다. 반환 country가 있으면 수집 출처 국가와 대조한다. 점수는 유한한 0~1 숫자여야 한다. 주장 ID, 문서 ID, 티어, 사건 날짜, 근거 ID, 번역 인용을 모두 현재 전달 내용과 대조한다. 알 수 없는 주장이나 수정된 인용은 보고서 생성 전에 거부한다.

## 로컬 함수 설정

기본 함수는 develop에 들어온 `analysis/reliability.py`의 `run`이다. 서버 `.env`에 다른 함수가 설정돼 있으면 그 설정을 사용한다. 설정 변경 후 실행 중인 서버는 재시작한다.

```dotenv
SKYTRACE_RELIABILITY_FUNCTION=analysis.reliability:run
SKYTRACE_RELIABILITY_INPUT_MODE=dict
SKYTRACE_RELIABILITY_TIMEOUT=30
```

`D:/project/verification/reliability.py:calculate_reliability` 같은 파일 경로도 지원한다. 함수는 dict를 하나 받아 dict를 반환한다. JSON 파일 경로를 받는 구현이면 입력 모드를 `path`로 바꾼다. async 함수와 JSON 문자열 반환도 지원한다. 서버 설정에 지정한 함수만 별도 Python 프로세스에서 실행하고 시간 초과 시 종료한다. 함수의 동작을 대체할 임의 점수나 데모 함수는 제공하지 않는다.

현재 함수는 문서 간 유사도를 같은 입장 확률 구간에 대응시키고 출처 가중치·국가 보정으로 문서 점수를 계산해 해당 문서의 대표 주장에 부여한다. 사실 여부나 개별 주장 간 일치를 직접 검증한 확률이 아니다. `GLOBAL` 문서도 비교에 포함되지만 국가 보정에서는 하나의 그룹으로 처리하므로 실제 동일 국가·출처 종속성이 확인된 것으로 해석하지 않는다.

화면에서 수집 → **주장·유사도 분석** → **로컬 신뢰도 함수 실행 · 보고서 작성**을 누른다. 외부에서 반환 JSON을 받았다면 파일을 선택해 **반환 JSON으로 보고서 작성**을 사용할 수도 있다. 보고서는 핵심 판단, 공통 사실 주장, 상충 후보, 출처별 해석, 분석의 한계를 LLM이 작성하며 원문 인용·번역·실제 반환 점수를 함께 표시한다. 모든 대표 근거를 유지하고 모델 입력 한도를 초과하면 중단한다. 근거 없는 항목은 빈 상태로 두며, 공통·상충 항목은 근거 두 개 이상을 요구한다.

새 보고서는 항상 초안이다. 사람이 원문과 번역을 검토하고 검토자·의견을 입력해 승인하거나 보류한다. 재생성은 이전 승인을 물려받지 않는다. 분석 입력이 바뀌면 기존 보고서 승인을 막는다. 구조·인용 검사 후 보고서 문장과 인용 근거를 별도 LLM 호출로 대조한다. 공통·상충 관계는 경량 모델의 반복 판단으로 확정하지 않고 인용 쌍을 사람의 검토 대상으로 제안한다. 미지지·판단 불가 문장은 원문 근거와 함께 보류 기록에 남긴다. 경량 모델이 잘못된 공통·상충 분류를 놓친 실제 사례가 있어 비교 항목은 모두 LLM 제안 상태로 보류한다. 화면에서 인용 쌍을 읽고 반영할 항목을 직접 선택한다. 승인 요청에서는 모든 비교 제안의 반영·제외 여부를 함께 전달해야 한다. 이 검토도 동일 경량 모델의 판단이므로 의미 정확성은 보장되지 않는다. 사람의 원문 검토와 승인이 필요하다.

## 저장 파일로 실행

새 질문부터 보고서까지 한 번에 실행한다. 기존 시나리오를 덮어쓰지 않도록 새 출력 폴더를 사용한다.

```powershell
.\.venv\Scripts\python.exe -u -m app.cli.run_collection_scenario --report `
  --question '중국과 대만의 대만해협 충돌에 관한 양측 발표와 주요 논쟁사항' `
  --output data/scenarios/taiwan-question-new-run
```

`reliability-result.json`은 같은 실행의 실제 함수 반환값과 입력 해시, `reliability-result-full.json`은 기본 함수의 국가 보정·문서별 계산 근거를 저장한다. `report.json`, `report.md`, `scenario-summary.json`도 저장하고 같은 실행 ID로 화면 API에서 조회할 수 있게 보관한다. 수집·분석까지 완료된 새 실행은 `python -m app.scenarios.reliability_scenario --directory 해당폴더`로 이어갈 수 있다. 보고서는 승인 전 초안으로 저장한다.

PowerShell에서 저장된 시나리오를 이어갈 수 있다. `--result`를 생략하면 설정된 실제 로컬 함수를 호출한다.

```powershell
.\.venv\Scripts\python.exe -m app.cli.build_reliability_report `
  --collection data/scenarios/taiwan-question-develop-20261011/collective_live.json `
  --details data/scenarios/taiwan-question-develop-20261011/all-collected_verification-input-details.json `
  --result data/current-reliability-result.json `
  --output data/scenarios/taiwan-question-develop-20261011/report.json
```

API는 `POST /api/collections/{id}/analysis/verify-report`로 로컬 검증·보고서 생성을 실행한다. 반환 파일을 사용할 때는 `POST .../analysis/report`에 `{"reliability_result": {...}}`를 보낸다. `GET .../analysis/report-input`의 `verification_input_sha256`를 함께 보내면 현재 입력의 변경을 추가로 검사한다. 반환 JSON에도 같은 `input_sha256`를 넣을 수 있다. 해시는 정렬된 키·UTF-8·공백 없는 JSON으로 만든 검증 입력의 SHA-256이다. 로컬 직접 호출은 실제 전달 입력을 해시와 함께 `data/reliability-calls/`에 보존한다. 해시 없는 외부 응답은 주장 필드를 대조할 수 있지만 검증 함수가 사용한 가중치·sim까지 확인할 수 없다.

보고서와 호출 trace는 `data/reliability-reports/`에 저장한다. PDF·JSON·Markdown 다운로드와 검토 이력도 제공한다. 시나리오 보고서 화면과 PDF·Markdown의 근거 목록에는 수치 대신 반환된 라벨을 표시한다. `값 일치`는 연초록, `개연성 있음`은 연노랑, `판단 보류`는 연주황 pill이며 라벨이 없으면 회색 `라벨 미제공`으로 표시한다. 원래 점수는 JSON에 보존하며 예전 시연 데이터의 라벨이나 임계값을 새 실행에 가져오지 않는다. PDF는 단어 경계에서 줄을 바꾸되 한 줄보다 긴 URL·공백 없는 원문은 나눠 넘침을 방지한다. 수집·분석·보고서 모델 호출은 동시에 실행하지 않는다. `OLLAMA_FORCE_CPU=1` 설정도 보고서에 적용한다.

제공된 샘플 `result.json`은 이전 실행의 67개 주장 결과다. 최신 시나리오의 문서 ID가 다르므로 이 샘플을 새 수집 결과와 합치지 않는다. 최신 검증 입력으로 함수를 실행한 새 반환값이 필요하다. SNS의 수집 분류나 높은 점수는 계정의 공식성·출처 독립성·사실 여부를 증명하지 않는다. snippet 분석은 기사 전체 분석보다 근거 범위가 좁다.

새 `result (2).json`은 이전 17개 기사 시나리오의 대표 주장 16개와 정확히 일치하며 `개연성 있음` 7개·`판단 보류` 9개를 반환한다. 이번 develop 재수집의 8개 기사에는 맞지 않는다. 보고서와 점수는 실행별로 구분해 저장한다.

`GLOBAL` 출처도 공통·상충 비교에 포함한다. 국가가 확인되지 않았다는 메타데이터는 문장 비교를 막는 조건이 아니다. 검증 함수의 `값 일치` 라벨이 0건이어도 공통 내용이 없다는 결론으로 바꾸지 않는다. LLM이 찾은 비교 후보는 각각 공통 사실 주장·상충 후보 항목에 표시하고, 두 출처의 한국어 인용과 실제 반환 점수를 함께 보여 준다. 공통 내용은 발표·보도의 내용이 겹친다는 후보이며 독립적인 사실 확인을 뜻하지 않는다. 상충 후보는 같은 대상·시점·조건에서 양립 불가능한 내용이어야 한다. 단순히 해석이 다르면 출처별 해석에 표시한다. 후보 반영 여부를 사람이 결정하기 전에는 확정 항목으로 승격하거나 자동 승인하지 않는다.
