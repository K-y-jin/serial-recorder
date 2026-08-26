# server — 압력 위험도 모니터링 서버 + 대시보드

`client/`가 통신하는 실제 서버. `client/mock_server`와 동일한 REST 계약을 구현하고
(테스트용 mock은 그대로 `client/mock_server`에 남아있음), 위험 경고를 시각화하는
대시보드를 제공한다.

## 엔드포인트

- `GET/PUT /config` — `calibration_factor`, `critical_pressure`, `critical_time`, `cols`, `rows`
- `POST /event` — client의 risk warning: `{"accumulated_time", "risky_idx", "pressure_mask_idx"}`
- `GET/PUT /command` — `start`/`pause`/`stop`/`reset`/`state` 명령 큐 (한 번 소비되면 비워짐)
- `POST /state` — client의 `state` 명령 응답: `{"timestamp", "pressure"}` (전체 압력 벡터)
- `POST /image` — 위험 경고 스냅샷 PNG (multipart, 필드명 `image`). 누적 이미지가
  아니라 **현재 프레임 + risky_idx 셀 표시(빨간색) overlay**를 담고 있음
  (client `client/image.py:render_risk_image()`가 생성)
- `GET /image/latest` — 가장 최근에 받은 위험 경고 스냅샷 PNG
- `GET /dashboard` — 대시보드 HTML
- `GET /api/latest` — 대시보드 폴링용 JSON (`risky_idx`/`pressure_mask_idx`를 `[row, col]`
  2D 좌표로 변환해서 내려줌 — `server/grid.py:idx_to_rowcol()`, `row = idx // cols`).
  `connected`/`last_seen`으로 client 연결 상태도 포함

## 대시보드

`GET /dashboard`를 브라우저로 열면 1.5초 간격으로 `/api/latest`를 폴링해 매트리스
그리드를 `<canvas>`에 그린다:

- 압력이 실린 영역(`pressure_mask_idx`, 또는 `POST /state`로 받은 전체 압력값이 있으면
  그레이스케일로 그 값을 그대로 사용)을 실루엣처럼 배경으로 표시
- `risky_idx`(critical_time을 넘긴 셀)를 빨간색으로 강조
- 최근 이벤트가 없으면 "정상" 상태 표시
- 위험 경고 스냅샷(`POST /image`로 받은 최신 PNG)이 있으면 그리드 아래에 표시
- 상단에 client 연결 상태 배지 표시 (연결됨 / 연결 끊김 / 확인 중)

## 클라이언트 연결 상태

`server/connection_monitor.py:ConnectionMonitor`가 client의 접속 여부를 감시한다.
client가 서버에 실제로 요청을 보내는 엔드포인트(`GET /config`, `GET /command`,
`POST /event`, `POST /state`, `POST /image`)를 마지막으로 받은 시각을 기준으로
`--client-timeout`(기본 10초) 동안 아무 요청도 없으면 연결 끊김으로 판단한다:

- 연결 상태는 `/api/latest`의 `connected`(true/false/null)·`last_seen`으로 노출되고
  대시보드 상단 배지에 실시간 반영됨
- 연결이 끊기는 순간, 그리고 다시 연결되는 순간 각각 한 번씩
  `server/alert.py:fire_alert()`로 로그를 남기고, 대시보드가 열려 있으면
  대시보드가 팝업 + 알림음을 띄운다
  — 상태가 유지되는 동안 반복 알림은 발생하지 않음
- 서버가 처음 켜져서 client가 아직 한 번도 접속하지 않은 상태는 `connected: null`
  (알 수 없음)로 표시되며 알림도 발생하지 않음

```bash
python -m server.app --port 5000 --client-timeout 15
```

## 위험 경고 기록 (파일 저장)

`server/warning_store.py:WarningStore`가 위험 경고를 디스크에 영구 기록한다
(메모리만 유지하는 `ServerState`와 별개 — 서버 재시작해도 기록은 남음):

- `POST /event`가 올 때마다 `<warning-dir>/warnings.log`에 JSON 한 줄씩 append
- `POST /image`가 올 때마다 `<warning-dir>/images/<received_at>.png`로 저장

`<warning-dir>`은 기본 `warnings/` (서버 실행 cwd 기준), `--warning-dir`로 변경 가능:

```bash
python -m server.app --port 5000 --warning-dir /var/log/pressure/warnings
```

## 위험 경고 알림

`POST /event`로 client의 위험 경고(risky_idx가 있는 이벤트)를 받으면
`server/alert.py:fire_alert()`가 실행되어 로그를 남긴다. 실제 사용자에게
보이는 알림음/팝업은 서버 프로세스가 아니라 대시보드(브라우저)가 담당한다
(`server/templates/dashboard.html:playAlertBeep()` / `showWarningPopup()`)
— 알림 소리 크기·종류는 대시보드 설정에서 조절 가능하며 OS나 브라우저와
무관하게 항상 동일하게 재생된다.

## 실행

```bash
pip install -r server/requirements.txt
python -m server.app --port 5000 --cols 32 --rows 64
```

client를 이 서버로 연결:

```bash
python -m client.main --dry-run --server-url http://localhost:5000
```

브라우저에서 `http://localhost:5000/dashboard` 확인.

## 테스트

```bash
pytest server/tests -v
```

## Windows exe 빌드

PyInstaller로 `server/app.py`를 독립 실행형 Windows 앱으로 빌드할 수 있다
(Windows에서, 또는 Wine 환경에서 실행). 저장소 루트에서:

```bat
build_windows.bat
```

내부적으로는:

```bat
pip install -r server\requirements-build.txt
pyinstaller server.spec --noconfirm
```

빌드 결과는 `dist\pressure-server\pressure-server.exe` (onedir 빌드 — 템플릿 등 부속
파일이 exe 옆에 그대로 남아 있어 onefile보다 실행이 빠르다). 실행 시 기존과
동일한 CLI 인자를 사용한다:

```bat
dist\pressure-server\pressure-server.exe --port 5000 --cols 32 --rows 64
```

빌드 구성 파일: `server.spec` (PyInstaller spec, `server/templates`를
데이터로 포함), `server/win_launcher.py` (PyInstaller 진입점),
`server/requirements-build.txt` (런타임 의존성 + `pyinstaller`).
