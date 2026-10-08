# TrueBit web API in a container (Render builds this; see render.yaml)
FROM python:3.12-slim

# FFmpeg does the decoding, the loudness measurement and the spectrogram pictures
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Print logs straight away (instead of buffering them), and keep the daily-limit database in /tmp
ENV PYTHONUNBUFFERED=1 \
    TRUEBIT_QUOTA_DB=/tmp/truebit-quota.db

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Render sets $PORT; default to 8000 locally
CMD ["sh", "-c", "uvicorn truebit.api:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
