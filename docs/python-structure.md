# Python 코드 구조

2026-10-11 정리. 웹 진입점 `app.main:app`, 신뢰도 함수 `analysis.reliability:run`,
HTTP API 주소와 기존 `data/` 결과물은 그대로 유지한다.

| 경로 | 담당 기능 |
| --- | --- |
| `app/main.py`, `app/config.py` | 앱 조립·기존 검토 API·환경 설정 |
| `app/api/` | 주장 분석·신뢰도 보고서·RAG HTTP 라우터 |
| `app/collection/` | Tavily 수집 흐름·병렬 수집·수집 JSON 계약 |
| `app/search/` | 검색 의미 분석·다국어 검색어 생성 |
| `app/claims/` | snippet/원문 보완·주장 추출·번역·임베딩·문서 간 유사도 |
| `app/reliability/` | 팀 신뢰도 함수 호출과 별도 프로세스 실행 |
| `app/reporting/` | 보고서 계약·LLM 생성·PDF 출력 |
| `app/scenarios/` | 질문부터 보고서까지 자동 실행·검사·재개 |
| `app/rag/` | 근거 검색 자료형·변환·SQLite 저장 |
| `app/llm/` | 공통 Ollama 통신 |
| `app/core/` | 공통 자료형·저장·오류·캐시·자원 경로·접근 제어 |
| `app/cli/` | 파일 변환·벤치마크·시나리오·배포 검사 실행 도구 |
| `app/legacy/` | 별도 `/app` 화면의 기존 OpenAI 분석 흐름. 계속 사용 가능 |
| `app/prompts/`, `app/static/` | 프롬프트·기존 화면·PDF 글꼴 |
| `frame/` | 수집 담당자의 Tavily 구현. 공개 import 경로 유지 |
| `analysis/` | 검증 담당자의 신뢰도 구현. 공개 함수 경로 유지 |
| `tests/` | Python·브라우저 로직 회귀 검사 |
| `deploy/` | 선택 가능한 배포 설정 |

원자적 JSON 저장은 `app.core.json_io.save_json`을 사용한다. 서버 모듈에서 CLI를 import하지 않는다.
프롬프트와 글꼴 위치는 `app.core.paths`에서 정의하므로 모듈의 하위 폴더 위치에 의존하지 않는다.

## 실행 명령 변경

내부 Python 모듈 경로는 변경됐다. 팀 코드에서 옛 `app.<모듈>`을 import한다면 위 폴더로 갱신한다.
빈 호환 파일을 수십 개 남기지 않았으며, 기존 파일명은 각 담당 폴더 안에서 유지했다.

| 이전 명령의 모듈 | 새 모듈 |
| --- | --- |
| `app.analyze_collection` | `app.cli.analyze_collection` |
| `app.benchmark_snippets` | `app.cli.benchmark_snippets` |
| `app.build_reliability_report` | `app.cli.build_reliability_report` |
| `app.run_collection_scenario` | `app.cli.run_collection_scenario` |
| `app.reliability_scenario` | `app.scenarios.reliability_scenario` |

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8766
.\.venv\Scripts\python.exe -m app.cli.analyze_collection --help
.\.venv\Scripts\python.exe -m app.cli.run_collection_scenario --help
.\.venv\Scripts\python.exe -m app.cli.check_deployment --check-services
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/*.cjs
```

테스트 임시 파일·pytest·Ruff 캐시는 `.cache/` 아래로 모았다. 실제 수집 원문·보고서는
`data/`, 내보낸 산출물은 `output/`, 화면 캡처는 `docs/captures/`에 보존한다.
