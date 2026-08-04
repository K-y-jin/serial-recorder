# client — 라즈베리파이5 압력 위험도 모니터링 클라이언트

`sensor/serial_reader.py` + `sensor/frame_parser.py`를 재사용해 매트리스 압력 센서
프레임을 시리얼로 읽고, 셀별 누적 위험도(`accumulated_risk`)를 계산해 임계 시간을
넘긴 셀을 서버로 보고하는 헤드리스(비-GUI) 프로그램.

## 동작 개요

- 매 프레임마다 `risk_mask = pressure > (critical_pressure / calibration_factor)`
- `accumulated_risk = (accumulated_risk + risk_mask * dt_min) * risk_mask`
  (`dt_min`은 실제 경과 시간(분), risky 하지 않은 셀은 즉시 0으로 리셋)
- `calibration_factor`, `critical_pressure`, `critical_time`은 서버에서
  주기적으로 polling(`GET /config`)해 가져오며, 값이 바뀌어도 진행 중인
  `accumulated_risk`는 리셋되지 않고 다음 프레임부터 새 값이 적용됨
- 어떤 셀의 `accumulated_risk`가 `critical_time`(분)에 도달하면 `POST /event`로
  보고. 같은 셀이 계속 risky 상태를 유지하면 최초 알림 이후 `--alert-cooldown`
  (기본 5분) 간격으로만 재전송

## 서버 명령 (start / pause / stop / reset / state)

`--command-poll-interval`(기본 2초)마다 `GET /command`로 대기 중인 명령을 가져와
즉시 반영한다. 시리얼 수신 자체는 명령 상태와 무관하게 항상 계속되며(최신
프레임을 `state` 응답용으로 유지하기 위함), risk 누적 계산만 `pause`/`stop`
상태에서 멈춘다.

- `start`: risk 누적 재개(정지 시간만큼 dt가 몰아서 누적되지 않도록 tick 기준
  시각을 재동기화)
- `pause`, `stop`: risk 누적만 중지 (accumulated_risk는 보존됨)
- `reset`: `pause` + `accumulated_risk = 0` + `start`를 한번에 수행 — 리셋 후
  즉시 다시 누적을 시작
- `state`: 현재 monitor 상태는 바꾸지 않고, 최신 pressure vector를
  `POST /state`로 즉시 전송 (`{"timestamp": ..., "pressure": [...]}`)

`GET /command` 응답 형식: `{"command": "start"}` 또는 대기 중인 명령이 없으면
`{"command": null}`. 서버는 한 번 전달한 명령을 큐에서 제거해야 한다(중복 적용
방지).

## mock_sensor — 하드웨어 없이 /dev/ttyUSB0 에뮬레이션

`client/dumpy_data/Calib31.CSV`(실제 녹화된 프레임 CSV, CsvLogger wide format)를
읽어 랜덤한 행(row=프레임)부터 순서대로 실제 센서 패킷 포맷(header+payload)으로
`socat`이 만든 가상 시리얼 장치에 스트리밍한다. `client/main.py --port /dev/ttyUSB0`
또는 `sensor` GUI가 실제 하드웨어처럼 이 장치를 열어 사용할 수 있다.

`socat` 설치 필요 (`sudo apt install socat`). `/dev/ttyUSB0`에 심볼릭 링크를
만들려면 보통 sudo 권한이 필요하다 — 권한 없이 테스트하려면 `--link /tmp/ttyUSB0`
같은 경로를 쓰고 client의 `--port`도 그 경로로 맞추면 된다.

```bash
sudo python -m client.mock_sensor --link /dev/ttyUSB0 --fps 30
# 또는 권한 없이:
python -m client.mock_sensor --link /tmp/ttyUSB0 --fps 30
```

## 실행

```bash
pip install -r requirements.txt

# mock 서버 (테스트용)
pip install -r client/mock_server/requirements.txt
python -m client.mock_server.server --port 5000

# 클라이언트 (실제 하드웨어 또는 mock_sensor가 만든 장치)
python -m client.main --port /dev/ttyUSB0 --server-url http://localhost:5000

# 시리얼 장치 없이 합성 데이터로 테스트 (mock_sensor보다 더 간단, risk 경로 검증용)
python -m client.main --dry-run --server-url http://localhost:5000
```

## 테스트

```bash
pip install -r client/mock_server/requirements.txt  # test_integration.py에 필요
pytest client/tests -v
```

## systemd 배치 예시

`/etc/systemd/system/bliss-client.service`:

```ini
[Unit]
Description=Bliss pressure risk monitoring client
After=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/bliss_recorder
ExecStart=/usr/bin/python3 -m client.main --port /dev/ttyUSB0 --server-url http://SERVER_HOST:8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```
