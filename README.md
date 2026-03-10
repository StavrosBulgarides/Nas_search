# Search Wizard

A fast, lightweight search tool for finding files across a Synology NAS. Built to replace Synology's built-in Universal Search, which becomes unusable with tens of thousands of files — returning overwhelming result lists with no meaningful way to filter by folder or file type.

Search Wizard solves this by providing:

- **Instant search** (<100ms) across hundreds of thousands of files using SQLite FTS5
- **Fuzzy matching** for when you can't remember the exact title or spelling
- **Folder filtering** to narrow results to specific collections
- **Direct file opening** — launch files in the appropriate viewer based on type:
  - Epub via built-in reader (epub.js) — far faster than Synology's native PDFViewer
  - PDF via built-in reader (PDF.js) with page navigation and zoom
  - MP4, WebM, MOV via Synology VideoPlayer
  - MKV, AVI, WMV, FLV via built-in video player with FFmpeg transcoding
  - CBZ, CBR, CB7 via built-in comic reader with page navigation
  - MP3 via built-in audiobook player with position saving
- **Audiobook player** — full-featured player for MP3 audiobooks with:
  - Auto-save position (never lose your place)
  - Chapter navigation (embedded ID3 CHAP frames or per-file chapters)
  - Bookmarks with notes
  - Sleep timer (timed, end of file, end of chapter)
  - Playback speed control (0.5x–3x)
  - Library view with cover art, progress tracking, and series grouping
  - Cross-device position sync (via server-side SQLite)
- **Folder navigation** — jump to any result's location in Synology File Station
- **Automated reindexing** so results stay current without manual intervention

## Architecture

```
┌───────────────────────────────────────────────────────┐
│                    Docker Container                   │
│                                                       │
│  ┌──────────────┐        ┌─────────────────────────┐  │
│  │   Frontend   │        │       Backend           │  │
│  │              │        │                         │  │
│  │  index.html  │  HTTP  │  FastAPI (Python)       │  │
│  │  player.html │◄──────►│  uvicorn :8080          │  │
│  │  reader.html │        │                         │  │
│  │  pdf-reader  │        │                         │  │
│  │  epub-reader │        │                         │  │
│  │  ab-player   │        │                         │  │
│  │  app.js      │        │                         │  │
│  │  style.css   │        │  ┌───────────────────┐  │  │
│  └──────────────┘        │  │  SQLite + FTS5    │  │  │
│                          │  └───────────────────┘  │  │
│                          │                         │  │
│                          │  ┌───────────────────┐  │  │
│                          │  │  FFmpeg + unrar   │  │  │
│                          │  │  (video & comics) │  │  │
│                          │  └───────────────────┘  │  │
│                          │                         │  │
│                          │  ┌───────────────────┐  │  │
│                          │  │  APScheduler      │  │  │
│                          │  │  (cron 02:00)     │  │  │
│                          │  └───────────────────┘  │  │
│                          └─────────────────────────┘  │
│                                    │                  │
│                           /mnt/nas (read-only)        │
└────────────────────────────┼──────────────────────────┘
                             │
                      ┌──────┴──────┐
                      │  NAS Volume │
                      │  /volume1/  │
                      └─────────────┘
```

### Components

**Frontend** — Vanilla HTML/CSS/JavaScript. No build tools, no framework. Served as static files by FastAPI. All state (pinned folders, recent files) stored in the browser's localStorage. Includes a dedicated video player page for streaming transcoded video.

**Backend** — Python 3.11 with FastAPI. Handles search queries, file indexing, video streaming, configuration, and serves the frontend. Runs on uvicorn.

**Database** — SQLite with WAL journal mode for concurrent reads. Uses FTS5 (Full Text Search 5) virtual tables with automatic sync triggers. The database file is stored in a named Docker volume so it persists across container rebuilds.

**Indexer** — Walks configured folders, reads file metadata (name, path, size, modified date, extension), and upserts into the database. Supports incremental scans (using directory mtime to skip unchanged directories) and full scans. Runs in a background thread to avoid blocking the API.

**Scheduler** — APScheduler with a cron trigger. Runs a full reindex at a configurable time (default 02:00).

**Video Streamer** — Uses FFmpeg to stream video files to the browser. Detects the video codec with ffprobe: H.264 files are remuxed instantly (no CPU cost), while other codecs (H.265, etc.) are transcoded to H.264 on the fly. Output is streamed as fragmented MP4.

