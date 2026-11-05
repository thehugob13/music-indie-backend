FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080 MEDIA_DATA_DIR=/data/media
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg gosu ca-certificates && rm -rf /var/lib/apt/lists/* && useradd --uid 10001 --create-home app
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=proxy_ca if [ -f /run/secrets/proxy_ca ]; then PIP_CERT=/run/secrets/proxy_ca pip install --no-cache-dir -r requirements.txt; else pip install --no-cache-dir -r requirements.txt; fi
COPY app.py archive_source.py entrypoint.sh ./
RUN chmod 755 /app/entrypoint.sh
EXPOSE 8080
ENTRYPOINT ["/app/entrypoint.sh"]
