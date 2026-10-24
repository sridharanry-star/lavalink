#!/usr/bin/env bash
echo "==================================================="
echo "    Starting Ryuga Lavalink v4 + ML Search Node"
echo "==================================================="

# If Python 3 is available in the container/server, launch ML Gateway
if command -v python3 &> /dev/null; then
    echo "[INFO] Python 3 detected. Checking ML dependencies..."
    if ! python3 -c "import fastapi, uvicorn, lightgbm" &> /dev/null; then
        echo "[INFO] Installing requirements for ML Gateway..."
        pip3 install --no-cache-dir -r requirements.txt --break-system-packages 2>/dev/null || pip install --no-cache-dir -r requirements.txt 2>/dev/null
    fi
    echo "[INFO] Starting Lavalink ML Gateway..."
    exec python3 lavalink_ml_gateway.py
else
    echo "[INFO] Python 3 not detected in container. Launching standalone Java Lavalink..."
    exec java -Xmx2G -XX:+UseG1GC -jar Lavalink.jar
fi
