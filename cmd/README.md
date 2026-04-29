# Sensor Recorder — CLI (`cmd/start.py`)

GUI 없이 터미널에서 바로 녹화하는 헤드리스 레코더.

## 실행

프로젝트 루트에서:

```bash
python cmd/start.py
```

기본 동작:

- 포트: `/dev/ttyUSB0`
- 저장 경로: `~/sensor_logs/sensor_YYYYMMDD_HHMMSS.csv`
- 주기: 1초 (1 Hz)
- 통신 설정: GUI 기본값과 동일 (`baud=921600, cols=32, rows=64, header=A55A, pre=6, post=2`)
- 실행 즉시 녹화 시작, `Ctrl+C`로 중단

포트가 없으면 `FileNotFoundError`로 즉시 중단됩니다.

## 옵션

| 인자                | 기본값            | 설명                                                                              |
| ------------------- | ----------------- | --------------------------------------------------------------------------------- |
| `--port`            | `/dev/ttyUSB0`    | 시리얼 포트                                                                       |
| `--baud`            | `921600`          | 보드레이트                                                                        |
| `--cols`            | `32`              | 매트리스 열 수                                                                    |
| `--rows`            | `64`              | 매트리스 행 수                                                                    |
| `--header`          | `A55A`            | 프레임 헤더 (hex)                                                                 |
| `--pre`             | `6`               | 헤더 뒤 skip 바이트                                                               |
| `--post`            | `2`               | 페이로드 뒤 skip 바이트                                                           |
| `--interval`        | `1.0`             | 저장 주기 (초, `0` = 모든 프레임)                                                 |
| `--outpath`         | 자동              | 저장 파일명/경로                                                                  |
| `--upload`          | off               | wandb로 실시간 메트릭 스트리밍 + CSV 아티팩트 주기 업로드 (업로드 시 파일 rotate) |
| `--upload-interval` | `86400`           | 업로드 주기(초, 기본 1일) — 이 주기마다 현재 CSV를 업로드하고 새 파일로 이어 쓰기 |
| `--wandb-project`   | `sensor-recorder` | wandb 프로젝트 이름                                                               |
| `--wandb-entity`    | 계정 기본         | wandb entity (user/team)                                                          |
| `--wandb-run-name`  | 자동              | wandb run 이름                                                                    |
| `--dry-run`         | off               | 시리얼 대신 합성 프레임 생성 (장비 없이 CSV/wandb 동작 검증)                      |
| `--dry-fps`         | `30`              | 합성 프레임 레이트                                                                |

기본 저장 디렉토리는 **`~/sensor_logs/`** 입니다 (예: `~/sensor_logs/sensor_<timestamp>.csv`).

## `--outpath` 규칙

- **미지정**: `~/sensor_logs/sensor_<timestamp>.csv`
- **파일명만**: `~/sensor_logs/<이름>.csv` (상대경로는 기본 디렉토리 기준)
- **절대경로**: 그대로 사용
- **확장자 없음**: 자동으로 `.csv` 추가
- **`~`**: 홈 디렉토리로 확장
- 부모 디렉토리는 자동 생성

## 예시

```bash
# 기본 실행
python cmd/start.py

# 포트 변경
python cmd/start.py --port /dev/ttyUSB1

# 파일명 지정 (확장자 자동)
python cmd/start.py --outpath test_run_01
# → ~/sensor_logs/test_run_01.csv

# 주기 500 ms
python cmd/start.py --interval 0.5

# 절대경로
python cmd/start.py --outpath /tmp/sensor/run1.csv

# 모든 프레임 저장 (주기 0)
python cmd/start.py --interval 0

# 해상도/헤더 변경
python cmd/start.py --cols 64 --rows 32 --header A55A --pre 6 --post 2

# wandb로 업로드 (실시간 메트릭 + 10분마다 CSV 아티팩트)
python cmd/start.py --upload --wandb-project sensor-recorder --wandb-run-name bed01

# 다른 entity (팀 계정)
python cmd/start.py --upload --wandb-entity myteam --wandb-project sensor

# 장비 없이 합성 프레임으로 동작 점검
python cmd/start.py --dry-run --interval 0.1 --outpath dryrun_test
```

