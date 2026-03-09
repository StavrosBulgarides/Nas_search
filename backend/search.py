from __future__ import annotations

import logging
import re
import time
from typing import Optional, Tuple, List
from backend.database import get_db, get_folder_usage
from backend.config import get_config
from backend.models import FileResult

logger = logging.getLogger(__name__)


def search_files(
    query: str,
    folder: Optional[str] = None,
    extension: Optional[str] = None,
    fuzzy: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[FileResult], int]:
    if not query or not query.strip():
        return [], 0

    config = get_config()
    max_results = config.get("max_results", 100)
    limit = min(limit, max_results)
    start_time = time.time()

    with get_db() as conn:
        # Try FTS search first
        results, total = _fts_search(conn, query, folder, extension, limit, offset)

        search_type = "fts"

        # Fall back to fuzzy if enabled and no results
        if not results and fuzzy:
            search_type = "fuzzy"
            results, total = _fuzzy_search(
                conn, query, folder, extension, limit, offset,
                config.get("fuzzy_threshold", 80)
            )

        elapsed_ms = (time.time() - start_time) * 1000

        logger.info(
            "Search: q='%s' folder=%s ext=%s fuzzy=%s type=%s -> %d results (%d total) in %.1fms",
            query,
            folder or "all",
            extension or "all",
            fuzzy,
            search_type,
            len(results),
            total,
            elapsed_ms,
        )

        if elapsed_ms > 200:
            logger.warning(
                "Slow search: q='%s' took %.1fms (target <100ms)",
                query, elapsed_ms,
            )

        if total == 0:
            logger.debug("Zero results for q='%s' (fuzzy=%s)", query, fuzzy)

        return results, total


def _fts_search(conn, query, folder, extension, limit, offset):
    tokens = _tokenize(query)
    if not tokens:
        return [], 0

    where_clauses = []
    params = []

    if folder:
        where_clauses.append("f.folder_path LIKE ?")
        params.append(f"{folder}%")

    if extension:
        where_clauses.append("f.extension = ?")
        params.append(extension.lower().lstrip("."))

    where_sql = ""
    if where_clauses:
        where_sql = "AND " + " AND ".join(where_clauses)

    # Try AND first (all tokens must match)
    fts_terms = " AND ".join(f'"{t}"*' for t in tokens)
    logger.debug("FTS query (AND): tokens=%s fts_terms='%s'", tokens, fts_terms)

    results, total = _run_fts_query(conn, fts_terms, where_sql, params, limit, offset)

    # If AND returns nothing and we have multiple tokens, try OR (any token matches)
    if total == 0 and len(tokens) > 1:
        fts_terms = " OR ".join(f'"{t}"*' for t in tokens)
        logger.debug("FTS query (OR fallback): fts_terms='%s'", fts_terms)
        results, total = _run_fts_query(conn, fts_terms, where_sql, params, limit, offset)

    return results, total


def _run_fts_query(conn, fts_terms, where_sql, params, limit, offset):
    # Get folder usage for boosting
    folder_usage = get_folder_usage(conn)
    max_usage = max(folder_usage.values()) if folder_usage else 1

    # Count total matches
    count_sql = f"""
        SELECT COUNT(*) FROM files_fts
        JOIN files f ON f.id = files_fts.rowid
        WHERE files_fts MATCH ? {where_sql}
    """
    try:
        total = conn.execute(count_sql, [fts_terms] + params).fetchone()[0]
    except Exception:
        logger.exception("FTS count query failed: terms='%s' params=%s", fts_terms, params)
        return [], 0

    if total == 0:
        return [], 0

    # Fetch results with ranking
    now = time.time()
    search_sql = f"""
        SELECT f.*, -rank AS fts_score
        FROM files_fts
        JOIN files f ON f.id = files_fts.rowid
        WHERE files_fts MATCH ? {where_sql}
        ORDER BY -rank DESC
        LIMIT ? OFFSET ?
    """
    try:
        rows = conn.execute(search_sql, [fts_terms] + params + [limit * 3, 0]).fetchall()
    except Exception:
        logger.exception("FTS search query failed: terms='%s' params=%s", fts_terms, params)
        return [], 0

    # Apply composite scoring
    results = []
    for row in rows:
        row_dict = dict(row)
        score = row_dict.pop("fts_score", 0)

        # Folder usage boost (0-5 points)
        fp = row_dict["folder_path"]
        usage = folder_usage.get(fp, 0)
        score += (usage / max_usage) * 5 if max_usage > 0 else 0

        # Recency boost (0-3 points, files modified in last 30 days get max)
        age_days = (now - row_dict["modified_date"]) / 86400
        if age_days < 30:
            score += 3 * (1 - age_days / 30)

        results.append(FileResult(**row_dict, score=score))

    # Sort by composite score and apply offset/limit
    results.sort(key=lambda r: r.score, reverse=True)
    results = results[offset:offset + limit]

    return results, total


def _fuzzy_search(conn, query, folder, extension, limit, offset, threshold):
    from rapidfuzz import fuzz

    where_clauses = ["1=1"]
    params = []

    if folder:
        where_clauses.append("folder_path LIKE ?")
        params.append(f"{folder}%")

    if extension:
        where_clauses.append("extension = ?")
        params.append(extension.lower().lstrip("."))

    where_sql = " AND ".join(where_clauses)

    try:
        rows = conn.execute(
            f"SELECT * FROM files WHERE {where_sql}", params
        ).fetchall()
    except Exception:
        logger.exception("Fuzzy search DB query failed")
        return [], 0

    logger.debug("Fuzzy search: scanning %d files against q='%s' (threshold=%d)", len(rows), query, threshold)

    query_lower = query.lower()
    scored = []
    for row in rows:
        row_dict = dict(row)
        name_score = fuzz.partial_ratio(query_lower, row_dict["filename"].lower())
        path_score = fuzz.partial_ratio(query_lower, row_dict["full_path"].lower())
        best = max(name_score, path_score)
        if best >= threshold:
            scored.append(FileResult(**row_dict, score=best))

    scored.sort(key=lambda r: r.score, reverse=True)
    total = len(scored)
    results = scored[offset:offset + limit]
    return results, total


def _tokenize(query: str) -> list:
    # Split on whitespace and common separators, filter empties
    tokens = re.split(r'[\s\-_/\\]+', query.strip())
    return [t for t in tokens if len(t) >= 1]
