#!/bin/sh
set -eu

export DISPLAY=:99

# An ungraceful kill leaves a stale X lock that makes Xvfb :99 refuse to start
# on the next run; clear it (and any leftover socket) first.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true

# Continuous, lightweight: virtual display + VNC mirror + noVNC bridge.
Xvfb :99 -screen 0 1280x900x24 -nolisten tcp -ac >/tmp/xvfb.log 2>&1 &
sleep 1
x11vnc -display :99 -forever -shared -nopw -localhost -rfbport 5900 -bg -o /tmp/x11vnc.log
websockify --web=/usr/share/novnc 6080 localhost:5900 >/tmp/websockify.log 2>&1 &
sleep 1

echo "[entrypoint] Xvfb :99 + x11vnc(5900,localhost) + websockify(6080) up; starting vault"
exec node /app/vault.js
