"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.database import SessionLocal, engine, init_db
from app.errors import AppError
from app.logging_utils import configure_logging
from app.routers import patients, voice

configure_logging()
logger = logging.getLogger("carecloud.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if get_settings().seed_demo_data:
        from app.seed import seed_demo_data

        with SessionLocal() as db:
            seed_demo_data(db)
    logger.info("API started")
    yield


app = FastAPI(
    title="CareCloud Voice AI - Patient Registration API",
    description="Demo system with synthetic data only. NOT a production healthcare system.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(patients.router)
app.include_router(voice.router)


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"data": None, "error": {"code": code, "message": message, "details": details}},
    )


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return _error(exc.status_code, exc.code, exc.message, exc.details)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    errors = exc.errors()
    if any(e.get("type") == "json_invalid" for e in errors):
        return _error(400, "malformed_json", "Request body is not valid JSON")
    details = []
    for e in errors:
        loc = [str(p) for p in e.get("loc", []) if p not in ("body", "query", "path")]
        msg = str(e.get("msg", "invalid value")).removeprefix("Value error, ")
        details.append({"field": ".".join(loc) or "request", "message": msg})
    summary = "; ".join(f"{d['field']}: {d['message']}" for d in details)
    return _error(422, "validation_error", f"Validation failed - {summary}", details)


@app.exception_handler(Exception)
async def unhandled_handler(_: Request, exc: Exception):
    logger.exception("Unhandled error")  # stack trace goes to logs only, never to the client
    return _error(500, "internal_error", "An unexpected error occurred")


@app.get("/health", tags=["health"], summary="Liveness + database check")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"data": {"status": "ok", "database": "ok"}, "error": None}
    except Exception:
        logger.exception("Health check failed")
        return _error(503, "unhealthy", "Database unavailable")
