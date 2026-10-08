# TrueBit web API in a container (for Render, Railway, Fly...)
FROM python:3.12-slim

# FFmpeg does the decoding and loudness measurement
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Render sets $PORT; default to 8000 locally
CMD ["sh", "-c", "uvicorn truebit.api:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