### Dry-run / 테스트

`--dry-run` 옵션은 시리얼 포트를 열지 않고 사인파 패턴의 합성 프레임을 생성합니다. CSV 저장, rotate, wandb 업로드, wifi 단절 회복력 등을 **장비 없이** 검증할 때 사용:

```bash
# CSV 저장만 검증 (1분간 합성 프레임)
python cmd/start.py --dry-run

# wandb 업로드 흐름 점검 (3초마다 rotate + 업로드)
python cmd/start.py --dry-run --upload --upload-interval 3

# 자동 회귀 테스트
python -m pytest tests/test_dry_run.py -v
```

`tests/test_dry_run.py`는 다음을 자동으로 검증합니다:

- dry-run subprocess가 실제로 CSV에 row를 기록함
- `Recorder.rotate()`가 `(2)`, `(3)` 접미사로 파일을 이어 만들고 기존 파일과 충돌 시 다음 번호로 skip
- `wandb.init` 실패 후 재시도 성공
- artifact 업로드가 실패하면 큐에 쌓이고, 네트워크가 돌아오면 큐가 비워짐
- `wandb.log` 실패가 녹화를 망가뜨리지 않음
- 종료 시 끝까지 못 올린 파일 경로가 콘솔에 출력됨

### `--upload` (wandb) 사용 조건

1. **wandb 설치 및 로그인**:
   ```bash
   pip install wandb
   wandb login   # API key 한 번 입력
   ```
2. 동작:
   - `wandb.init(project=..., config={port, baud, cols, rows, ...})`로 run 시작
   - 매 저장된 프레임마다 **스칼라 메트릭 `min / max / mean / saved_count`** 를 `wandb.log`로 스트리밍 → 대시보드에서 실시간 그래프로 확인
   - `--upload-interval`초(기본 86400 = 1일)마다:
     1. 현재 CSV 파일을 close
     2. **Artifact로 업로드** (버전링, 여러 day가 같은 artifact name의 버전으로 누적됨)
     3. 파일명을 `<base> (2).csv`, `<base> (3).csv`, ... 로 **자동 rotate**하여 새 파일에 이어서 녹화
   - Ctrl+C 종료 시 현재 진행 중인 CSV를 `final` 태그로 한 번 더 업로드 후 `run.finish()`
3. **네트워크 회복력 (wifi 단절 대응)**:
   - `wandb.init` 실패 시 백그라운드에서 30초 간격으로 자동 재시도 — 네트워크가 돌아올 때까지 계속
   - `wandb.log` 실패는 무시 (wandb SDK가 내부적으로 재전송)
   - **artifact 업로드 실패 시 메모리 큐에 보관** → 다음 인터벌과 종료 시점에 재시도
   - 종료 시까지 실패한 파일은 디스크에 그대로 남고 콘솔에 경로 출력 → 나중에 `wandb artifact put`로 수동 업로드 가능
4. CSV 저장은 wandb 상태와 독립적으로 동작 — 인터넷이 끊겨도 녹화는 멈추지 않습니다.
5. wandb 오프라인 모드가 필요하면 `WANDB_MODE=offline python cmd/start.py --upload ...`

## 출력 예

```
[rec] writing to /home/nrc/sensor_logs/sensor_20260414_152030.csv
[cfg] port=/dev/ttyUSB0 baud=921600 cols=32 rows=64 header=A55A pre=6 post=2 interval=1.0s
[serial] Connecting to /dev/ttyUSB0...
[serial] Connected to /dev/ttyUSB0
[rec] recording... press Ctrl+C to stop
[15:20:31] saved #1  min=  3  max=187  mean= 42.18  (fps≈28)
[15:20:32] saved #2  min=  2  max=192  mean= 43.01  (fps≈30)
...
^C
[rec] stopped. saved 127 frames -> /home/nrc/sensor_logs/sensor_20260414_152030.csv
```

