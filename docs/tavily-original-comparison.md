# Tavily 원본 수집기 비교 · 2026-10-10

저장 요청 `3bffd2ca8e6d4139929f91cc53c481dc`의 같은 입력으로 동료 수집기를 실제 호출했다. 동료 버전은 `origin/develop`의 `579ea52f916f4d03b97f1eab0f04686761509871`이며 별도 작업 폴더에서 실행했다.

| 측정 | 시간 | 결과 |
|---|---:|---:|
| 저장된 사용자 버전 수집 단계 | 77.852초 | 1문서 |
| 동료 원본 수집기 전체 | 41.235초 | 6문서 |
| 원본 한국어 검색 1회 | 14.698초 | 원시 검색 결과 12건 |
| 원본 중국어 검색 1회 | 7.061초 | 원시 검색 결과 20건 |
| 원본 번체 검색 1회 | 6.912초 | 원시 검색 결과 20건 |
| 원본 영어 검색 1회 | 12.299초 | 원시 검색 결과 20건 |

원본은 4언어를 순차 호출했다. 사용자 버전의 저장 기록에는 4언어 검색 외에 전체 검색어 재시도 3회, 본문 없는 URL 12개의 재수집이 있다. 저장 실행의 검색어 생성은 캐시 적중으로 약 0.35초였다. 따라서 15초라는 외부 측정과 비교할 때 검색 1회인지 다국어 수집 전체인지 먼저 구분해야 한다. 이 측정으로 컴퓨터 성능 차이를 원인으로 확정할 수 없다.

두 버전은 수집 시점과 필터 동작이 다르다. 원본은 `search_query`, `selected_languages`, `relevance_context`를 사용하지 않고 `query`를 읽는다. 결과 건수나 전체 시간 차이를 순수 속도 개선율로 해석하지 않는다.

## 보관 범위

- 커밋된 사용자 `frame` 수정 5개 파일의 별도 보관: stash `08b258e6d1b2cfb00626415ca3c716112344c48f`. README, article_filters, collector, config, schemas를 포함한다. 동료 원본 실행 작업 폴더는 `C:/Users/USER/.codex/worktrees/tavily-original-comparison/d4d`다.
- 사용자가 현재 작업 폴더의 변경도 보관하도록 재요청하여, `git stash push --include-untracked -- frame`으로 stash `c15a4a7c157ad4759291ceb223e599d653265f55`를 추가했다. 이 stash는 당시 미커밋 `frame/collector.py` 변경 15줄을 보관한다. 직후 현재 폴더의 `frame` 변경이 없는 것을 확인했다.
- 나머지 작업 폴더 변경은 건드리지 않았다. 현재 브랜치의 커밋된 `frame` 전체를 동료 버전으로 교체한 것은 아니다. 원본 비교는 위 별도 작업 폴더에서 수행했다.

## JSON 중복

사용자 결과는 같은 문서를 `documents`, `all_documents`, `by_country`, 국가 코드 최상위 필드에 4번 저장한다. 원본도 `documents`, `by_country`, 국가 코드 필드로 3번 저장한다. 원본으로 바꿔도 중복이 완전히 없어지지는 않는다. 문단의 `raw_text`와 `text`, `paragraph_id`와 `id`도 중복된다.

로컬 실측 자료는 `data/benchmarks/tavily-original-comparison/summary.json`, `teammate-original-collected.json`, `run_original.py`에 보존했다. API 키는 출력에 포함하지 않았다. 커밋이나 푸시로 원시 수집 자료를 전송하지 않는다.
