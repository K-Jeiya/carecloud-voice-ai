"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
import html
from fastapi.responses import HTMLResponse, JSONResponse
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

@app.get("/voice-ui", response_class=HTMLResponse, tags=["voice"])
def voice_ui():
    settings = get_settings()

    if not settings.vapi_public_key or not settings.vapi_assistant_id:
        return HTMLResponse(
            "<h2>Voice setup incomplete</h2>"
            "<p>Configure VAPI_PUBLIC_KEY and VAPI_ASSISTANT_ID in .env.</p>",
            status_code=503,
        )

    public_key = html.escape(settings.vapi_public_key, quote=True)
    assistant_id = html.escape(settings.vapi_assistant_id, quote=True)

    page = """
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>CareCloud Voice Registration</title>
      <style>
      h1 { color: #60a5fa !important; }
      p { color: #e5e7eb !important; }
      #status {
        background: #1f2937 !important;
        color: #f9fafb !important;
        border: 1px solid #4b5563;
        border-radius: 8px;
        padding: 12px;
        min-height: 22px;
        box-sizing: border-box;
      }
      button {
        color: #ffffff;
        font-weight: 600;
      }
      #stop {
        background-color: #dc2626 !important;
        color: #ffffff !important;
        border: 1px solid #b91c1c !important;
        font-weight: 700 !important;
        opacity: 1 !important;
      }
      #stop:disabled {
        background-color: #7f1d1d !important;
        color: #ffffff !important;
        opacity: 0.75 !important;
        cursor: not-allowed;
      }
      #stop:not(:disabled):hover {
        background-color: #b91c1c !important;
      }
      button:disabled {
        color: #374151 !important;
        opacity: 0.9 !important;
        cursor: not-allowed;
      }
    </style>


      <style>
        body { font-family: Arial, sans-serif; max-width: 650px;
               margin: 50px auto; padding: 20px; color: #1f2937; }
        button { padding: 12px 18px; margin: 8px 8px 8px 0;
                 border: 0; border-radius: 8px; cursor: pointer; }
        #start { background: #166534; color: white; }
        #stop { background: #e5e7eb; }
        #status { margin-top: 20px; padding: 12px; background: #f3f4f6;
                  border-radius: 8px; }
      </style>
    </head>
    <body>
      <h1>CareCloud Voice Registration</h1>
      <p>This is a demonstration. Use fictional details only.
         Do not share real personal or medical information.</p>
      <button id="start">Start Voice Registration</button>
      <button id="stop" disabled>End Call</button>
      <div id="status" role="status">Ready to start.</div>

      <script type="module">
        import Vapi from "https://esm.sh/@vapi-ai/web";

        const vapi = new Vapi("__PUBLIC_KEY__");
        const assistantId = "__ASSISTANT_ID__";
        const status = document.getElementById("status");
        const start = document.getElementById("start");
        const stop = document.getElementById("stop");

        start.addEventListener("click", async () => {
          start.disabled = true;
          status.textContent = "Connecting to the assistant...";
          try {
            await vapi.start(assistantId);
          } catch (error) {
            status.textContent =
              "Could not start the call. Check microphone permission and Vapi setup.";
            start.disabled = false;
          }
        });

        stop.addEventListener("click", () => vapi.stop());

        vapi.on("call-start", () => {
          status.textContent = "Call connected. You can start speaking.";
          stop.disabled = false;
        });

        vapi.on("call-end", () => {
          status.textContent = "Call ended.";
          start.disabled = false;
          stop.disabled = true;
        });

        vapi.on("error", () => {
          status.textContent =
            "Voice error. Check browser microphone permission and Vapi configuration.";
          start.disabled = false;
          stop.disabled = true;
        });
      </script>
    </body>
    </html>
    """

    page = page.replace("__PUBLIC_KEY__", public_key)
    page = page.replace("__ASSISTANT_ID__", assistant_id)
    return HTMLResponse(page)