- `min/max/mean`: 저장된 프레임의 셀 값 통계 — 센서 작동 확인용
- `fps≈`: 직전 주기 동안 수신된 프레임 수 (저장되지 않은 프레임 포함)

## 중단

`Ctrl+C` 또는 `kill <pid>` — 시리얼 스레드 정상 종료 후 CSV close 및 최종 저장 수 출력.

---

# CSV Player (`cmd/display.py`)

저장된 CSV를 애니메이션으로 재생.

## 실행

```bash
python cmd/display.py <csv_path> [--rows 64] [--cols 32]
                                 [--cmap jet] [--fps 0]
                                 [--loop] [--rotate 0]
```

## 옵션

| 인자       | 기본값 | 설명                                 |
| ---------- | ------ | ------------------------------------ |
| `csv_path` | —      | 재생할 CSV 경로 (필수)               |
| `--rows`   | `64`   | 행 수 (기록 시 값과 동일해야 함)     |
| `--cols`   | `32`   | 열 수                                |
| `--cmap`   | `jet`  | matplotlib colormap                  |
| `--fps`    | `0`    | 재생 속도 (0 = 녹화 타임스탬프 사용) |
| `--loop`   | off    | 반복 재생                            |
| `--rotate` | `0`    | 90° CCW 회전 횟수 (0–3)              |

## 예시

```bash
# 녹화 속도 그대로 재생
python cmd/display.py ~/sensor_logs/sensor_20260414_152030.csv

# 10 Hz로 빠르게, 반복
python cmd/display.py run1.csv --fps 10 --loop

# grayscale + 회전
python cmd/display.py run1.csv --cmap gray --rotate 1
```

타이틀에 프레임 번호, 타임스탬프, min/max/mean이 표시됩니다.

---

# Calibration (`cmd/calibration.py`)

센서 baseline을 측정하여 CSV로 저장. N 프레임 평균값을 baseline으로 사용.

## 실행

```bash
python cmd/calibration.py [--samples 10] [--port /dev/ttyUSB0] [--outpath name]
```

## 옵션

| 인자                                                        | 기본값         | 설명                                     |
| ----------------------------------------------------------- | -------------- | ---------------------------------------- |
| `--port`                                                    | `/dev/ttyUSB0` | 시리얼 포트                              |
| `--samples`                                                 | `10`           | 평균 낼 프레임 수                        |
| `--timeout`                                                 | `10.0`         | 프레임 수신 최대 대기 시간 (초)          |
| `--outpath`                                                 | 자동           | `~/sensor_logs/baseline_<timestamp>.csv` |
| `--baud`, `--cols`, `--rows`, `--header`, `--pre`, `--post` | GUI 기본값     |                                          |

## 예시

```bash
# 10 프레임 평균으로 baseline 저장
python cmd/calibration.py

# 30 프레임 평균, 파일명 지정
python cmd/calibration.py --samples 30 --outpath bed_empty
# → ~/sensor_logs/bed_empty.csv

# 다른 포트
python cmd/calibration.py --port /dev/ttyUSB1
```

출력 예:

```
[cal] target: 10 frames averaged
[cfg] port=/dev/ttyUSB0 baud=921600 cols=32 rows=64
[serial] Connected to /dev/ttyUSB0
  captured 1/10  min=2 max=35 mean=12.34
  captured 2/10  min=2 max=34 mean=12.28
  ...
[cal] averaged 10 frames  min=2 max=34 mean=12.31
[cal] baseline saved -> /home/nrc/sensor_logs/baseline_20260414_153045.csv
```

저장 형식은 1프레임짜리 CSV (start.py의 CSV와 동일 포맷) 이므로 `display.py`로 열거나 후속 분석 스크립트에서 차감에 사용할 수 있습니다.
