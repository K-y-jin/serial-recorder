# pressure_recorder repo

매트리스 압력 센서를 다루는 두 개의 독립 앱이 공존하는 저장소입니다.

- **[pressure_recorder/](pressure_recorder/README.md)** — 시리얼로 압력 프레임을 읽어 실시간 colormap으로 표시하고 CSV로 저장하는 GUI(`main.py`) + 헤드리스 CLI 도구 모음(`cmd/`).
- **[risk_monitor/](risk_monitor/README.md)** — 서버(Windows)+클라이언트(라즈베리파이5) 구조로 압력 위험을 실시간 모니터링하는 앱 쌍(`server/`, `client/`).

두 앱은 시리얼 프레임 파싱 로직(`common/frame_parser.py`, `common/serial_reader.py`, `common/config.py`)을 공유합니다.

## Project Structure

```
common/               # pressure_recorder ↔ risk_monitor/client 공유 모듈
pressure_recorder/    # GUI + CLI (자세한 내용은 pressure_recorder/README.md)
risk_monitor/         # server + client (자세한 내용은 risk_monitor/README.md)
```

각 앱의 설치, 실행, 테스트 방법은 위 링크의 개별 README를 참고하세요.

## Dashboard

`risk_monitor/server`가 제공하는 웹 대시보드로, 클라이언트가 보고하는 압력 위험 상태를 실시간으로 확인합니다.

- 접속: 서버 실행 후 `http://<서버-IP>:5000/dashboard`
- 매트리스 그리드에 압력 실린 영역(실루엣)과 위험 셀(빨간색)을 표시
- 클라이언트 연결 상태(연결됨 / 끊김 / 확인 중) 배지 및 위험 경고 스냅샷 이미지 표시
- 자세한 엔드포인트/동작은 [risk_monitor/README.md](risk_monitor/README.md#3-dashboard) 참고

## License

TBD
