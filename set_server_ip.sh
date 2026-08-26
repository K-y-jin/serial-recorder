#!/usr/bin/env bash
# Writes SERVER_IP=<ip> into .env so start_client.sh picks it up.
#
# Usage:
#   ./set_server_ip.sh <server-ip>
#
# Example:
#   ./set_server_ip.sh 0.0.0.0
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "usage: $0 <server-ip>" >&2
    exit 1
fi

SERVER_IP="$1"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

touch "$ENV_FILE"

if grep -q '^SERVER_IP=' "$ENV_FILE" 2>/dev/null; then
    sed -i "s/^SERVER_IP=.*/SERVER_IP=${SERVER_IP}/" "$ENV_FILE"
else
    echo "SERVER_IP=${SERVER_IP}" >> "$ENV_FILE"
fi

echo "SERVER_IP set to ${SERVER_IP} in $ENV_FILE"
