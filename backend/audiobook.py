from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from backend.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


def _natural_sort_key(s: str):
    """Sort strings with embedded numbers naturally: 'ch2' < 'ch10'."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", s)]


def _read_mp3_metadata(path: str) -> dict:
    """Read ID3 tags, duration, and embedded chapters from an MP3 file."""
    info = {
        "duration": 0, "track_num": 0, "disc_num": 0,
        "title": "", "artist": "", "album": "", "chapters": [],
    }
    try:
        from mutagen.mp3 import MP3

        audio = MP3(path)
        info["duration"] = audio.info.length
        tags = audio.tags
        if tags:
            try:
                info["track_num"] = int(str(tags.get("TRCK", "0")).split("/")[0])
            except (ValueError, AttributeError):
                pass
            try:
                info["disc_num"] = int(str(tags.get("TPOS", "0")).split("/")[0])
            except (ValueError, AttributeError):
                pass
            info["title"] = str(tags.get("TIT2", ""))
            info["artist"] = str(tags.get("TPE1", ""))
            info["album"] = str(tags.get("TALB", ""))

            # Extract embedded CHAP frames
            chapters = []
            for key in tags:
                if key.startswith("CHAP"):
                    chap = tags[key]
                    start_ms = getattr(chap, "start_time", 0) or 0
                    end_ms = getattr(chap, "end_time", 0) or 0
                    # Chapter title from sub-frames
                    chap_title = ""
                    if hasattr(chap, "sub_frames"):
                        for sf in chap.sub_frames.values():
                            if hasattr(sf, "text") and sf.text:
                                chap_title = str(sf.text[0])
                                break
                    chapters.append({
                        "title": chap_title or f"Chapter {len(chapters) + 1}",
                        "start": start_ms / 1000.0,
                        "end": end_ms / 1000.0,
                    })

            # Sort chapters by start time
            chapters.sort(key=lambda c: c["start"])
            info["chapters"] = chapters

    except Exception as e:
        logger.debug("Failed to read MP3 tags for %s: %s", path, e)
    return info


def _get_ordered_files(conn, folder_path: str) -> list:
    """Get ordered list of MP3 files in a folder from the DB."""
    files = conn.execute(
        "SELECT full_path, filename, size FROM files WHERE folder_path = ? AND extension = 'mp3'",
        (folder_path,),
    ).fetchall()
    return [dict(f) for f in files]


def _compute_metadata(conn, folder_path: str) -> dict:
    """Read MP3 tags from files in a folder and cache the aggregate metadata."""
    files = _get_ordered_files(conn, folder_path)
    if not files:
        return None

    total_duration = 0
    author = ""
    album = ""
    file_durations = []

    for f in files:
        meta = _read_mp3_metadata(f["full_path"])
        total_duration += meta["duration"]
        file_durations.append({
            "full_path": f["full_path"],
            "duration": meta["duration"],
            "track_num": meta["track_num"],
            "disc_num": meta["disc_num"],
        })
        if not author and meta["artist"]:
            author = meta["artist"]
        if not album and meta["album"]:
            album = meta["album"]

    title = os.path.basename(folder_path)
    # Series = parent folder name (one level up from the audiobook folder)
    parent = os.path.dirname(folder_path)
    series = os.path.basename(parent) if parent else ""

    now = time.time()
    conn.execute("""
        INSERT INTO audiobook_meta (folder_path, title, author, album, series, total_duration, file_count, cached_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(folder_path) DO UPDATE SET
            title = excluded.title,
            author = excluded.author,
            album = excluded.album,
            series = excluded.series,
            total_duration = excluded.total_duration,
            file_count = excluded.file_count,
            cached_at = excluded.cached_at
    """, (folder_path, title, author, album, series, total_duration, len(files), now))

    return {
        "title": title,
        "author": author,
        "album": album,
        "series": series,
        "total_duration": total_duration,
        "file_count": len(files),
        "file_durations": file_durations,
    }


def _get_cached_meta(conn, folder_path: str) -> Optional[dict]:
    """Get cached metadata for a folder, or None if not cached."""
    row = conn.execute(
        "SELECT * FROM audiobook_meta WHERE folder_path = ?", (folder_path,)
    ).fetchone()
    return dict(row) if row else None


def _compute_completion(conn, folder_path: str, progress: Optional[dict], meta: dict) -> float:
    """Compute completion percentage for a book."""
    if not progress:
        return 0.0
    if progress.get("is_finished"):
        return 100.0

    total_duration = meta.get("total_duration", 0)
    if total_duration <= 0:
        return 0.0

    current_file = progress.get("current_file", "")
    position = progress.get("position", 0)

    # Get ordered files with durations from cache
    cached_meta = _get_cached_meta(conn, folder_path)
    if not cached_meta:
        return 0.0

    # We need per-file durations to compute accurate completion.
    # Read from file list and match against current file.
    files = conn.execute(
        "SELECT full_path, filename FROM files WHERE folder_path = ? AND extension = 'mp3'",
        (folder_path,),
    ).fetchall()

    # Sort files the same way as the player
    file_list = []
    for f in files:
        file_meta = _read_mp3_metadata(f["full_path"])
        file_list.append({
            "full_path": f["full_path"],
            "filename": f["filename"],
            "duration": file_meta["duration"],
            "track_num": file_meta["track_num"],
            "disc_num": file_meta["disc_num"],
        })

    file_list.sort(key=lambda x: (
        x.get("disc_num", 0),
        x.get("track_num", 0),
        _natural_sort_key(x.get("filename", "")),
    ))

    # Sum durations of completed files + current position
    completed = 0.0
    for f in file_list:
        if f["full_path"] == current_file:
            completed += position
            break
        completed += f["duration"]

    if total_duration > 0:
        return min(100.0, round((completed / total_duration) * 100, 1))
    return 0.0


@router.get("/api/audiobooks")
async def list_audiobooks(
    sort: str = Query("title", description="Sort by: title, author, recent, duration"),
    search: str = Query("", description="Search audiobooks by title or author"),
):
    """List all folders containing MP3 files, with metadata and progress."""
    try:
        with get_db() as conn:
            # Batch query 1: all MP3 folders with counts
            folders = conn.execute("""
                SELECT folder_path, COUNT(*) as file_count, SUM(size) as total_size
                FROM files WHERE extension = 'mp3'
                GROUP BY folder_path
                ORDER BY folder_path
            """).fetchall()

            folder_map = {f["folder_path"]: dict(f) for f in folders}

            # Batch query 2: all cached metadata in one go
            all_meta = conn.execute("SELECT * FROM audiobook_meta").fetchall()
            meta_map = {row["folder_path"]: dict(row) for row in all_meta}

            # Batch query 3: all progress in one go
            all_progress = conn.execute("SELECT * FROM audiobook_progress").fetchall()
            progress_map = {row["folder_path"]: dict(row) for row in all_progress}

            result = []
            for folder_path, f in folder_map.items():
                meta = meta_map.get(folder_path)
                if not meta:
                    meta = {
                        "title": os.path.basename(folder_path),
                        "author": "",
                        "album": "",
                        "series": os.path.basename(os.path.dirname(folder_path)),
                        "total_duration": 0,
                        "file_count": f["file_count"],
                    }

                progress = progress_map.get(folder_path)

                # Approximate completion percentage without extra queries
                completion_pct = 0.0
                if progress and progress.get("is_finished"):
                    completion_pct = 100.0
                elif progress and progress.get("position", 0) > 0:
                    total_dur = meta.get("total_duration", 0)
                    file_count = f["file_count"]
                    if total_dur > 0 and file_count > 0:
                        # Rough estimate: assume equal file lengths
                        avg_dur = total_dur / file_count
                        # We don't know which file index without another query,
                        # so use position / avg_dur as a rough file index
                        est_completed_secs = progress.get("position", 0)
                        completion_pct = round(min(99.9, (est_completed_secs / total_dur) * 100), 1)

                book = {
                    "folder_path": folder_path,
                    "title": meta.get("title", os.path.basename(folder_path)),
                    "author": meta.get("author", ""),
                    "album": meta.get("album", ""),
                    "series": meta.get("series", ""),
                    "total_duration": meta.get("total_duration", 0),
                    "file_count": f["file_count"],
                    "total_size": f["total_size"],
                    "completion_pct": completion_pct,
                    "progress": progress,
                }
                result.append(book)

            # Apply search filter
            if search:
                q = search.lower()
                result = [b for b in result if
                          q in b["title"].lower() or
                          q in b["author"].lower() or
                          q in b["album"].lower() or
                          q in b["series"].lower() or
                          q in b["folder_path"].lower()]

            # Apply sort
            if sort == "author":
                result.sort(key=lambda b: (b["author"].lower() or "zzz", b["title"].lower()))
            elif sort == "recent":
                result.sort(key=lambda b: b["progress"]["last_played"] if b["progress"] else 0, reverse=True)
            elif sort == "duration":
                result.sort(key=lambda b: b["total_duration"], reverse=True)
            elif sort == "series":
                result.sort(key=lambda b: (b["series"].lower() or "zzz", b["title"].lower()))
            else:
                result.sort(key=lambda b: b["title"].lower())

            return {"audiobooks": result}
    except Exception:
        logger.exception("Failed to list audiobooks")
        return {"audiobooks": []}


@router.post("/api/audiobooks/refresh-meta")
async def refresh_metadata():
    """Recompute cached metadata for all audiobook folders."""
    try:
        with get_db() as conn:
            # Clear existing cache
            conn.execute("DELETE FROM audiobook_meta")

            folders = conn.execute("""
                SELECT DISTINCT folder_path FROM files WHERE extension = 'mp3'
            """).fetchall()

            count = 0
            for f in folders:
                _compute_metadata(conn, f["folder_path"])
                count += 1

        logger.info("Refreshed audiobook metadata for %d folders", count)
        return {"status": "ok", "folders_refreshed": count}
    except Exception:
        logger.exception("Failed to refresh audiobook metadata")
        return JSONResponse(status_code=500, content={"detail": "Failed to refresh metadata"})


@router.get("/api/audiobook/files")
async def get_audiobook_files(folder: str = Query(..., description="Folder path")):
    """Get ordered list of MP3 files in a folder with metadata."""
    try:
        with get_db() as conn:
            files = conn.execute(
                "SELECT * FROM files WHERE folder_path = ? AND extension = 'mp3'",
                (folder,),
            ).fetchall()

        file_list = []
        for f in files:
            meta = _read_mp3_metadata(f["full_path"])
            file_list.append({
                "full_path": f["full_path"],
                "filename": f["filename"],
                "size": f["size"],
                "duration": meta["duration"],
                "track_num": meta["track_num"],
                "disc_num": meta["disc_num"],
                "title": meta["title"],
                "artist": meta["artist"],
                "album": meta["album"],
                "chapters": meta["chapters"],
            })

        file_list.sort(key=lambda x: (
            x.get("disc_num", 0),
            x.get("track_num", 0),
            _natural_sort_key(x.get("filename", "")),
        ))

        return {
            "files": file_list,
            "folder": folder,
            "title": os.path.basename(folder),
        }
    except Exception:
        logger.exception("Failed to get audiobook files for %s", folder)
        return JSONResponse(status_code=500, content={"detail": "Failed to load audiobook"})


@router.get("/api/audiobook/progress")
async def get_progress(folder: str = Query(..., description="Folder path")):
    """Get saved progress and bookmarks for an audiobook."""
    try:
        with get_db() as conn:
            progress = conn.execute(
                "SELECT * FROM audiobook_progress WHERE folder_path = ?",
                (folder,),
            ).fetchone()
            bookmarks = conn.execute(
                "SELECT * FROM audiobook_bookmarks WHERE folder_path = ? ORDER BY created_at DESC",
                (folder,),
            ).fetchall()

        return {
            "progress": dict(progress) if progress else None,
            "bookmarks": [dict(b) for b in bookmarks],
        }
    except Exception:
        logger.exception("Failed to get progress for %s", folder)
        return {"progress": None, "bookmarks": []}


@router.put("/api/audiobook/progress")
async def save_progress(data: dict):
    """Save playback progress for an audiobook."""
    try:
        folder = data["folder_path"]
        current_file = data["current_file"]
        position = data.get("position", 0)
        speed = data.get("playback_speed", 1.0)
        finished = 1 if data.get("is_finished", False) else 0

        with get_db() as conn:
            conn.execute("""
                INSERT INTO audiobook_progress
                    (folder_path, current_file, position, playback_speed, is_finished, last_played)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(folder_path) DO UPDATE SET
                    current_file = excluded.current_file,
                    position = excluded.position,
                    playback_speed = excluded.playback_speed,
                    is_finished = excluded.is_finished,
                    last_played = excluded.last_played
            """, (folder, current_file, position, speed, finished, time.time()))

        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to save progress")
        return JSONResponse(status_code=500, content={"detail": "Failed to save progress"})


@router.post("/api/audiobook/bookmark")
async def add_bookmark(data: dict):
    """Add a bookmark at the current position."""
    try:
        with get_db() as conn:
            conn.execute("""
                INSERT INTO audiobook_bookmarks (folder_path, file_path, position, note, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                data["folder_path"],
                data["file_path"],
                data["position"],
                data.get("note", ""),
                time.time(),
            ))
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to add bookmark")
        return JSONResponse(status_code=500, content={"detail": "Failed to add bookmark"})


