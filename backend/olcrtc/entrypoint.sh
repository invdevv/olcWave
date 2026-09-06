#!/bin/sh
set -eu

: "${CONFIG:?CONFIG env is required}"
: "${PROXY_PORT:=1080}"
: "${PROXY_BIND_ADDR:=127.0.0.1}"
: "${STATS_FILE:=/tmp/olcwave/stats.json}"

mkdir -p /var/lib/olcwave /tmp/olcwave

printf '%s\n' "$CONFIG" > /tmp/olcwave/config.yaml

cat >> /tmp/olcwave/config.yaml <<EOF

socks:
  proxy_addr: "localhost"
  proxy_port: ${PROXY_PORT}
EOF

export LISTEN_ADDR="${PROXY_BIND_ADDR}:${PROXY_PORT}"
export STATS_FILE

if [ -n "${UPSTREAM_SOCKS:-}" ]; then
  export UPSTREAM_SOCKS
fi
if [ -n "${UPSTREAM_USER:-}" ]; then
  export UPSTREAM_USER
fi
if [ -n "${UPSTREAM_PASS:-}" ]; then
  export UPSTREAM_PASS
fi

/app/proxy &
proxy_pid=$!

/app/olcrtc /tmp/olcwave/config.yaml &
olcrtc_pid=$!

# On shutdown (docker stop -> SIGTERM) forward it to olcrtc FIRST so it can
# gracefully leave the Telemost room and send each connected client a "control
# closed by peer" close -> the client fails over to its warm standby INSTANTLY
# instead of hammering the now-dead room. The proxy is stopped on exit.
# (Previously the trap killed only the proxy, so olcrtc never got the signal and
# never sent the close, and the client fell back to the slow liveness path.)
trap 'kill "$proxy_pid" 2>/dev/null || true' EXIT
trap 'kill -TERM "$olcrtc_pid" 2>/dev/null || true' INT TERM

# A trapped signal makes `wait` return while olcrtc is still shutting down; keep
# waiting until it has actually exited so its graceful close gets sent.
while kill -0 "$olcrtc_pid" 2>/dev/null; do
  wait "$olcrtc_pid" || true
done

exit 0