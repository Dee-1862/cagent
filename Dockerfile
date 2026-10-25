# One container serves the whole demo: the live room hub, the ATC console and the pilot app.
# Works on Render, Fly.io, Railway or any Docker host. Keys come from the host's environment.

FROM node:20-slim AS app
WORKDIR /app
COPY app/package.json app/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 \
    # Trust the host's https proxy, so links and QR codes use https (phone mics need it).
    FORWARDED_ALLOW_IPS="*"
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=app /app/dist ./app/dist
EXPOSE 8765
# PORT is set by the host. The hub is live when CARTESIA_API_KEY is set; UNSTEP_OFFLINE=1 forces fake speech and no API calls.
CMD ["sh", "-c", "python -m unstep.live --host 0.0.0.0 --port ${PORT:-8765} --no-browser ${UNSTEP_OFFLINE:+--offline}"]