**Epub Reader** — Client-side epub rendering using epub.js. Replaces Synology's native PDFViewer for epub files, which is painfully slow. Features chapter navigation, adjustable font size, dark theme, reading position saved in localStorage, and a book-width page layout.

**PDF Reader** — Client-side PDF rendering using Mozilla's PDF.js (loaded via CDN). Provides a page-by-page viewer with zoom controls (in/out/fit-width), keyboard navigation (arrow keys, +/-, Home/End), and a collapsible bookmarks panel. Bookmarks are stored server-side in SQLite for cross-device sync. The bookmark workflow matches the other readers: optional description prompt, jump-to-bookmark with delete confirmation, and back-button save prompt.

**Comic Reader** — Server-side extraction of CBZ (ZIP), CBR (RAR), and CB7 (7-Zip) comic archives using `unrar` and `p7zip`. Images are served as individual pages via API endpoints. The frontend provides a page-by-page reader with keyboard/click navigation, fit-to-width/height toggle, and auto-hiding toolbar. Extracted archives are cached (up to 5) for fast page turns.

**Audiobook Player** — Full-featured MP3 audiobook player designed for long-form listening. Reads ID3 tags via mutagen for metadata (title, artist, album, track/disc numbers) and embedded CHAP frames for chapter markers. Files within a folder are ordered by disc number, track number, then natural filename sort. Progress is saved server-side in SQLite (auto-saves every 5 seconds, on pause, and on close) enabling cross-device sync. Features include: playback speed (0.5x–3x), skip forward/back (10/15/30s), chapter-aware navigation, manual bookmarks with notes, sleep timer, and a library view with cover art, progress bars, series grouping, and search/filter/sort.

### Search Strategy

1. **FTS5 AND search** — All search tokens must appear (prefix matching enabled). This is tried first for precision.
2. **FTS5 OR fallback** — If AND returns zero results for multi-token queries, falls back to matching any token.
3. **Fuzzy search** — If FTS5 returns nothing and fuzzy is enabled, scans all files using rapidfuzz's partial_ratio algorithm against filenames and paths. Files scoring above the configured threshold (default 80) are returned.

Results are ranked using a composite score:
- **FTS5 relevance** — SQLite's built-in ranking
- **Folder usage boost** (0-5 points) — Folders you click on more often rank higher
- **Recency boost** (0-3 points) — Files modified in the last 30 days get a bonus

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve the frontend |
| GET | `/player` | Serve the video player page |
| GET | `/api/search` | Search files (params: q, folder, extension, fuzzy, limit, offset) |
| POST | `/api/index` | Trigger a manual reindex |
| GET | `/api/status` | Get index status (file count, last index time, indexing state) |
| GET | `/api/folders` | List configured top-level folders |
| GET | `/api/extensions` | List distinct file extensions in the index |
| GET | `/api/recent` | Get recently modified files |
| POST | `/api/track-click` | Record a folder click for usage-based ranking |
| GET | `/api/config` | Get current configuration |
| PUT | `/api/config` | Update configuration |
| GET | `/api/stream` | Stream a video file via FFmpeg (params: path) |
| GET | `/pdf-reader` | Serve the PDF reader page |
| GET | `/epub-reader` | Serve the epub reader page |
| GET | `/api/file` | Serve a raw file from NAS (params: path) |
| GET | `/api/pdf/bookmarks` | Get PDF bookmarks (optional param: file) |
| POST | `/api/pdf/bookmark` | Add a PDF bookmark |
| DELETE | `/api/pdf/bookmark/{id}` | Delete a PDF bookmark |
| GET | `/api/comic/info` | Get comic page count (params: path) |
| GET | `/api/comic/page/{n}` | Get a single comic page image (params: path) |
| GET | `/audiobook-player` | Serve the audiobook player page |
| GET | `/api/audiobooks` | List all audiobooks with metadata (params: sort, search) |
| POST | `/api/audiobooks/refresh-meta` | Recompute cached metadata for all audiobook folders |
| GET | `/api/audiobook/files` | Get ordered MP3 files with chapters (params: folder) |
| GET | `/api/audiobook/progress` | Get saved progress and bookmarks (params: folder) |
| PUT | `/api/audiobook/progress` | Save playback position |
| POST | `/api/audiobook/bookmark` | Add a bookmark at current position |
| DELETE | `/api/audiobook/bookmark/{id}` | Delete a bookmark |
| GET | `/api/audiobook/cover` | Get cover art from MP3 ID3 tags (params: folder) |

