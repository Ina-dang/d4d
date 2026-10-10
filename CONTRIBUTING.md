# Git-flow와 커밋 안내

이 저장소의 폴더 이름은 `d4d`, 제품 이름은 겹눈입니다. 아래 규칙은 이 팀이 사용하는 Git-flow 운영 규칙입니다.

## 브랜치

| 브랜치 | 시작점 | 병합 대상 | 용도 |
| --- | --- | --- | --- |
| `main` | 초기 설정 | 직접 기능 커밋 금지 | 검증된 릴리스 |
| `develop` | `main` | 릴리스 준비 브랜치 | 기능 통합 |
| `feature/<이름>` | `develop` | `develop` | 기능 개발 |
| `release/<버전>` | `develop` | `main`, `develop` | 검증·버전 정리 |
| `hotfix/<이름>` | `main` | `main`, `develop` | 배포 긴급 수정 |

기능과 릴리스 병합은 `--no-ff`로 경계를 남깁니다. 릴리스 태그는 `v<버전>`으로 남깁니다. 공유 브랜치에는 강제 푸시하지 않습니다.

자동 생성 브랜치에 `codex/` 접두사가 있는 경우에도 뒤의 `feature/`, `release/`, `hotfix/`가 위 역할을 따릅니다. 예: `codex/feature/report-pipeline`.

## 작은 커밋

- 한 커밋에 한 책임을 담고 관련 테스트를 같이 추가합니다.
- 제목은 `feat:`, `fix:`, `test:`, `docs:`, `chore:` 중 변경 목적에 맞게 작성합니다.
- 본문에 변경 이유, 처음 읽을 파일, 검증 여부를 한국어로 적습니다.
- 커밋 전 staged diff를 확인합니다. `.env`, API 키, 원문 수집 결과, SQLite DB, 가상환경과 캐시는 커밋하지 않습니다.
- 초기 이력은 기존 구현을 책임별로 나눈 도입 기록입니다. 모든 중간 커밋이 완성 앱은 아니며, 릴리스에서 전체 테스트를 검증합니다.

## 처음 읽는 순서

1. `pyproject.toml`, `.env.example`: 실행 조건과 설정.
2. `app/core/schemas.py`, `app/legacy/demo.py`: 데이터 계약과 가상 시나리오.
3. `app/core/storage.py`, `app/legacy/verification.py`: 저장과 비교 규칙.
4. `app/legacy/providers.py`: 외부 검색·수집·LLM 연결.
5. `app/legacy/pipeline.py`, `app/legacy/export.py`: 분석 흐름과 보고서 출력.
6. `app/main.py`: API와 검토·승인 진입점.
7. `app/static/`: 실제 화면. `docs/storyboard.*`는 별도의 시안입니다.
8. `docs/collection-pipeline-design.md`: 검토 중인 설계이며 아직 구현된 기능으로 간주하지 않습니다.

```powershell
git log --reverse --no-merges --format="%h %s" main
git log --graph --oneline --decorate --all
```

## 검증

```powershell
.venv\Scripts\python.exe -m pytest
node --test tests/test_frontend.cjs
```

위 테스트는 외부 제공사 실연결이나 시안의 브라우저 검증을 대신하지 않습니다. API 인증·수집 성공 여부는 별도로 확인합니다.