@router.delete("/api/audiobook/bookmark/{bookmark_id}")
async def delete_bookmark(bookmark_id: int):
    """Delete a bookmark."""
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM audiobook_bookmarks WHERE id = ?", (bookmark_id,))
        return {"status": "ok"}
    except Exception:
        logger.exception("Failed to delete bookmark %d", bookmark_id)
        return JSONResponse(status_code=500, content={"detail": "Failed to delete bookmark"})


@router.get("/api/audiobook/bookmarks/all")
async def get_all_bookmarks():
    """Get all bookmarks across all audiobooks."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM audiobook_bookmarks ORDER BY created_at DESC"
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            # Add book title from folder path
            d["book_title"] = os.path.basename(d["folder_path"])
            d["file_name"] = os.path.basename(d["file_path"]).replace(".mp3", "")
            result.append(d)
        return {"bookmarks": result}
    except Exception:
        logger.exception("Failed to get all bookmarks")
        return {"bookmarks": []}


@router.get("/api/audiobook/cover")
async def get_cover(folder: str = Query(..., description="Folder path")):
    """Extract cover art from the first MP3 file in a folder."""
    try:
        with get_db() as conn:
            file = conn.execute(
                "SELECT full_path FROM files WHERE folder_path = ? AND extension = 'mp3' LIMIT 1",
                (folder,),
            ).fetchone()

        if not file:
            return JSONResponse(status_code=404, content={"detail": "No files found"})

        from mutagen.id3 import ID3

        tags = ID3(file["full_path"])
        for key in tags:
            if key.startswith("APIC"):
                apic = tags[key]
                return Response(content=apic.data, media_type=apic.mime)

        return JSONResponse(status_code=404, content={"detail": "No cover art"})
    except Exception:
        logger.debug("No cover art for %s", folder)
        return JSONResponse(status_code=404, content={"detail": "No cover art"})
