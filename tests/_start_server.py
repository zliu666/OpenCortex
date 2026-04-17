#!/usr/bin/env python3
"""Start server in-thread, run health check, then launch stability tests."""
import uvicorn, threading, time, json, urllib.request, sys, subprocess

def run_server():
    uvicorn.run("opencortex.api_server.app:app", host="127.0.0.1", port=18905, log_level="warning")

t = threading.Thread(target=run_server, daemon=True)
t.start()
time.sleep(5)

# Quick health check
try:
    r = urllib.request.urlopen("http://127.0.0.1:18905/health")
    h = json.loads(r.read())
    status = h.get("status", "?")
    model = h.get("model", "?")
    sessions = h.get("active_sessions", 0)
    print(f"Server OK: status={status} model={model} sessions={sessions}")
except Exception as e:
    print(f"Server FAIL: {e}")
    sys.exit(1)
