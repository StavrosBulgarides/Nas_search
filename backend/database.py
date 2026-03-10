import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from backend.config import DB_PATH

logger = logging.getLogger(__name__)

_local = threading.local()


def get_connection() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        logger.debug("Opening new SQLite connection to %s (thread=%s)", DB_PATH, threading.current_thread().name)
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
    return _local.conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        logger.exception("Database error, rolling back transaction")
        conn.rollback()
        raise


def init_db():
    logger.info("Initialising database at %s", DB_PATH)
    try:
        with get_db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    folder_path TEXT NOT NULL,
                    full_path TEXT NOT NULL UNIQUE,
                    extension TEXT,
                    size INTEGER,
                    modified_date REAL,
                    indexed_date REAL
                );

                CREATE INDEX IF NOT EXISTS idx_files_folder ON files(folder_path);
                CREATE INDEX IF NOT EXISTS idx_files_ext ON files(extension);
                CREATE INDEX IF NOT EXISTS idx_files_modified ON files(modified_date DESC);

                CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
                    filename, folder_path,
                    content='files',
                    content_rowid='id',
                    tokenize='unicode61'
                );

                CREATE TABLE IF NOT EXISTS folder_usage (
                    folder_path TEXT PRIMARY KEY,
                    usage_count INTEGER DEFAULT 0,
                    last_accessed REAL
                );

                CREATE TABLE IF NOT EXISTS index_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at REAL,
                    finished_at REAL,
                    files_added INTEGER DEFAULT 0,
                    files_updated INTEGER DEFAULT 0,
                    files_removed INTEGER DEFAULT 0,
                    duration REAL
                );

                CREATE TABLE IF NOT EXISTS audiobook_progress (
                    folder_path TEXT PRIMARY KEY,
                    current_file TEXT NOT NULL,
                    position REAL DEFAULT 0,
                    playback_speed REAL DEFAULT 1.0,
                    is_finished INTEGER DEFAULT 0,
                    last_played REAL
                );

                CREATE TABLE IF NOT EXISTS audiobook_bookmarks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder_path TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    position REAL NOT NULL,
                    note TEXT DEFAULT '',
                    created_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_audiobook_bookmarks_folder
                    ON audiobook_bookmarks(folder_path);

                CREATE TABLE IF NOT EXISTS epub_bookmarks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    cfi TEXT NOT NULL,
                    label TEXT DEFAULT '',
                    note TEXT DEFAULT '',
                    percentage REAL DEFAULT 0,
                    created_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_epub_bookmarks_file
                    ON epub_bookmarks(file_path);

                CREATE TABLE IF NOT EXISTS audiobook_meta (
                    folder_path TEXT PRIMARY KEY,
                    title TEXT DEFAULT '',
                    author TEXT DEFAULT '',
                    album TEXT DEFAULT '',
                    series TEXT DEFAULT '',
                    total_duration REAL DEFAULT 0,
                    file_count INTEGER DEFAULT 0,
                    cached_at REAL
                );
            """)

            # Create triggers to keep FTS in sync
            conn.executescript("""
                CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
                    INSERT INTO files_fts(rowid, filename, folder_path)
                    VALUES (new.id, new.filename, new.folder_path);
                END;

                CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
                    INSERT INTO files_fts(files_fts, rowid, filename, folder_path)
                    VALUES ('delete', old.id, old.filename, old.folder_path);
                END;

                CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
                    INSERT INTO files_fts(files_fts, rowid, filename, folder_path)
                    VALUES ('delete', old.id, old.filename, old.folder_path);
                    INSERT INTO files_fts(rowid, filename, folder_path)
                    VALUES (new.id, new.filename, new.folder_path);
                END;
            """)

            count = get_file_count(conn)
            logger.info("Database ready: %d files currently indexed", count)

    except Exception:
        logger.exception("Failed to initialise database")
        raise


def upsert_file(conn, filename, folder_path, full_path, extension, size, modified_date):
    now = time.time()
    conn.execute("""
        INSERT INTO files (filename, folder_path, full_path, extension, size, modified_date, indexed_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(full_path) DO UPDATE SET
            filename=excluded.filename,
            folder_path=excluded.folder_path,
            extension=excluded.extension,
            size=excluded.size,
            modified_date=excluded.modified_date,
            indexed_date=excluded.indexed_date
    """, (filename, folder_path, full_path, extension, size, modified_date, now))


def delete_missing_files(conn, existing_paths: set):
    cursor = conn.execute("SELECT id, full_path FROM files")
    to_delete = []
    for row in cursor:
        if row["full_path"] not in existing_paths:
            to_delete.append(row["id"])
    if to_delete:
        placeholders = ",".join("?" * len(to_delete))
        conn.execute(f"DELETE FROM files WHERE id IN ({placeholders})", to_delete)
    return len(to_delete)


def get_all_indexed_paths(conn) -> dict:
    """Return {full_path: modified_date} for all indexed files."""
    cursor = conn.execute("SELECT full_path, modified_date FROM files")
    return {row["full_path"]: row["modified_date"] for row in cursor}


def get_file_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]


def get_last_index_log(conn):
    row = conn.execute(
        "SELECT * FROM index_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def log_index_run(conn, started_at, finished_at, added, updated, removed, duration):
    conn.execute("""
        INSERT INTO index_log (started_at, finished_at, files_added, files_updated, files_removed, duration)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (started_at, finished_at, added, updated, removed, duration))


def increment_folder_usage(conn, folder_path: str):
    now = time.time()
    conn.execute("""
        INSERT INTO folder_usage (folder_path, usage_count, last_accessed)
        VALUES (?, 1, ?)
        ON CONFLICT(folder_path) DO UPDATE SET
            usage_count = usage_count + 1,
            last_accessed = excluded.last_accessed
    """, (folder_path, now))


def get_folder_usage(conn) -> dict:
    cursor = conn.execute("SELECT folder_path, usage_count FROM folder_usage")
    return {row["folder_path"]: row["usage_count"] for row in cursor}


def get_distinct_folders(conn) -> list:
    cursor = conn.execute("SELECT DISTINCT folder_path FROM files ORDER BY folder_path")
    return [row["folder_path"] for row in cursor]


def get_distinct_extensions(conn) -> list:
    cursor = conn.execute(
        "SELECT DISTINCT extension FROM files WHERE extension IS NOT NULL ORDER BY extension"
    )
    return [row["extension"] for row in cursor]


def get_recent_files(conn, limit: int = 10) -> list:
    cursor = conn.execute(
        "SELECT * FROM files ORDER BY modified_date DESC LIMIT ?", (limit,)
    )
    return [dict(row) for row in cursor]
