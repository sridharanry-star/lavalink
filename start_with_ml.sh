#!/usr/bin/env bash
echo "==================================================="
echo "    Starting Ryuga Lavalink v4 + ML Search Gateway"
echo "==================================================="

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 could not be found. Please install Python 3.10+."
    exit 1
fi

python3 lavalink_ml_gateway.py
