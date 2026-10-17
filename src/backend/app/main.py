import json
import logging
import re
import time
from uuid import uuid4

from fastapi import FastAPI, Request

from app.api.v1.router import api_router


def create_app() -> FastAPI:
    app = FastAPI(title="Software Cup A3 Learning Backend")

    @app.middleware("http")
    async def record_request_performance(request: Request, call_next):
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request_id = supplied_request_id if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", supplied_request_id) else uuid4().hex
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = max(0, round((time.perf_counter() - started) * 1000))
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(duration_ms)
        response.headers["Server-Timing"] = f"app;dur={duration_ms}"
        logging.getLogger("app.performance").info(
            json.dumps(
                {
                    "event": "api_request_completed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
                separators=(",", ":"),
            )
        )
        return response

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