### Project Structure

```
Nas_search/
├── backend/
│   ├── __init__.py
│   ├── config.py          # YAML config loading/saving
│   ├── database.py        # SQLite schema, FTS5, helper queries
│   ├── indexer.py          # File system walker and metadata extractor
│   ├── main.py             # FastAPI app, routes, middleware
│   ├── models.py           # Pydantic request/response models
│   ├── scheduler.py        # APScheduler cron job
│   ├── search.py           # FTS5 + fuzzy search logic
│   ├── stream.py           # FFmpeg video transcoding and streaming
│   ├── comic.py            # Comic archive extraction and page serving
│   └── audiobook.py        # Audiobook API (files, progress, bookmarks, cover art)
├── frontend/
│   ├── index.html          # Single-page search UI
│   ├── player.html         # Video player page
│   ├── reader.html         # Comic book reader
│   ├── pdf-reader.html     # PDF reader
│   ├── epub-reader.html    # Epub book reader
│   ├── audiobook-player.html  # Audiobook player page
│   ├── app.js              # All frontend logic (vanilla JS)
│   ├── style.css           # Dark theme styles
│   └── favicon.svg         # Browser tab icon
├── config.example.yml      # Example configuration (copy to config.yml)
├── requirements.txt        # Python dependencies
├── Dockerfile
├── docker-compose.yml
└── DEPLOY.md               # Step-by-step deployment guide
```

## Configuration

Copy `config.example.yml` to `config.yml` and edit it. Example:

```yaml
indexed_folders:
  Books: /mnt/nas/Books
  Movies: /mnt/nas/Movies

extensions:
  - epub
  - pdf
  - mp4
  - mkv
  - avi
  - mov
  - cbz
  - cbr
  - mp3

max_results: 100
fuzzy_threshold: 80
schedule_hour: 2
schedule_minute: 0
host: 0.0.0.0
port: 8080
```

| Setting | Description |
|---------|-------------|
| `indexed_folders` | Map of label → container path. Labels appear in the folder filter dropdown. |
| `extensions` | File extensions to index (without dots). |
| `max_results` | Maximum results returned per search query. |
| `fuzzy_threshold` | Minimum fuzzy match score (0-100). Higher = stricter matching. |
| `schedule_hour/minute` | When the nightly reindex runs (24-hour format). |

Configuration can also be edited from the Settings modal in the web UI.

## Deployment on Synology NAS

### Prerequisites

- Synology NAS running DSM 7+ (tested on DS920+)
- **Container Manager** installed (search for it in Package Center; older DSM versions call it "Docker")
- SSH access enabled (Control Panel > Terminal & SNMP > Enable SSH service)
- Your NAS IP address (visible in the browser address bar when accessing DSM)

### Step 1: Copy project files to the NAS

From your terminal:

```bash
rsync -av -e "ssh -p YOUR_SSH_PORT" --exclude='.venv' --exclude='data' --exclude='__pycache__' --exclude='.git' /path/to/Nas_search/ "YOUR_NAS_USER@YOUR_NAS_IP:/volume1/docker/nas-search/"
```

Replace the placeholders with your own values. If your SSH port is the default 22, you can omit `-e "ssh -p ..."`.

