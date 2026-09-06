# olcWave auth-token vault sidecar: Playwright/Chromium + Xvfb + x11vnc + noVNC.
FROM mcr.microsoft.com/playwright:v1.62.1-jammy

ENV DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC

RUN apt-get update \
  && apt-get install -y --no-install-recommends xvfb x11vnc websockify novnc \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json .
RUN npm install --omit=dev

COPY vault.js entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh

ENV DISPLAY=:99
VOLUME /data
EXPOSE 6080 8091

CMD ["/app/entrypoint.sh"]
