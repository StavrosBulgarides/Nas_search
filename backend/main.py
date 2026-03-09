from __future__ import annotations

import logging
import logging.handlers
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from backend.config import get_config, load_config, save_config, DB_PATH
from backend.database import init_db, get_db, get_file_count, get_last_index_log
from backend.database import get_distinct_folders, get_distinct_extensions
from backend.database import get_recent_files, increment_folder_usage
from backend.indexer import run_index, is_indexing
from backend.search import search_files
from backend.scheduler import start_scheduler, stop_scheduler
from backend.models import SearchResponse, IndexStatus, TrackClick
from backend.stream import router as stream_router


def setup_logging():
    """Configure logging to both console and rotating file."""
    log_dir = Path(os.environ.get("LOG_DIR", "/app/data"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "nas_search.log"

    # Root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Console handler — INFO and above
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # File handler — DEBUG and above, rotating at 5MB, keep 3 backups
    file_handler = logging.handlers.RotatingFileHandler(
        str(log_file), maxBytes=5 * 1024 * 1024, backupCount=3,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s [%(threadName)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root.addHandler(console)
    root.addHandler(file_handler)

    # Quieten noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)


setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== Search Wizard starting ===")
    logger.info("DB path: %s", DB_PATH)

    cfg = load_config()
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    init_db()
    start_scheduler()

    logger.info("=== Search Wizard ready ===")
    yield
    logger.info("=== Search Wizard shutting down ===")
    stop_scheduler()


app = FastAPI(title="Search Wizard", lifespan=lifespan)
app.include_router(stream_router)


# ── Request logging middleware ──

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
    except Exception:
        elapsed = (time.time() - start) * 1000
        logger.exception(
            "Request failed: %s %s (%.1fms)",
            request.method, request.url.path, elapsed,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
    elapsed = (time.time() - start) * 1000

    # Log API requests (skip static file requests to reduce noise)
    path = request.url.path
    if path.startswith("/api/"):
        log_level = logging.WARNING if response.status_code >= 400 else logging.DEBUG
        logger.log(
            log_level,
            "%s %s -> %d (%.1fms)",
            request.method, path, response.status_code, elapsed,
        )

    return response


# Serve frontend static files
frontend_dir = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(frontend_dir / "index.html"))


@app.get("/player")
async def player():
    return FileResponse(str(frontend_dir / "player.html"))


@app.get("/api/search")
async def api_search(
    q: str = Query("", description="Search query"),
    folder: Optional[str] = Query(None, description="Filter by folder path"),
    extension: Optional[str] = Query(None, description="Filter by extension"),
    fuzzy: bool = Query(False, description="Enable fuzzy search"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> SearchResponse:
    results, total = search_files(q, folder, extension, fuzzy, limit, offset)
    return SearchResponse(results=results, total=total, query=q, fuzzy=fuzzy)


@app.post("/api/index")
async def api_index(full: bool = Query(False)):
    if is_indexing():
        logger.info("Index request rejected: already in progress")
        return {"status": "already_running"}
    scan_type = "full" if full else "incremental"
    logger.info("Manual index triggered: %s scan", scan_type)
    thread = threading.Thread(target=run_index, args=(full,), daemon=True, name="indexer")
    thread.start()
    return {"status": "started", "full_scan": full}


@app.get("/api/status")
async def api_status() -> IndexStatus:
    try:
        with get_db() as conn:
            count = get_file_count(conn)
            last_log = get_last_index_log(conn)
    except Exception:
        logger.exception("Failed to fetch status")
        return IndexStatus(
            total_files=0, last_index_time=None,
            last_index_duration=None, indexing_in_progress=is_indexing(),
        )

    last_time = None
    last_duration = None
    if last_log:
        last_time = datetime.fromtimestamp(last_log["finished_at"]).isoformat()
        last_duration = last_log["duration"]

    return IndexStatus(
        total_files=count,
        last_index_time=last_time,
        last_index_duration=last_duration,
        indexing_in_progress=is_indexing(),
    )


@app.get("/api/folders")
async def api_folders():
    try:
        cfg = get_config()
        indexed_folders = cfg.get("indexed_folders", {})
        # Return just the top-level configured folders
        folders = [{"label": label, "path": path} for label, path in indexed_folders.items()]
        return {"folders": folders}
    except Exception:
        logger.exception("Failed to fetch folders")
        return {"folders": []}


@app.get("/api/extensions")
async def api_extensions():
    try:
        with get_db() as conn:
            extensions = get_distinct_extensions(conn)
        return {"extensions": extensions}
    except Exception:
        logger.exception("Failed to fetch extensions")
        return {"extensions": []}


@app.get("/api/recent")
async def api_recent(limit: int = Query(10, ge=1, le=50)):
    try:
        with get_db() as conn:
            files = get_recent_files(conn, limit)
        return {"files": files}
    except Exception:
        logger.exception("Failed to fetch recent files")
        return {"files": []}


@app.post("/api/track-click")
async def api_track_click(data: TrackClick):
    try:
        with get_db() as conn:
            increment_folder_usage(conn, data.folder_path)
        logger.debug("Click tracked: %s", data.folder_path)
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to track click for '%s'", data.folder_path)
        return {"status": "error"}


@app.get("/api/config")
async def api_get_config():
    try:
        cfg = get_config()
        return cfg
    except Exception:
        logger.exception("Failed to fetch config")
        return {}


@app.put("/api/config")
async def api_put_config(cfg: dict):
    try:
        save_config(cfg)
        return {"status": "saved"}
    except Exception:
        logger.exception("Failed to save config")
        return JSONResponse(
            status_code=500,
            content={"detail": "Failed to save config"},
        )
