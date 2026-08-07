"""Health-check endpoint for external load-test monitoring - polled
repeatedly during a live JMeter run (see AITool's live_perf.run_live_test /
HEALTH_CHECK_URL) to capture real server-side CPU/memory/DB-pool data
alongside JMeter results, instead of the "No monitoring/APM data
available." placeholder every prior run had to fall back on.

No authentication required - registered in main.py's PUBLIC_ENDPOINTS so a
load-testing tool can poll it without a login token or session.
"""

import time

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_vendor_db, vendor_engine

try:
    import psutil

    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False

router = APIRouter(prefix="/health", tags=["Health"])

_START_TIME = time.time()


@router.get("")
def health_check(db: Session = Depends(get_vendor_db)):
    """Real-time server health snapshot: CPU/memory (if psutil is
    installed), DB connection pool stats, and a live DB round-trip check.

    Always returns 200 - even when the DB check fails, the response body
    reports database.status="error" with the real exception message rather
    than the endpoint itself raising a 5xx, so a monitoring poller always
    gets a JSON body to record instead of needing separate error-response
    handling just for a health check.
    """
    db_status = "ok"
    db_error = None
    db_latency_ms = None
    try:
        start = time.time()
        db.execute(text("SELECT 1"))
        db_latency_ms = round((time.time() - start) * 1000, 2)
    except Exception as exc:
        db_status = "error"
        db_error = str(exc)

    pool = vendor_engine.pool
    result = {
        "status": "ok",
        "uptime_sec": round(time.time() - _START_TIME, 1),
        "database": {
            "status": db_status,
            "error": db_error,
            "latency_ms": db_latency_ms,
            "pool_size": pool.size(),
            "pool_checked_in": pool.checkedin(),
            "pool_checked_out": pool.checkedout(),
            "pool_overflow": pool.overflow(),
        },
    }

    if _PSUTIL_AVAILABLE:
        memory = psutil.virtual_memory()
        result["system"] = {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": memory.percent,
            "memory_used_mb": round(memory.used / (1024 * 1024), 1),
            "memory_available_mb": round(memory.available / (1024 * 1024), 1),
        }

    return result
