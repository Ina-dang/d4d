# Vercel 배포 준비

> 현재 시연 서버는 2026-10-11 Azure 학생 구독의 일본 서부 VM에 배포했다.
> 전용 도메인 없이 Azure 기본 DNS와 HTTPS를 사용한다.
> 접속·운영·실측 방법은 [Azure 배포 안내](../deploy/azure/README.md)를 참고한다.
> 아래 내용은 앞서 검토한 Vercel 구성의 제약과 준비 사항이다.

## 결론과 현재 상태

**Vercel은 Python/FastAPI를 지원한다. 현재 겹눈을 그대로 Vercel Functions에 올려서 모든 기능을 유지할 수 있는 상태는 아니다.**
언어 지원과 앱의 저장·모델·작업 실행 구조는 별개다. 아래는 2026-10-11 코드와 공식 문서 확인 결과다.

| 기능 | 현재 구현 | Vercel Functions에 그대로 배포 |
| --- | --- | --- |
| 화면·HTTP API | FastAPI와 HTML/JS | 지원하는 유형 |
| Tavily 검색·원문 수집 | 외부 HTTPS API | 키·호출량·요청 시간 조건을 맞추면 가능 |
| 검색어·주장·번역·보고서 LLM | PC의 `127.0.0.1:11434` Ollama | PC에 접근할 수 없음. 호스팅된 추론 서비스와 어댑터 필요 |
| 문서 간 유사도 | 로컬 Ollama `bge-m3` | 외부 임베딩 서비스/호스팅된 모델 필요 |
| 신뢰도 계산 | 로컬 Python 함수와 subprocess | Python 계산 자체는 가능. 상태·작업 흐름 연결 확인 필요 |
| 원문·중간 JSON·검토 기록 | 로컬 파일과 SQLite | 영구 저장소로 사용 불가. DB/오브젝트 저장소 필요 |
| 탭 이동 중 계속 실행·진행률·재개 | `asyncio.create_task`, 메모리 잠금, JSON | 요청/인스턴스를 넘는 지속 실행 보장 없음. 내구성 작업 큐·공유 상태 필요 |
| PDF·MD·JSON 다운로드 | 저장된 결과 읽기·ReportLab | 입력을 영구 저장소에서 읽도록 변경 필요. PDF 글꼴도 포함해야 함 |

최대 요청 시간을 늘리거나 SQLite 경로를 `/tmp`로 바꾸는 것만으로 해결하지 않는다.
`/tmp`는 임시 공간이며 재배포·인스턴스 변경에도 남는 보고서 저장소가 아니다.
Vercel Functions의 시간 제한은 요금제·설정에 따라 달라진다. 제한 시간 내 응답했다는 사실이
응답 후 시작한 임의의 `asyncio` 작업의 완료를 보장하지 않는다.

공식 근거:

