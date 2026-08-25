#!/usr/bin/env bash
# Starts client/main.py in the background and detaches it from the
# terminal. Logs to logs/client.log, PID recorded in run/client.pid so
# stop_client.sh (or `kill $(cat run/client.pid)`) can stop it later.
#
# Usage:
#   ./start_client.sh [args passed through to python -m client.main]
#
# Examples:
#   ./start_client.sh --dry-run --server-url http://localhost:5000
#   ./start_client.sh --port /dev/ttyUSB0 --server-url http://localhost:5000
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RUN_DIR="$SCRIPT_DIR/run"
LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$RUN_DIR/client.pid"
LOG_FILE="$LOG_DIR/client.log"

mkdir -p "$RUN_DIR" "$LOG_DIR"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "client already running (PID $(cat "$PID_FILE"))" >&2
    exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"

nohup "$PYTHON_BIN" -m client.main "$@" >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
disown

echo "client started in background (PID $(cat "$PID_FILE")), logging to $LOG_FILE"
