import logging
import os
import time
from pathlib import Path

from backend.config import get_config
from backend.database import (
    get_db,
    upsert_file,
    get_all_indexed_paths,
    log_index_run,
)

logger = logging.getLogger(__name__)

_indexing_in_progress = False


def is_indexing() -> bool:
    return _indexing_in_progress


def run_index(full_scan: bool = False):
    global _indexing_in_progress
    if _indexing_in_progress:
        logger.warning("Indexing already in progress, skipping request")
        return

    _indexing_in_progress = True
    scan_type = "full" if full_scan else "incremental"
    started_at = time.time()
    added = 0
    updated = 0
    removed = 0
    errors = 0
    dirs_scanned = 0
    files_seen = 0

    logger.info("=== Indexing started (%s scan) ===", scan_type)

    try:
        config = get_config()
        extensions = set(ext.lower().lstrip(".") for ext in config.get("extensions", []))
        folders = config.get("indexed_folders", {})

        if not folders:
            logger.warning("No folders configured for indexing — nothing to do")
            return

        logger.info("Extensions filter: %s", extensions if extensions else "all")
        logger.info("Folders to scan: %d", len(folders))

        with get_db() as conn:
            existing = get_all_indexed_paths(conn)
            logger.info("Existing indexed files: %d", len(existing))
            seen_paths = set()

            for label, folder_path in folders.items():
                if not os.path.isdir(folder_path):
                    logger.error(
                        "Folder not found: '%s' -> '%s' — check volume mount and config",
                        label, folder_path,
                    )
                    errors += 1
                    continue

                logger.info("Scanning folder: %s (%s)", label, folder_path)
                folder_start = time.time()
                a, u, e, d, f = _scan_directory(
                    conn, folder_path, extensions, existing, seen_paths, full_scan
                )
                added += a
                updated += u
                errors += e
                dirs_scanned += d
                files_seen += f
                folder_duration = time.time() - folder_start
                logger.info(
                    "  %s done: +%d added, ~%d updated, %d errors, "
                    "%d dirs, %d matching files in %.1fs",
                    label, a, u, e, d, f, folder_duration,
                )

            # Remove files that no longer exist on disk
            to_remove = set(existing.keys()) - seen_paths
            if to_remove:
                removed = len(to_remove)
                logger.info("Removing %d files no longer on disk", removed)
                # Delete in batches to avoid huge SQL statements
                remove_list = list(to_remove)
                batch_size = 500
                for i in range(0, len(remove_list), batch_size):
                    batch = remove_list[i:i + batch_size]
                    placeholders = ",".join("?" * len(batch))
                    conn.execute(
                        f"DELETE FROM files WHERE full_path IN ({placeholders})",
                        batch,
                    )

            finished_at = time.time()
            duration = finished_at - started_at
            log_index_run(conn, started_at, finished_at, added, updated, removed, duration)

        logger.info("=== Indexing complete ===")
        logger.info(
            "  Results: +%d added, ~%d updated, -%d removed",
            added, updated, removed,
        )
        logger.info(
            "  Scanned: %d directories, %d matching files",
            dirs_scanned, files_seen,
        )
        logger.info("  Errors: %d", errors)
        logger.info("  Duration: %.1fs", duration)

    except Exception:
        logger.exception("Indexing failed with unexpected error")
    finally:
        _indexing_in_progress = False


def _scan_directory(
    conn, root: str, extensions: set, existing: dict, seen_paths: set, full_scan: bool
) -> tuple:
    added = 0
    updated = 0
    errors = 0
    dirs_scanned = 0
    files_seen = 0

    skipped_extensions = {}

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden directories
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and not d.startswith("@")]
        dirs_scanned += 1

        # For incremental scan, skip directories that haven't changed
        if not full_scan and existing:
            try:
                dir_mtime = os.path.getmtime(dirpath)
            except OSError as e:
                logger.warning("Cannot stat directory '%s': %s", dirpath, e)
                errors += 1
                continue
            last_indexed = max(
                (existing.get(os.path.join(dirpath, f), 0) for f in filenames),
                default=0,
            )
            if dir_mtime < last_indexed and not full_scan:
                # Still need to record seen_paths for deletion detection
                for filename in filenames:
                    if filename.startswith("."):
                        continue
                    ext = Path(filename).suffix.lower().lstrip(".")
                    if extensions and ext not in extensions:
                        skipped_extensions[ext] = skipped_extensions.get(ext, 0) + 1
                        continue
                    seen_paths.add(os.path.join(dirpath, filename))
                continue

        for filename in filenames:
            if filename.startswith("."):
                continue

            ext = Path(filename).suffix.lower().lstrip(".")
            if extensions and ext not in extensions:
                skipped_extensions[ext] = skipped_extensions.get(ext, 0) + 1
                continue

            full_path = os.path.join(dirpath, filename)
            seen_paths.add(full_path)
            files_seen += 1

            try:
                stat = os.stat(full_path)
            except OSError as e:
                logger.warning("Cannot stat file '%s': %s", full_path, e)
                errors += 1
                continue

            prev_mtime = existing.get(full_path)
            if prev_mtime is not None and abs(stat.st_mtime - prev_mtime) < 1:
                continue  # Unchanged

            try:
                folder_path = dirpath
                upsert_file(
                    conn, filename, folder_path, full_path, ext, stat.st_size, stat.st_mtime
                )
            except Exception as e:
                logger.error("Failed to index file '%s': %s", full_path, e)
                errors += 1
                continue

            if prev_mtime is None:
                added += 1
            else:
                updated += 1

    if skipped_extensions:
        sorted_skipped = sorted(skipped_extensions.items(), key=lambda x: -x[1])
        skipped_str = ", ".join(f".{ext}({count})" for ext, count in sorted_skipped)
        logger.info("  Skipped extensions: %s", skipped_str)

    return added, updated, errors, dirs_scanned, files_seen
