#!/bin/bash
# Production launcher for the Customer-API.
#
# Route handlers here are mostly sync `def`, so per-instance concurrency is
# governed by two knobs, both configurable in .env:
#   - WEB_CONCURRENCY  — number of uvicorn worker *processes* (default 1)
#   - THREAD_POOL_SIZE — sync-handler thread pool *within* each process,
#                        applied at startup in main.py (default 40)
# See the "Pre-scale fixes" section of the deployment doc for sizing guidance.

set -e

WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"
HOST="${API_HOST:-0.0.0.0}"
PORT="${API_PORT:-8000}"

echo "Starting Customer-API: ${WEB_CONCURRENCY} worker process(es) on ${HOST}:${PORT}"
exec uvicorn main:app --host "$HOST" --port "$PORT" --workers "$WEB_CONCURRENCY"
