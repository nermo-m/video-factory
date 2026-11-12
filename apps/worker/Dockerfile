# syntax=docker/dockerfile:1
# Build from the repository root: docker build -f apps/worker/Dockerfile .

FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
# Two programs the worker starts as separate processes, never imports as libraries:
# espeak-ng turns narration text into phonemes for the Kokoro voice (GPL-3.0), and FFmpeg
# encodes video and measures audio (GPL in Debian's build, which includes x264).
RUN apt-get update     && apt-get install --yes --no-install-recommends "espeak-ng=1.51*" "ffmpeg=7:5.1*"     && rm -rf /var/lib/apt/lists/*
WORKDIR /app

FROM base AS deps
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --only-group worker

# Test image for the golden-frame tests: the same Python, Pillow and fonts as the worker,
# plus the test tools. The repository is mounted at /src when it runs (make render-test).
FROM deps AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked
WORKDIR /src
# The voice tests (make voice-test) find the model files in the mounted models volume.
ENV PYTHONPATH=/src \
    KOKORO_MODEL_PATH=/models/kokoro/kokoro.onnx \
    KOKORO_VOICES_PATH=/models/kokoro/voices.bin
CMD ["python", "-m", "pytest", "-m", "render", "-p", "no:cacheprovider"]

FROM base AS runtime
RUN useradd --system --uid 10001 --create-home app \
    && mkdir -p /data /models \
    && chown app:app /data /models
COPY --from=deps /opt/venv /opt/venv
COPY apps/__init__.py apps/__init__.py
COPY apps/worker apps/worker
COPY packages packages
COPY schemas schemas
# The sample episode: its spec, pictures and recorded narration (demo mode, FR-16).
COPY samples samples
# `make models` runs this inside the container to fill the models volume.
COPY scripts/__init__.py scripts/download_models.py scripts/
USER app
CMD ["python", "-m", "apps.worker"]
