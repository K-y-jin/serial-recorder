# Sensor Recorder

매트리스 압력 센서의 데이터를 시리얼 포트로 수신하여 실시간 colormap으로 표시하고 CSV로 저장하는 경량 GUI 프로그램.

## Features

- 시리얼 포트 자동 탐지 + 새로고침, 자동 재연결
- 실시간 2D colormap 디스플레이 (viridis / gray / jet / inferno / magma)
- 프레임 단위 CSV 저장 (한 행 = 한 프레임, ISO 타임스탬프 포함)
- Calibration (현재 프레임을 baseline으로 차감)
- 디스플레이 90° 단위 회전 (CW / CCW)
- 다크 테마 Tk GUI

## Requirements

- Python 3.10+
- Tkinter (`sudo apt install python3-tk` on Debian/Ubuntu)
- 시리얼 포트 접근 권한: `sudo usermod -aG dialout $USER` 후 재로그인

## Install & Run

```bash
git clone <repo-url> sensor_recorder
cd sensor_recorder
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Packet Format

기본 패킷 레이아웃 (GUI에서 모두 변경 가능):

```
offset  size   field
0       2      HEADER    (A5 5A)
2       6      PRE_SKIP
8       N      PAYLOAD   (cols × rows bytes, 8-bit unsigned, row-major)
8+N     2      POST_SKIP
```

기본값: `cols=64, rows=32, baud=921600`.

## Controls

| 버튼                          | 동작                                           |
| ----------------------------- | ---------------------------------------------- |
| Connect / Disconnect          | 시리얼 연결 토글 (연결만으로 실시간 표시 동작) |
| Start / Stop Recording        | CSV 기록 토글                                  |
| Calibrate / Reset Calibration | 현재 프레임을 baseline으로 저장 / 해제         |
| ↺ CCW / ↻ CW                  | 디스플레이 90° 회전 (CSV에는 영향 없음)        |
| Refresh                       | 시리얼 포트 목록 갱신                          |

## CSV Format

```
timestamp,               c0, c1, c2, ..., c{rows*cols-1}
2026-04-13T14:23:45.123, 0,  5,  12, ..., 0
```

- 한 행 = 한 프레임 (row-major flatten)
- Calibration 활성 시 보정값이 저장됨

## Build standalone executable

```bash
pip install pyinstaller
pyinstaller SensorRecorder.spec --clean --noconfirm
./dist/SensorRecorder/SensorRecorder
```

배포 시 `dist/SensorRecorder/` 폴더 전체를 압축해 전달.
**PyInstaller는 크로스-아키텍처 빌드를 지원하지 않으므로 타겟 머신과 같은 OS/아키텍처에서 빌드해야 합니다** (예: Jetson Orin(aarch64)용은 Jetson에서 빌드).

## Project Structure

```
sensor_recorder/
├── main.py
├── sensor/
│   ├── config.py          # 기본값 상수
│   ├── serial_reader.py   # 시리얼 스레드 + 자동 재연결
│   ├── frame_parser.py    # 헤더 동기화, 프레임 추출
│   ├── csv_logger.py      # CSV 저장
│   ├── colormap_view.py   # matplotlib 디스플레이
│   └── app.py             # Tk GUI
├── tests/
│   └── test_frame_parser.py
├── SensorRecorder.spec     # PyInstaller
├── DESIGN.md              # 설계 문서
└── requirements.txt
```

## Tests

```bash
pip install pytest
python -m pytest tests/
```

## License

TBD
