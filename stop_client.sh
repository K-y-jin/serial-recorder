#!/usr/bin/env bash
# Stops the client started by start_client.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/run/client.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "no PID file at $PID_FILE -- client not running (or not started via start_client.sh)" >&2
    exit 1
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "sent SIGTERM to client (PID $PID)"
else
    echo "client (PID $PID) not running" >&2
fi

rm -f "$PID_FILE"
