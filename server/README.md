# server — 압력 위험도 모니터링 서버 + 대시보드

`client/`가 통신하는 실제 서버. `client/mock_server`와 동일한 REST 계약을 구현하고
(테스트용 mock은 그대로 `client/mock_server`에 남아있음), 위험 경고를 시각화하는
대시보드를 제공한다.

## 엔드포인트

- `GET/PUT /config` — `calibration_factor`, `critical_pressure`, `critical_time`, `cols`, `rows`
- `POST /event` — client의 risk warning: `{"accumulated_time", "risky_idx", "pressure_mask_idx"}`
- `GET/PUT /command` — `start`/`pause`/`stop`/`reset`/`state` 명령 큐 (한 번 소비되면 비워짐)
- `POST /state` — client의 `state` 명령 응답: `{"timestamp", "pressure"}` (전체 압력 벡터)
- `GET /dashboard` — 대시보드 HTML
- `GET /api/latest` — 대시보드 폴링용 JSON (`risky_idx`/`pressure_mask_idx`를 `[row, col]`
  2D 좌표로 변환해서 내려줌 — `server/grid.py:idx_to_rowcol()`, `row = idx // cols`)

## 대시보드

`GET /dashboard`를 브라우저로 열면 1.5초 간격으로 `/api/latest`를 폴링해 매트리스
그리드를 `<canvas>`에 그린다:

- 압력이 실린 영역(`pressure_mask_idx`, 또는 `POST /state`로 받은 전체 압력값이 있으면
  그레이스케일로 그 값을 그대로 사용)을 실루엣처럼 배경으로 표시
- `risky_idx`(critical_time을 넘긴 셀)를 빨간색으로 강조
- 최근 이벤트가 없으면 "정상" 상태 표시

## 실행

```bash
pip install -r server/requirements.txt
python -m server.app --port 8000 --cols 32 --rows 64
```

client를 이 서버로 연결:

```bash
python -m client.main --dry-run --server-url http://localhost:8000
```

브라우저에서 `http://localhost:8000/dashboard` 확인.

## 테스트

```bash
pytest server/tests -v
```