- [FastAPI 지원](https://vercel.com/docs/frameworks/backend/fastapi)
- [Python 런타임·엔트리포인트·번들](https://vercel.com/docs/functions/runtimes/python)
- [런타임 파일 시스템](https://vercel.com/docs/functions/runtimes)
- [Functions 제한](https://vercel.com/docs/functions/limitations)
- [응답 이후 작업의 수명](https://vercel.com/kb/guide/troubleshooting-inconsistent-logs-in-vercel-functions)

## 준비한 선택지: Vercel 접속 주소 + 지속 실행 Python 서버

`deploy/vercel/`은 **Vercel Functions에서 Python을 실행하는 구성이 아니라, 기존 앱으로 연결하는 게이트웨이 설정**이다.
화면·API·다운로드 모두 Vercel의 같은 origin을 사용하고 실제 HTML과 데이터는 Python 서버에서 제공한다.
모델이나 수집/검증 로직은 교체하지 않는다. 이 구성을 채택할지는 별도로 정할 수 있다.

```text
브라우저 → Vercel HTTPS 주소 → Python 서버의 HTTPS 주소
                                  ├─ FastAPI (worker 1개)
                                  ├─ Ollama (같은 서버의 loopback)
                                  ├─ Tavily (외부 API)
                                  └─ 영구 데이터 디렉터리 + SQLite
```

저장·진행 작업은 Python 서버가 담당한다. 서버가 꺼지면 작업도 멈추고, 재시작 후에는 기존 재개 기능을 사용한다.
현재는 **팀이 공유하는 단일 작업 공간**이다. 계정별 데이터 분리·동시 다중 사용자 작업은 구현하지 않았다.
수평 확장, worker 여러 개, autosleep은 현재 프로세스 내 잠금·작업 상태와 호환되지 않는다.

### Python 서버 준비

1. 계속 켜져 있는 Linux 서버에 Ollama 및 두 모델을 설치한다. Ollama는 `127.0.0.1:11434`를 사용한다.
2. `deploy/backend/.env.example`을 서버의 비공개 환경 파일로 복사해 실제 값을 입력한다.
   `TAVILY_API_KEY`, 팀 접속 계정/비밀번호, 정확한 도메인, 영구 저장 경로가 필요하다.
   기존 `/app` OpenAI 경로도 쓰려면 `OPENAI_API_KEY`를 넣는다.
3. Vercel과 Python 서버의 실제 HTTPS origin을 `SKYTRACE_PUBLIC_ORIGINS`에 등록한다.
   모든 `*.vercel.app`을 허용하지 않는다. Preview 주소도 사용할 주소만 추가한다.
4. Python 서버 도메인 DNS와 HTTPS 역방향 프록시를 구성한다. `deploy/backend/Caddyfile.example`을 참고한다.
   Ollama 포트를 인터넷에 공개하지 않는다. Vercel에는 모델 파일·API 키를 올리지 않는다.

Docker 예시 (저장소 루트에서 빌드, Linux 호스트의 Ollama 사용):

```sh
docker build -f deploy/backend/Dockerfile -t gyeopnun-backend .
sudo install -d -o 10001 -g 10001 /srv/gyeopnun-data
docker run -d --name gyeopnun --restart unless-stopped --network host \
  --env-file /secure/gyeopnun.env \
  --mount type=bind,source=/srv/gyeopnun-data,target=/data \
  gyeopnun-backend
```

`Dockerfile`은 `127.0.0.1:8766`, worker 1개로 시작한다. HTTPS 프록시는 같은 호스트의 해당 포트로 연결한다.
이 Docker 예시는 Linux 호스트 네트워크용이다. Windows Docker Desktop·호스팅 서비스의 네트워크를 동일하게 가정하지 않는다.
배포 모드에서는 계정과 16자 이상 비밀번호가 없으면 시작을 거절한다. 브라우저 기본 인증으로 팀 접속을 제한한다.
단독 로컬 실행의 기본 동작은 그대로다.

### Vercel 설정

1. 저장소의 Vercel 프로젝트 **Root Directory를 `deploy/vercel`**로 지정한다.
2. Framework Preset은 Other. 빌드·설치 명령은 해당 폴더의 `vercel.json`을 사용한다.
3. `BACKEND_ORIGIN=https://실제-Python-서버-도메인`을 설정한다. 경로·사용자명·비밀번호는 넣지 않는다.
4. 빌드하면 `.vercel/output/config.json`을 생성한다. 설정 누락 또는 localhost 주소는 빌드를 실패시킨다.
5. 배포 주소에서 접속 계정 입력 → 보고서 생성 → 다른 화면 이동 → 완료 → 검토 저장 → 모든 다운로드를 확인한다.

### 현재 Windows PC로 시연하는 경우

서버를 새로 구매하지 않고 **현재 PC의 Python + Ollama**를 그대로 사용할 수 있다.
동일 PC에서 화면을 공유하는 시연은 지금의 `http://127.0.0.1:8766`으로 가능하다.
외부 참가자가 Vercel 주소로 직접 접속하려면 다음 연결이 추가로 필요하다.

1. 현재 PC의 `8766` 포트로 연결되는 인증 가능한 HTTPS 터널/역방향 프록시를 준비한다.
2. PC 서버 설정에 `SKYTRACE_DEPLOYMENT=1`, 접속 계정/비밀번호를 설정하고 재시작한다.
   `SKYTRACE_ALLOWED_HOSTS`에는 로컬 호스트와 실제 터널·Vercel 호스트를 정확히 넣고,
   `SKYTRACE_PUBLIC_ORIGINS`에는 실제 터널·Vercel HTTPS origin을 넣는다.
3. Vercel의 `BACKEND_ORIGIN`을 터널의 HTTPS origin으로 설정한다.
4. 시연 중에는 PC·Python·Ollama·터널을 계속 켜 놓고 절전 진입을 막는다.

터널 주소가 바뀌면 양쪽 설정도 갱신한다. Ollama `11434` 포트는 외부에 연결하지 않는다.
현재 작업에서는 터널을 열거나 PC의 데이터를 외부에 공개하지 않았다.

원스톱 경로는 `POST /api/scenarios`가 즉시 반환하고 상태를 polling하므로 전체 LLM 실행 시간을 한 HTTP 요청에서 기다리지 않는다.
다만 **기존 개별 분석/보고서 동기 API**는 오래 걸리면 Vercel 외부 프록시의 **120초 제한**에 걸릴 수 있다.
전체 화면의 모든 보조 기능까지 배포 완료로 판정하려면 이 경로들도 작업 ID 방식으로 바꾸거나 별도로 실행 시간을 검증해야 한다.
[외부 프록시 제한](https://vercel.com/docs/limits), [Build Output 라우팅 규격](https://vercel.com/docs/build-output-api/configuration).

## 배포 사전 검사

```powershell
.\.venv\Scripts\python.exe -m app.cli.check_deployment --target local --check-services --output data/deployment/local-check.json
.\.venv\Scripts\python.exe -m app.cli.check_deployment --target vercel-functions --output data/deployment/vercel-check.json
```

두 번째 명령은 현재 구현에서 실패 코드 `2`가 정상이다. 외부 모델·영구 저장·내구성 작업이 아직 미구현이기 때문이다.
지속 실행 서버에서는 `--target persistent --check-services`로 설정을 검사한다.
이 도구는 유료 검색이나 모델 추론을 실행하지 않으며 키·비밀번호를 출력하지 않는다.
키의 실제 유효성, 외부 DNS/TLS, 클라우드 프록시, 볼륨의 재배포 후 영속성은 실배포 검증 대상이다.

## Vercel에서 Python까지 실행하려면 남은 작업

1. Ollama 전용 생성/임베딩 어댑터를 외부 모델 서비스로 전환. 현재 모델/번역 품질·점수 분포 재검증.
2. SQLite·JSON 접근을 외부 DB/오브젝트 저장소 어댑터로 전환. 원문·입력 해시·검토 버전 유지.
3. 수집/분석/보고서 단계를 내구성 큐 또는 워크플로로 분리. 공유 잠금·중복 실행 방지·취소·재개 구현.
4. 호스팅된 환경에서 전체 시나리오·동시 요청·재시작·다운로드·접근 제어 검증.

이 전환에는 사용할 모델 서비스, 저장소, 작업 실행 서비스와 비용/계정 설정이 필요하다.
현재 작업에서 해당 서비스를 임의로 선택하거나 결제·공개 배포하지 않았다.

## 이번 로컬 검증 결과

- 폴더 이동·배포 설정을 포함한 Python 테스트 375개, JavaScript 테스트 40개 통과.
- Ruff 검사 및 주요 새 CLI 모듈의 `--help` 실행 통과.
- 로컬 Ollama의 생성·임베딩 모델 설치, 프롬프트, PDF 글꼴, 신뢰도 함수 import, 저장 경로 검사 통과.
- 서버 재시작 후 기존 완료 실행의 조회 및 PDF(162,406바이트)·MD·JSON 다운로드 HTTP 200 확인.
- Vercel 게이트웨이 빌드 출력 생성은 예시 HTTPS 주소로 확인. 실제 클라우드 라우팅 검증은 미실시.
- 이 PC에는 Docker/Vercel CLI가 없어 컨테이너 빌드와 실제 배포는 실행하지 않음.
- 기존 `/app` OpenAI 경로의 키는 현재 설정되지 않음. 원스톱 Ollama 경로에는 필요하지 않음.

검사 JSON: `data/deployment/local-check.json`, `data/deployment/vercel-check.json`.
실제 외부 접속·터널·HTTPS·모델 추론을 포함한 시연은 주소/호스팅 방식이 정해진 뒤 확인해야 한다.
