# Search Wizard

A fast, lightweight search tool for finding files across a Synology NAS. Built to replace Synology's built-in Universal Search, which becomes unusable with tens of thousands of files — returning overwhelming result lists with no meaningful way to filter by folder or file type.

Search Wizard solves this by providing:

- **Instant search** (<100ms) across hundreds of thousands of files using SQLite FTS5
- **Fuzzy matching** for when you can't remember the exact title or spelling
- **Folder filtering** to narrow results to specific collections
- **Direct file opening** — launch files in Synology's native viewers (PDFViewer for PDF/epub, VideoPlayer for video files)
- **Folder navigation** — jump to any result's location in Synology File Station
- **Automated reindexing** so results stay current without manual intervention

## Screenshot

The interface is a single-page dark-themed web app with type-ahead search, filter dropdowns, pinned folder shortcuts, and recent file history.

## Architecture

```
┌──────────────────────────────────────────────────┐
│                  Docker Container                │
│                                                  │
│  ┌──────────────┐        ┌────────────────────┐  │
│  │   Frontend    │        │     Backend        │  │
│  │              │        │                    │  │
│  │  index.html  │  HTTP  │  FastAPI (Python)  │  │
│  │  app.js      │◄──────►│  uvicorn :8080     │  │
│  │  style.css   │        │                    │  │
│  └──────────────┘        │  ┌──────────────┐  │  │
│                          │  │  SQLite DB   │  │  │
│                          │  │  + FTS5      │  │  │
│                          │  └──────────────┘  │  │
│                          │                    │  │
│                          │  ┌──────────────┐  │  │
│                          │  │  Scheduler   │  │  │
│                          │  │  (APScheduler│  │  │
│                          │  │  cron 02:00) │  │  │
│                          │  └──────────────┘  │  │
│                          └────────────────────┘  │
│                                   │              │
│                          /mnt/nas/Books (ro)     │
└──────────────────────────┼───────────────────────┘
                           │
                    ┌──────┴──────┐
                    │  NAS Volume │
                    │  /volume1/  │
                    └─────────────┘
```

### Components

**Frontend** — Vanilla HTML/CSS/JavaScript. No build tools, no framework. Served as static files by FastAPI. All state (pinned folders, recent files) stored in the browser's localStorage.

**Backend** — Python 3.11 with FastAPI. Handles search queries, file indexing, configuration, and serves the frontend. Runs on uvicorn.

**Database** — SQLite with WAL journal mode for concurrent reads. Uses FTS5 (Full Text Search 5) virtual tables with automatic sync triggers. The database file is stored in a named Docker volume so it persists across container rebuilds.

**Indexer** — Walks configured folders, reads file metadata (name, path, size, modified date, extension), and upserts into the database. Supports incremental scans (using directory mtime to skip unchanged directories) and full scans. Runs in a background thread to avoid blocking the API.

**Scheduler** — APScheduler with a cron trigger. Runs a full reindex at a configurable time (default 02:00).

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
| GET | `/api/search` | Search files (params: q, folder, extension, fuzzy, limit, offset) |
| POST | `/api/index` | Trigger a manual reindex |
| GET | `/api/status` | Get index status (file count, last index time, indexing state) |
| GET | `/api/folders` | List configured top-level folders |
| GET | `/api/extensions` | List distinct file extensions in the index |
| GET | `/api/recent` | Get recently modified files |
| POST | `/api/track-click` | Record a folder click for usage-based ranking |
| GET | `/api/config` | Get current configuration |
| PUT | `/api/config` | Update configuration |

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
│   └── search.py           # FTS5 + fuzzy search logic
├── frontend/
│   ├── index.html          # Single-page UI
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

- Synology NAS running DSM 7+
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

Then SSH into the NAS and download:

```bash
ssh -p YOUR_SSH_PORT "YOUR_NAS_USER@YOUR_NAS_IP"
sudo mkdir -p /volume1/docker/nas-search && cd /volume1/docker/nas-search
wget -r -np -nH --cut-dirs=0 -R "index.html*" http://YOUR_LOCAL_IP:9999/
```

### Step 2: Configure volume mounts

Edit `docker-compose.yml` on the NAS to map your actual book folders. The key section is the `volumes` list:

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
- **`:ro`**: Read-only. The app never writes to your book folders.

### Step 3: Configure indexed folders

Copy `config.example.yml` to `config.yml` and edit it. The `indexed_folders` paths must match the **container paths** (right side) from docker-compose.yml:

```yaml
indexed_folders:
  Books: /mnt/nas/Books
  Movies: /mnt/nas/Movies
```

### Step 4: Configure path mappings in the frontend

Edit `frontend/app.js` and update the `PATH_MAPPINGS` array near the top of the file. This maps container paths back to NAS shared folder paths so that File Station and PDFViewer links work correctly:

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
sudo docker-compose up -d --build
```

First build takes 1-2 minutes (downloads the Python 3.11 base image). Subsequent builds are faster.

### Step 6: First index

Open `http://YOUR_NAS_IP:8080` in your browser. Click **Reindex** (bottom-right) to trigger the first scan. The status bar shows progress. For ~100k files expect 1-3 minutes.

### Updating after code changes

Copy updated files to the NAS (Step 1), then rebuild:

```bash
cd /volume1/docker/nas-search && sudo docker-compose up -d --build
```

A simple `docker restart` does **not** pick up file changes — you must rebuild with `--build`.

## Usage

- **Search**: Type in the search box. Results appear as you type (300ms debounce).
- **Filter by folder**: Use the folder dropdown to restrict results to a specific collection.
- **Filter by type**: Use the extension dropdown to show only epub, pdf, etc.
- **Fuzzy search**: Tick the "Fuzzy" checkbox when you're unsure of exact spelling.
- **Open a file**: Click "Open" to launch the file in the appropriate Synology viewer (PDFViewer for PDF/epub, VideoPlayer for video files).
- **Open the folder**: Click "Folder" to navigate to the file's location in Synology File Station.
- **Pin folders**: Click "Pin" on a result to save that folder as a sidebar shortcut. Click "x" next to a pinned folder to remove it.
- **Recent files**: Files you open are saved to a recent files list in the sidebar. Click the "x" to clear.
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
3. Rebuild: `sudo docker-compose up -d --build`
4. Click **Reindex** in the web UI

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
| Indexing seems stuck | Check logs: `sudo docker logs -f nas-search`. Large collections (500k+ files) can take 10-15 minutes on the first full scan. |
| Container won't start after NAS reboot | The `restart: unless-stopped` policy handles this automatically. If not: `cd /volume1/docker/nas-search && sudo docker-compose up -d` |
| Changes not showing after update | You must rebuild with `sudo docker-compose up -d --build`. A plain `docker restart` does not copy new files into the container. |

## Tech Stack

- **Backend**: Python 3.11, FastAPI, uvicorn
- **Database**: SQLite with FTS5 and WAL journal mode
- **Fuzzy search**: rapidfuzz (Levenshtein distance)
- **Scheduling**: APScheduler
- **Frontend**: Vanilla HTML, CSS, JavaScript (no build tools)
- **Deployment**: Docker on Synology NAS
