"""
Campus Eye — FastAPI Application Entry Point
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.utils.logger import setup_logging
from app.routers import faces, events, settings, stream
from app.pipeline.processor import FrameProcessor

logger = logging.getLogger(__name__)
settings_obj = get_settings()

# ── Shared processor instance (singleton) ────────────────────────────────────
processor: FrameProcessor | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    setup_logging()
    logger.info("Campus Eye starting up...")

    # Initialise database (create tables if needed)
    await init_db()
    logger.info("Database initialised.")

    # Start video processing loop in background
    global processor
    processor = FrameProcessor()
    task = asyncio.create_task(processor.run())
    app.state.processor = processor
    app.state.processor_task = task
    logger.info("Frame processor started.")

    yield  # ── application is running ──

    # Shutdown
    logger.info("Shutting down Campus Eye...")
    processor.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Shutdown complete.")


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Campus Eye API",
    version="1.0.0",
    description="Campus CCTV monitoring system — face recognition, behavioral analysis, alerting.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(faces.router,    prefix="/api/faces",    tags=["Faces"])
app.include_router(events.router,   prefix="/api/events",   tags=["Events"])
app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
app.include_router(stream.router,   prefix="",              tags=["Stream"])


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "version": "1.0.0"}


# ── Serve media files (snapshots, clips) ──────────────────────────────────────
import os as _os
_os.makedirs("media", exist_ok=True)
app.mount("/media", StaticFiles(directory="media"), name="media")

# ── Serve frontend static files (catch-all — must be last) ───────────────────
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
