# risk_monitor

**서버(Windows)** + **클라이언트(라즈베리파이5)** 구조로 매트리스 압력 위험을 실시간 모니터링하는 앱 쌍.
서버는 대시보드를 제공하고, 클라이언트는 센서 데이터를 읽어 위험도를 계산해 서버로 보고합니다.

- [server/](server/README.md) — Windows에서 실행. 대시보드, 위험 경고 저장, 클라이언트 연결 상태 관리
- [client/](client/README.md) — 라즈베리파이5에서 실행. 시리얼 센서 프레이밍(공유 [`../common/`](../common) 모듈 사용), 위험도 누적, 서버 리포팅

`server`와 `client`는 서로 짝을 이루는 앱이라 같은 디렉토리 아래 나란히 둡니다: `server/app.py`는 경고 이미지 렌더링을 위해 `client/image.py`의 `render_risk_image`를 그대로 임포트합니다.

## Quick Start

### 서버 PC (Windows)

0. 설치 (빌드 + 배포)
   ```
   git clone <repo-url> pressure_recorder_repo
   cd pressure_recorder_repo\risk_monitor
   build_windows.bat
   ```
   PyInstaller로 빌드 후 `%USERPROFILE%\pressure-server`에 배포하고 방화벽 규칙을 등록합니다.
1. 서버 앱 시작
   ```
   dist\pressure-server\pressure-server.exe
   ```
   (또는 소스에서, `risk_monitor/` 안에서: `python -m server.app`)

   > exe 설치 경로에 한글이 포함되면 안 됩니다.
2. 브라우저로 대시보드 접속: `http://localhost:5000/dashboard`
3. 서버 IP 확인: 대시보드 상단에 표시되는 "서버 IP" 확인 (클라이언트 설정에 필요)

### 클라이언트 PC (라즈베리파이)

0. 설치
   ```bash
   git clone <repo-url> pressure_recorder_repo
   cd pressure_recorder_repo/risk_monitor
   python3 -m venv venv
   source venv/bin/activate
   pip install -r client/requirements.txt
   ```
1. 라즈베리파이에 SSH 접속
2. 서버 IP 설정
   ```bash
   ./set_server_ip.sh <서버-IP>
   ```
3. 클라이언트 시작
   ```bash
   ./start_client.sh
   ```
4. 클라이언트 중지
   ```bash
   ./stop_client.sh
   ```

## 데이터 저장 위치

`risk_monitor/` 폴더 자체는 소스코드만 담고, 실행 중 생성되는 데이터는 모두 폴더 밖에 저장됩니다.

- 서버 경고 로그/이미지: Windows는 `%APPDATA%\carerobot\press_warnings`, 그 외(dev/CI)는 `~/press_warnings`
- 클라이언트 경고 로그: `~/risk_monitor_logs/client_warnings`
- `start_client.sh`가 만드는 PID/로그 파일(`run/`, `logs/`)만 `risk_monitor/` 안에 남습니다 (프로세스 관리용, 데이터 아님)

## Project Structure

```
risk_monitor/
├── server/                  # Flask 대시보드 + 경고 저장 (Windows)
│   └── README.md
├── client/                  # 헤드리스 모니터링 클라이언트 (라즈베리파이5)
│   └── README.md
├── server.spec              # PyInstaller spec (risk_monitor/ 에서 빌드)
├── build_windows.bat        # 서버 exe 빌드 + 배포 + 방화벽 등록
├── start_client.sh
├── stop_client.sh
└── set_server_ip.sh
```

## Tests

```bash
python -m pytest server/tests/ client/tests/ -v
```
