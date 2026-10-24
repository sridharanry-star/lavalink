#!/usr/bin/env bash
echo "==================================================="
echo "    Starting Ryuga Lavalink v4 + ML Search Node"
echo "==================================================="

# Check available runtimes for ML Gateway
if command -v node &> /dev/null; then
    echo "[INFO] Node.js detected. Starting Java Lavalink (internal port 4999) + Node.js ML Gateway (public port 4998)..."
    export SERVER_PORT=4999
    java -Xmx2G -XX:+UseG1GC -jar Lavalink.jar &
    LAVALINK_PID=$!
    export LAVALINK_PORT=4999
    export LAVALINK_PROXY_PORT=4998
    sleep 4
    node ml.js
elif command -v python3 &> /dev/null; then
    echo "[INFO] Python 3 detected. Checking ML dependencies..."
    if ! python3 -c "import fastapi, uvicorn, lightgbm" &> /dev/null; then
        echo "[INFO] Installing requirements for ML Gateway..."
        pip3 install --no-cache-dir -r requirements.txt --break-system-packages 2>/dev/null || pip install --no-cache-dir -r requirements.txt 2>/dev/null
    fi
    echo "[INFO] Starting Lavalink ML Gateway..."
    exec python3 lavalink_ml_gateway.py
else
    echo "[INFO] Launching standalone Java Lavalink..."
    exec java -Xmx2G -XX:+UseG1GC -jar Lavalink.jar
fi
