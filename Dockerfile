# Python image: API and worker share one source tree. AAB_ROLE selects the process.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AAB_HOME=/data \
    AAB_DATABASE_URL=sqlite:////data/aab.db \
    AAB_MEDIA_DIR=/data/media \
    AAB_MODELS_DIR=/data/models

WORKDIR /app

# ffmpeg enables AAC chapter masters and ffprobe durations; the stdlib fallback still works
# without it. curl is used by scripts/setup_tts.sh in the optional `models` Compose service.
RUN apt-get update \
 && apt-get install -y --no-install-recommends bash ca-certificates curl ffmpeg \
 && rm -rf /var/lib/apt/lists/*

COPY . /app

# dev is the lean default (fake speech still exercises the whole pipeline). Build with
# --build-arg AAB_PY_EXTRAS=kokoro,dev to bake real local TTS into the image.
ARG AAB_PY_EXTRAS=dev
RUN pip install --no-cache-dir -e "python[${AAB_PY_EXTRAS}]"

# Preserve the executable bit even when the source tree was checked out without it.
RUN chmod +x /app/scripts/docker-entrypoint.sh /app/scripts/setup_tts.sh \
 && useradd --uid 10001 --create-home --shell /bin/bash aab \
 && mkdir -p /data \
 && chown -R aab:aab /data /app

USER aab
EXPOSE 8000

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
