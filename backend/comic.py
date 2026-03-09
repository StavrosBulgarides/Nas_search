from __future__ import annotations

import logging
import os
import zipfile
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

router = APIRouter()

# Cache extracted comics in temp dir to avoid re-extracting on every page turn
_extract_cache: dict[str, dict] = {}
_MAX_CACHE = 5

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}


def _is_image(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_EXTS


def _validate_path(path: str) -> str:
    real = os.path.realpath(path)
    if not real.startswith("/mnt/nas"):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.isfile(real):
        raise HTTPException(status_code=404, detail="File not found")
    return real


def _extract_comic(file_path: str) -> dict:
    """Extract comic archive and return page info."""
    if file_path in _extract_cache:
        return _extract_cache[file_path]

    # Evict oldest if cache full
    if len(_extract_cache) >= _MAX_CACHE:
        oldest = next(iter(_extract_cache))
        old = _extract_cache.pop(oldest)
        shutil.rmtree(old["dir"], ignore_errors=True)

    ext = Path(file_path).suffix.lower()
    temp_dir = tempfile.mkdtemp(prefix="comic_")

    try:
        if ext == ".cbz":
            _extract_zip(file_path, temp_dir)
        elif ext == ".cbr":
            _extract_rar(file_path, temp_dir)
        elif ext == ".cb7":
            _extract_7z(file_path, temp_dir)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}")
    except HTTPException:
        raise
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.exception("Failed to extract %s", file_path)
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    # Find all image files
    pages = []
    for root, dirs, files in os.walk(temp_dir):
        for f in files:
            if _is_image(f):
                pages.append(os.path.join(root, f))

    # Sort naturally by path
    pages.sort(key=lambda p: p.lower())

    if not pages:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="No images found in archive")

    info = {"dir": temp_dir, "pages": pages}
    _extract_cache[file_path] = info
    logger.info("Extracted comic: %s (%d pages)", file_path, len(pages))
    return info


def _extract_zip(file_path: str, dest: str):
    with zipfile.ZipFile(file_path, 'r') as zf:
        zf.extractall(dest)


def _extract_rar(file_path: str, dest: str):
    # Use unrar command (installed in Docker)
    result = subprocess.run(
        ["unrar", "x", "-o+", file_path, dest],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"unrar failed: {result.stderr[:200]}")


def _extract_7z(file_path: str, dest: str):
    result = subprocess.run(
        ["7z", "x", f"-o{dest}", file_path],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"7z failed: {result.stderr[:200]}")


@router.get("/api/comic/info")
async def comic_info(path: str = Query(...)):
    real = _validate_path(path)
    info = _extract_comic(real)
    return {"pages": len(info["pages"]), "filename": Path(path).name}


@router.get("/api/comic/page/{page_num}")
async def comic_page(page_num: int, path: str = Query(...)):
    real = _validate_path(path)
    info = _extract_comic(real)

    if page_num < 0 or page_num >= len(info["pages"]):
        raise HTTPException(status_code=404, detail="Page not found")

    page_path = info["pages"][page_num]
    ext = Path(page_path).suffix.lower()
    content_type = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.gif': 'image/gif',
        '.bmp': 'image/bmp', '.webp': 'image/webp',
    }.get(ext, 'image/jpeg')

    with open(page_path, 'rb') as f:
        data = f.read()

    return Response(content=data, media_type=content_type)
