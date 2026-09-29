# Customer-API — FastAPI backend
#
# python-magic needs libmagic1 at runtime; easyocr/torch/opencv (pulled in
# transitively) need a few common shared libs to import at all on a slim
# base, even running headless/CPU-only. Installed once here rather than
# left to fail on first request.
FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# torch/torchvision default to CUDA wheels (multiple GB) unless told
# otherwise — this is a web API container, not a GPU training box, so pin
# the CPU-only index first and let pip fall through to PyPI for everything
# else in requirements.txt.
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

COPY . .

# .env is deliberately NOT copied into the image (see .dockerignore) — it
# holds real DB/SMTP credentials. Supply config at run time instead, e.g.
# `docker run --env-file .env ...` or docker-compose's env_file:, so the
# same image can move between environments without secrets baked in.

EXPOSE 8000

# --workers stays at 1: this app runs its own in-process APScheduler
# (main.py's startup_event) and multiple uvicorn workers would each start
# their own copy, duplicating every cron/interval job. Scale by running
# more *containers* behind a load balancer instead, with ENABLE_SCHEDULER=
# false on all but one (see docker-compose.yml).
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
