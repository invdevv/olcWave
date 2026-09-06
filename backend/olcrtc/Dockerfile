FROM golang:1.26 AS builder

RUN apt-get -o Acquire::ForceIPv4=true update && \
    apt-get -o Acquire::ForceIPv4=true install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN go install github.com/magefile/mage@latest
ENV PATH="/go/bin:${PATH}"

WORKDIR /build
RUN git clone --depth=1 https://github.com/openlibrecommunity/olcrtc.git olcrtc
WORKDIR /build/olcrtc
RUN mage build

WORKDIR /build/proxy
COPY proxy.go go.mod go.sum ./
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o /proxy proxy.go

FROM debian:bookworm-slim

RUN apt-get -o Acquire::ForceIPv4=true update && \
    apt-get -o Acquire::ForceIPv4=true install -y --no-install-recommends ca-certificates bash && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /build/olcrtc/build/olcrtc-linux-amd64 ./olcrtc
# The deployment this series comes from replaces the binary above with one
# built from the olcRTC fixes at
#   https://github.com/WhimP990/olcrtc/tree/fixes-and-failover
# The one that matters here is the per-connection record stream: without it
# the srv seals the data and control planes from one counter, and a client
# behind a busy data plane discards control records as replayed-too-old,
# dropping the liveness pongs and the closing notification a rotation depends
# on. Until that fix is in the upstream clone above, place such a build at
# backend/olcrtc/olcrtc-linux-amd64 and uncomment:
# COPY olcrtc-linux-amd64 ./olcrtc
COPY --from=builder /proxy ./proxy
COPY entrypoint.sh .

RUN chmod +x /app/olcrtc /app/proxy /app/entrypoint.sh && \
    mkdir -p /var/lib/olcwave /tmp/olcwave /tmp/olcwave/data

COPY --from=builder /build/olcrtc/internal/names/data /tmp/olcwave/data

ENV PROXY_BIND_ADDR=127.0.0.1
ENV PROXY_PORT=1080
ENV STATS_FILE=/tmp/olcwave/stats.json

ENTRYPOINT ["/app/entrypoint.sh"]
