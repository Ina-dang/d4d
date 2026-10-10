# Azure 학생 계정 시연 서버

2026-10-11에 일본 서부 `rg-gyeopnun-demo / gyeopnun-demo`에 배포했다.
한국 지역은 학생 구독의 허용 지역 정책에 포함되지 않아 생성이 차단됐고,
사용자가 일본 서부의 동일한 4 vCPU / 16 GiB 구성을 선택했다.

- 접속: https://gyeopnun-demo-20261011.japanwest.cloudapp.azure.com/storyboard/storyboard.html
- VM: Ubuntu 24.04 LTS, Standard_B4as_v2, Standard SSD 64 GiB
- 모델: Ollama 0.40.2, gemma4:e2b, bge-m3 (CPU 사용)
- 앱: FastAPI worker 1개, systemd 지속 실행, Caddy HTTPS
- 신뢰도 함수: `analysis.reliability:run`
- 전용 도메인·Cloudflare·Vercel은 사용하지 않는다.

## 접속과 보관

팀 접속 계정은 로컬 `.cache/azure-deploy/access.txt`에 있다.
SSH 개인키, 접속 비밀번호와 Tavily 키는 Git에서 제외한 `.cache/azure-deploy/`에 보관한다.
이 디렉터리를 저장소에 추가하거나 공개하지 않는다.

서버 소스는 `/srv/gyeopnun/app`, Python 환경은 `/srv/gyeopnun/venv`,
원문·캐시·분석·보고서·SQLite는 `/srv/gyeopnun/data`에 저장한다.
비공개 환경 파일 `/etc/gyeopnun/app.env`는 root 소유, 권한 600이다.
자동 백업과 자동 종료는 설정하지 않았다. 데이터의 별도 백업이 필요하다.

외부에는 80/443을 열고, 앱과 Ollama는 각각 loopback 8766/11434에만 바인딩한다.
UI와 API에는 HTTP Basic 인증을 적용했다. 허용 호스트와 POST Origin도 Azure 주소로 제한한다.
SSH 22번은 설치를 진행한 PC의 실제 출발지 공인 IP 한 개(`/32`)만 허용한다.
통신사 NAT 환경에서는 일반 IP 조회 사이트와 VM에서 관측한 출발지 주소가 달랐다.
SSH 시간 초과 시 포트를 전체 공개하지 말고 출발지 IP와 NSG 규칙을 확인한다.

## 상태 확인

프로젝트 루트의 PowerShell에서 실행한다. `known_hosts`는 배포 당시 Azure 안에서
확인한 호스트 키와 대조하여 저장했으며, 검증을 끄지 않는다.

```powershell
ssh -i .cache/azure-deploy/gyeopnun-demo_ed25519 `
  -o StrictHostKeyChecking=yes `
  -o UserKnownHostsFile=.cache/azure-deploy/known_hosts `
  azureuser@20.210.184.149 "systemctl is-active gyeopnun ollama caddy; free -m; ollama list"
```

앱 로그는 `sudo journalctl -u gyeopnun -n 100 --no-pager`로 확인한다.
모델 설치는 Ollama 서비스 계정으로 실행해 HOME이 없는 systemd 임시 작업에서의
CLI 실패를 피한다: `sudo -u ollama -H ollama pull gemma4:e2b`.

실행 중에는 브라우저를 닫아도 서버 작업이 계속된다. VM이나 앱을 중지하면 작업은
중단되며, 재시작 뒤 화면에서 재개한다. 시연 작업 중 앱을 재배포하거나 재시작하지 않는다.

## 시나리오 측정과 결과 저장

아래 명령은 실제 Tavily 검색과 모델 추론을 실행한다. 모든 수집 기사를 유지한다.
새 출력 폴더를 사용해야 하며, 이미 실행한 작업의 결과만 확인하려면 `--run-id`로 연결한다.

```powershell
.\.venv\Scripts\python.exe -m deploy.azure.benchmark `
  --origin https://gyeopnun-demo-20261011.japanwest.cloudapp.azure.com `
  --env .cache/azure-deploy/app.env `
  --output data/deployment/azure-20261011/taiwan-cold `
  --run-id d9f3060ed22940b4a482c5926ff3b456
```

`scenario-run.json`에는 서버 경과 시간과 단계별 시간이 남는다.
완료 후 검색어·수집·분석·검증 입력·신뢰도 JSON과 보고서 JSON/MD/PDF를 다운로드한다.
`scenario-checks.json`은 문서 보존, sim 대칭, 원문 근거, 입력 해시와 신뢰도 연결을 검사한다.
통과는 구조와 근거 연결의 확인이며 주장 자체의 진실이나 번역의 완전성을 보증하지 않는다.
보고서는 사람의 검토 전 `draft`로 유지한다.

## 비용과 중지

생성 확인 화면의 VM 단가는 US$0.196/시간(24시간 약 US$4.70)이었고,
디스크·공용 IP 등은 별도다. 학생 크레딧에서 차감되며 실제 금액은 Azure 비용 관리에서 확인한다.
시연하지 않을 때는 Azure Portal의 VM **중지** 후 **중지됨(할당 취소됨)** 상태를 확인한다.
OS 내부 shutdown으로만 중지하면 컴퓨팅 요금이 계속 발생할 수 있다.
할당을 취소해도 디스크·일부 네트워크 비용은 남는다.
[Azure 상태별 과금](https://learn.microsoft.com/en-us/azure/virtual-machines/states-billing)

B4as_v2는 CPU 크레딧을 사용하는 버스트형 VM이다. 연속 고부하 시 기본 성능으로
제한될 수 있으므로 1회 측정값을 반복 시연의 최대 지연 보장으로 사용하지 않는다.
[Basv2 사양 및 CPU 크레딧](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/basv2-series)

## 소스 배포

`package.py`는 앱 소스와 필요한 정적 파일만 묶고 `.env`, 데이터, 캡처,
캐시와 개인키를 제외한다. 생성된 manifest와 서버의 SHA256을 비교한 뒤 설치한다.
`bootstrap.sh`는 준비된 Ubuntu 서버에서 실행하는 설치 도구다.
`--skip-models`는 같은 모델이 이미 설치됐거나 별도 설치 중일 때만 사용한다.
환경 파일과 Caddy 설정을 배치한 다음 앱 서비스를 시작한다.
이 도구는 Azure 리소스를 생성하거나 삭제하지 않는다.