If rsync fails (some Synology setups don't support it), use this alternative — run a temporary HTTP server on your local machine:

```bash
cd /path/to/Nas_search && python3 -m http.server 9999
```

Then SSH into the NAS and download individual files with wget:

```bash
cd /volume1/docker/nas-search
sudo wget -O filename http://YOUR_LOCAL_IP:9999/filename
```

### Step 2: Configure volume mounts

Edit `docker-compose.yml` on the NAS to map your folders. The key section is the `volumes` list:

```yaml
volumes:
  # Persistent database storage
  - nas_search_data:/app/data

  # Config file (persists across rebuilds)
  - ./config.yml:/app/config.yml

  # NAS folders (read-only) — adjust to match your NAS paths
  - /volume1/Books:/mnt/nas/Books:ro
  - /volume1/Movies:/mnt/nas/Movies:ro
```

The format is `NAS_PATH:CONTAINER_PATH:ro`:
- **Left side**: The real path on your NAS. Find it by right-clicking a folder in File Station > Properties > Location.
- **Right side**: Where the folder appears inside the container. Always use `/mnt/nas/...`.
- **`:ro`**: Read-only. The app never writes to your folders.

**Important**: Each top-level NAS shared folder needs its own mount. You cannot mount a read-only volume and then mount a sub-path inside it — Docker will fail with a read-only filesystem error.

### Step 3: Configure indexed folders

Copy `config.example.yml` to `config.yml` and edit it. The `indexed_folders` paths must match the **container paths** (right side) from docker-compose.yml:

```yaml
indexed_folders:
  Books: /mnt/nas/Books
  Movies: /mnt/nas/Movies
```

### Step 4: Configure path mappings in the frontend

Edit `frontend/app.js` and update the `PATH_MAPPINGS` array near the top of the file. This maps container paths back to NAS shared folder paths so that File Station and viewer links work correctly:

```javascript
const PATH_MAPPINGS = [
    { container: '/mnt/nas/Books', nas: '/Books' },
    { container: '/mnt/nas/Movies', nas: '/Movies' },
];
```

If your DSM web port is not 5000 (the default), also update `NAS_PORT`:

```javascript
const NAS_PORT = 5000;
```

### Step 5: Build and start

SSH into the NAS and run:

```bash
cd /volume1/docker/nas-search
sudo docker-compose down && sudo docker-compose up -d --build
```

First build takes 2-3 minutes (downloads Python 3.11 base image, FFmpeg, unrar, and p7zip). Subsequent builds are faster.

### Step 6: First index

Open `http://YOUR_NAS_IP:8080` in your browser. Click **Reindex** (bottom-right) to trigger the first scan. The status bar shows progress. For ~100k files expect 1-3 minutes.

### Updating after code changes

Copy updated files to the NAS (Step 1), then rebuild:

```bash
cd /volume1/docker/nas-search
sudo docker-compose down && sudo docker-compose up -d --build
```

A simple `docker restart` does **not** pick up file changes — you must rebuild with `--build`.

**Note**: Synology Container Manager may send a "stopped unexpectedly" email when rebuilding, even with a clean `docker-compose down`. This is a Synology notification behavior — it treats any container removal as unexpected. To disable these alerts: open **Container Manager > Container > nas-search > Settings** and uncheck the restart alert option. Alternatively, disable the rule globally in **Control Panel > Notification > Rules**.

## Usage

- **Search**: Type in the search box. Results appear as you type (300ms debounce).
- **Filter by folder**: Use the folder dropdown to restrict results to a specific collection.
- **Filter by type**: Use the extension dropdown to show only epub, pdf, mp4, etc.
- **Fuzzy search**: Tick the "Fuzzy" checkbox when you're unsure of exact spelling.
- **Open a file**: Click "Open" to launch the file in the appropriate viewer:
  - Epub opens in the built-in reader (chapter nav, font size, reading position saved)
  - PDF opens in the built-in reader (page nav, zoom, bookmarks)
  - MP4, WebM, MOV open in Synology VideoPlayer (native browser playback)
  - MKV, AVI, WMV, FLV open in the built-in player (transcoded via FFmpeg)
  - CBZ, CBR, CB7 open in the built-in comic reader (server-side extraction)
  - MP3 opens in the built-in audiobook player (position auto-saved)
- **Audiobooks tab**: Switch to the Audiobooks tab to browse your library with cover art, progress bars, and series grouping. Filter by status (All / In Progress / Finished / Not Started), sort by title, author, recently played, duration, or series. Search within your audiobook library.
- **Audiobook player**: Play/pause, seek, skip forward/back (10/15/30s), adjust speed (0.5x–3x). Navigate by chapter (embedded or per-file). Set a sleep timer. Mark books as finished. Progress syncs across devices automatically.
- **Bookmarks** (PDF, epub, comic, audiobook): All readers share the same bookmark workflow. A collapsible panel on the right shows all bookmarks across all files of that type, grouped by file. Bookmark the current position with an optional description. When jumping to a bookmark, you're prompted to delete it. When navigating away without a bookmark near your current position, you're prompted to save one. Bookmarks are stored server-side in SQLite for cross-device sync.
- **Audiobook bookmarks**: A persistent bookmarks panel on the right side of the player shows all bookmarks across all audiobooks, grouped by book. Bookmark the current position with an optional description. When resuming from a bookmark, you're prompted to delete it. When navigating away without a bookmark, you're prompted to save one.
- **Open the folder**: Click "Folder" to navigate to the file's location in Synology File Station.
- **Pin folders**: Click "Pin" on a result to save that folder as a sidebar shortcut. Remove individual pins with the "x" next to each, or clear all with the "x" in the header.
- **Recent files**: Files you open are saved to a recent files list in the sidebar. Remove individual entries with the "x" next to each, or clear all with the "x" in the header.
- **Reindex**: Click "Reindex" (bottom-right) to trigger a manual full scan.
- **Settings**: Click "Settings" to modify indexed folders, file extensions, and the nightly reindex schedule.

## Common Operations

### View logs

```bash
sudo docker logs nas-search        # recent logs
sudo docker logs -f nas-search     # follow in real-time
```

Logs are also written to a rotating file inside the container at `/app/data/nas_search.log` (5MB, 3 backups).

### Stop / restart

```bash
cd /volume1/docker/nas-search
sudo docker-compose restart         # restart
sudo docker-compose down            # stop and remove container
sudo docker-compose up -d           # start again
```

### Add a new folder

1. Add the volume mount in `docker-compose.yml`
2. Add the folder in `config.yml` (or via the Settings UI after restart)
3. Update `PATH_MAPPINGS` in `frontend/app.js`
4. Rebuild: `sudo docker-compose up -d --build`
5. Click **Reindex** in the web UI

### Change the reindex schedule

Edit `config.yml`:

```yaml
schedule_hour: 3
schedule_minute: 30
```

Then restart: `sudo docker-compose restart`

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Connection refused" on port 8080 | Check container is running: `sudo docker ps`. Check logs: `sudo docker logs nas-search`. Verify port 8080 isn't used by another app. |
| No search results after indexing | Verify folder paths in Settings match the container mount paths. Check extensions list includes your file types. Check logs for "Folder not found" errors. |
| File Station / Open links don't work | Verify `PATH_MAPPINGS` in `app.js` correctly maps container paths to NAS paths. Check `NAS_PORT` matches your DSM web port (default 5000). |
| Video won't play in built-in player | Check logs: `sudo docker logs nas-search`. FFmpeg may be failing on the file. Try a different file to isolate the issue. |
| Comic reader shows error | Check logs. The archive may be corrupt, or use an unsupported compression method. CBZ (ZIP) and CBR (RAR v4/v5) are supported. |
| Docker build fails with read-only error | You cannot mount a sub-path inside a read-only mount. Give each NAS shared folder its own volume mount line. |
| Indexing seems stuck | Check logs: `sudo docker logs -f nas-search`. Large collections (500k+ files) can take 10-15 minutes on the first full scan. |
| Container won't start after NAS reboot | The `restart: unless-stopped` policy handles this automatically. If not: `cd /volume1/docker/nas-search && sudo docker-compose up -d` |
| Changes not showing after update | You must rebuild with `sudo docker-compose up -d --build`. A plain `docker restart` does not copy new files into the container. |
| Audiobook not appearing in library | Ensure `mp3` is in the extensions list in `config.yml`. Reindex after adding it. MP3 files must be in a folder together (one folder = one audiobook). |
| Audiobook progress not saving | Check browser console and server logs. The SQLite database must be writable. Progress auto-saves every 5 seconds. |
| No cover art on audiobook cards | Cover art is extracted from ID3 APIC tags in the first MP3 file. Not all MP3 files have embedded cover art. |
| Chapters not showing in player | Chapters come from embedded ID3 CHAP frames. If a file has no CHAP frames, the entire file is treated as one chapter. |

## Tech Stack

- **Backend**: Python 3.11, FastAPI, uvicorn
- **Database**: SQLite with FTS5 and WAL journal mode
- **Fuzzy search**: rapidfuzz (Levenshtein distance)
- **Video streaming**: FFmpeg (remux H.264, transcode other codecs)
- **PDF reader**: PDF.js (client-side rendering via CDN)
- **Epub reader**: epub.js + JSZip (client-side rendering)
- **Comic reader**: Server-side extraction with unrar-free and p7zip
- **Audiobook metadata**: mutagen (MP3 ID3 tag reading, chapter extraction)
- **Scheduling**: APScheduler
- **Frontend**: Vanilla HTML, CSS, JavaScript (no build tools)
- **Deployment**: Docker on Synology NAS
