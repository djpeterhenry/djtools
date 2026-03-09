#!/bin/bash
cd "$(dirname "$0")"

# Kill any existing process on port 8888
PID=$(lsof -ti :8888)
if [ -n "$PID" ]; then
    echo "Stopping previous server (PID $PID)..."
    kill $PID
    sleep 1
fi

echo "Starting History Server on http://localhost:8888 ..."
echo "Close this window to stop the server."
echo ""
python3.11 history_server.py
