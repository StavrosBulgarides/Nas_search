const API = '';
// ── Debug Log ──
const _debugLines = [];
function debugLog(msg) {
    const ts = new Date().toLocaleTimeString('en-GB', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
    const line = `[${ts}] ${msg}`;
    _debugLines.push(line);
    if (_debugLines.length > 200) _debugLines.shift();
    const el = document.getElementById('debug-log');
    if (el) {
        el.textContent = _debugLines.join('\n');
        el.scrollTop = el.scrollHeight;
    }
    console.log('[DBG]', msg);
}
// Inject debug panel into page once DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    const panel = document.createElement('div');
    panel.id = 'debug-panel';
    panel.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <strong style="color:#e94560;font-size:0.7rem;">Debug Log</strong>
            <div style="display:flex;gap:6px;">
                <button id="debug-clear-btn" style="background:none;border:1px solid #555;color:#aaa;cursor:pointer;padding:2px 8px;font-size:0.7rem;display:none;">Clear</button>
                <button id="debug-toggle-btn" style="background:none;border:1px solid #555;color:#aaa;cursor:pointer;padding:2px 8px;font-size:0.7rem;">Show</button>
            </div>
        </div>
        <pre id="debug-log" style="margin:0;max-height:200px;overflow-y:auto;font-size:0.7rem;line-height:1.3;color:#aaa;white-space:pre-wrap;word-break:break-all;display:none;margin-top:4px;"></pre>
    `;
    panel.style.cssText = 'position:fixed;bottom:0;left:0;right:0;background:#111;border-top:1px solid #333;padding:6px 12px;z-index:9999;font-family:monospace;';
    document.body.appendChild(panel);
    document.getElementById('debug-toggle-btn').addEventListener('click', () => {
        const log = document.getElementById('debug-log');
        const clearBtn = document.getElementById('debug-clear-btn');
        if (log.style.display === 'none') { log.style.display = ''; clearBtn.style.display = ''; document.getElementById('debug-toggle-btn').textContent = 'Hide'; }
        else { log.style.display = 'none'; clearBtn.style.display = 'none'; document.getElementById('debug-toggle-btn').textContent = 'Show'; }
    });
    document.getElementById('debug-clear-btn').addEventListener('click', () => {
        _debugLines.length = 0;
        document.getElementById('debug-log').textContent = '';
    });
    debugLog('App initialised');
});

let searchTimeout = null;
let currentOffset = 0;
let currentTotal = 0;
let currentQuery = '';
let pinnedFolders = JSON.parse(localStorage.getItem('pinnedFolders') || '[]');
// NAS base URL for File Station links — auto-detected from current host
const NAS_HOST = window.location.hostname;
const NAS_PORT = 5000;
// Maps container mount paths back to NAS shared folder paths for File Station / viewer links
// Adjust these to match your docker-compose.yml volume mounts and NAS shared folder names
const PATH_MAPPINGS = [
    { container: '/mnt/nas/Stephen', nas: '/Stephen' },
    { container: '/mnt/nas/Movies', nas: '/Movies' },
];

// ── Init ──

document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadFilters();
    loadRecentFiles();
    renderPinnedFolders();
    setupEventListeners();
    setupTabs();
    setupAudiobookSearch();
});

function setupEventListeners() {
    const searchInput = document.getElementById('search-input');
    searchInput.addEventListener('input', () => {
        debugLog(`EVENT: search input changed -> "${searchInput.value}"`);
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => doSearch(false), 300);
    });
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            debugLog('EVENT: search Enter pressed');
            clearTimeout(searchTimeout);
            doSearch(false);
        }
    });

    document.getElementById('folder-filter').addEventListener('change', (e) => {
        debugLog(`EVENT: folder filter changed -> "${e.target.value}"`);
        clearTimeout(searchTimeout);
        doSearch(false);
    });
    document.getElementById('extension-filter').addEventListener('change', (e) => {
        debugLog(`EVENT: extension filter changed -> "${e.target.value}"`);
        clearTimeout(searchTimeout);
        doSearch(false);
    });
    document.getElementById('fuzzy-toggle').addEventListener('change', (e) => {
        debugLog(`EVENT: fuzzy toggle changed -> ${e.target.checked}`);
        clearTimeout(searchTimeout);
        doSearch(false);
    });

    document.getElementById('load-more-btn').addEventListener('click', () => doSearch(true));

    document.getElementById('reindex-btn').addEventListener('click', triggerReindex);
    document.getElementById('settings-btn').addEventListener('click', openSettings);
    document.getElementById('cancel-settings-btn').addEventListener('click', closeSettings);
    document.getElementById('save-settings-btn').addEventListener('click', saveSettings);
    document.getElementById('add-folder-btn').addEventListener('click', addFolderRow);

    document.getElementById('enable-fuzzy-link').addEventListener('click', (e) => {
        e.preventDefault();
        document.getElementById('fuzzy-toggle').checked = true;
        doSearch(false);
    });

    // Clear recent files
    document.getElementById('clear-recent-btn').addEventListener('click', () => {
        localStorage.removeItem('recentFiles');
        loadRecentFiles();
    });

    // Clear all pinned folders
    document.getElementById('clear-pinned-btn').addEventListener('click', () => {
        pinnedFolders = [];
        localStorage.setItem('pinnedFolders', JSON.stringify(pinnedFolders));
        renderPinnedFolders();
    });

    // Clear search button
    const clearBtn = document.getElementById('clear-search-btn');
    clearBtn.addEventListener('click', () => {
        document.getElementById('search-input').value = '';
        clearBtn.style.display = 'none';
        clearResults();
        document.getElementById('search-input').focus();
    });

    // Show/hide clear button based on input content
    document.getElementById('search-input').addEventListener('input', () => {
        clearBtn.style.display = document.getElementById('search-input').value ? '' : 'none';
    });
}

// ── Search ──

let searchId = 0;

async function doSearch(loadMore) {
    const query = document.getElementById('search-input').value.trim();
    const folder = document.getElementById('folder-filter').value;
    const extension = document.getElementById('extension-filter').value;

    debugLog(`doSearch called: q="${query}" folder="${folder}" ext="${extension}" loadMore=${loadMore}`);

    if (!query && !folder && !extension) {
        debugLog('doSearch: no query/folder/ext -> clearing results');
        clearResults();
        return;
    }

    const thisSearch = ++searchId;
    debugLog(`doSearch: searchId=${thisSearch}`);

    if (!loadMore) {
        currentOffset = 0;
        currentQuery = query;
    }

    const fuzzy = document.getElementById('fuzzy-toggle').checked;

    const params = new URLSearchParams({
        q: query,
        limit: '20',
        offset: String(currentOffset),
        fuzzy: String(fuzzy),
    });
    if (folder) params.set('folder', folder);
    if (extension) params.set('extension', extension);

    const url = `${API}/api/search?${params}`;
    debugLog(`doSearch: fetching ${url}`);

    try {
        const resp = await fetch(url);
        debugLog(`doSearch: response status=${resp.status} (searchId=${thisSearch}, current=${searchId})`);
        if (thisSearch !== searchId) {
            debugLog(`doSearch: STALE response (thisSearch=${thisSearch} != searchId=${searchId}), discarding`);
            return;
        }
        const data = await resp.json();
        debugLog(`doSearch: got ${data.results?.length ?? 0} results, total=${data.total}`);
        if (thisSearch !== searchId) {
            debugLog(`doSearch: STALE after json parse, discarding`);
            return;
        }
        currentTotal = data.total;

        if (!loadMore) {
            document.getElementById('results-body').innerHTML = '';
        }

        if (data.results.length === 0 && currentOffset === 0) {
            debugLog('doSearch: no results, showing empty state');
            showNoResults(fuzzy);
        } else {
            hideNoResults();
            renderResults(data.results);
            currentOffset += data.results.length;
            debugLog(`doSearch: rendered ${data.results.length} results, offset now ${currentOffset}`);
        }

        document.getElementById('results-info').textContent = '';

        const loadMoreBtn = document.getElementById('load-more-btn');
        loadMoreBtn.style.display = currentOffset < currentTotal ? '' : 'none';

    } catch (err) {
        debugLog(`doSearch: ERROR ${err.message}`);
        console.error('Search failed:', err);
    }
}

function renderResults(results) {
    const tbody = document.getElementById('results-body');
    for (const file of results) {
        const tr = document.createElement('tr');

        const fileStationUrl = buildFileStationUrl(file.folder_path);
        const openFileUrl = buildOpenFileUrl(file.full_path, file.extension);
        const modified = formatDate(file.modified_date);
        const size = formatSize(file.size);

        // Shorten folder display to last 3 segments
        const folderDisplay = shortenPath(file.folder_path);

        tr.innerHTML = `
            <td class="filename-cell" title="${escHtml(file.full_path)}">${escHtml(file.filename)}</td>
            <td class="folder-cell" title="${escHtml(file.folder_path)}">${escHtml(folderDisplay)}</td>
            <td class="size-cell">${size}</td>
            <td class="date-cell">${modified}</td>
            <td class="actions-cell">
                <a href="${openFileUrl}" target="_blank" class="open-link">Open</a>
                <a href="${fileStationUrl}" target="_blank" class="folder-link">Folder</a>
                <button class="pin-btn" title="Pin this folder" data-folder="${escAttr(file.folder_path)}">Pin</button>
            </td>
        `;

        // Track click on both links
        tr.querySelector('.open-link').addEventListener('click', () => {
            trackClick(file.folder_path);
            addToRecentFiles(file);
        });
        tr.querySelector('.folder-link').addEventListener('click', () => {
            trackClick(file.folder_path);
        });

        tr.querySelector('.pin-btn').addEventListener('click', (e) => {
            pinFolder(e.target.dataset.folder);
        });

        tbody.appendChild(tr);
    }
}

function clearResults() {
    document.getElementById('results-body').innerHTML = '';
    document.getElementById('results-info').textContent = '';
    document.getElementById('load-more-btn').style.display = 'none';
    hideNoResults();
}

function showNoResults(fuzzyEnabled) {
    document.getElementById('no-results').style.display = '';
    document.getElementById('results-table').style.display = 'none';
    document.getElementById('fuzzy-suggestion').style.display = fuzzyEnabled ? 'none' : '';
}

function hideNoResults() {
    document.getElementById('no-results').style.display = 'none';
    document.getElementById('results-table').style.display = '';
}

// ── Filters ──

async function loadFilters() {
    try {
        const [foldersResp, extResp] = await Promise.all([
            fetch(`${API}/api/folders`),
            fetch(`${API}/api/extensions`),
        ]);
        const foldersData = await foldersResp.json();
        const extData = await extResp.json();

        const folderSelect = document.getElementById('folder-filter');
        // Clear existing options (keep the first "All folders" option)
        while (folderSelect.options.length > 1) folderSelect.remove(1);
        for (const f of foldersData.folders) {
            const opt = document.createElement('option');
            opt.value = f.path;
            opt.textContent = f.label;
            folderSelect.appendChild(opt);
        }

        const extSelect = document.getElementById('extension-filter');
        while (extSelect.options.length > 1) extSelect.remove(1);
        for (const ext of extData.extensions) {
            const opt = document.createElement('option');
            opt.value = ext;
            opt.textContent = `.${ext}`;
            extSelect.appendChild(opt);
        }
    } catch (err) {
        console.error('Failed to load filters:', err);
    }
}

// ── Status ──

async function loadStatus() {
    try {
        const resp = await fetch(`${API}/api/status`);
        const data = await resp.json();
        document.getElementById('file-count').textContent = data.total_files.toLocaleString();
        if (data.indexing_in_progress) {
            document.getElementById('index-status').textContent = '(indexing...)';
        }
    } catch (err) {
        console.error('Failed to load status:', err);
    }
}

// ── Recent Files ──

function loadRecentFiles() {
    const recentFiles = JSON.parse(localStorage.getItem('recentFiles') || '[]');
    const ul = document.getElementById('recent-list');
    ul.innerHTML = '';
    if (recentFiles.length === 0) {
        const li = document.createElement('li');
        li.textContent = 'None yet';
        li.style.color = '#555';
        ul.appendChild(li);
        return;
    }
    for (const file of recentFiles) {
        const li = document.createElement('li');
        li.classList.add('pinned-item');

        const name = document.createElement('span');
        name.textContent = file.filename;
        name.title = file.full_path;
        name.addEventListener('click', () => {
            document.getElementById('search-input').value = file.filename.replace(/\.[^.]+$/, '');
            doSearch(false);
        });

        const remove = document.createElement('span');
        remove.classList.add('unpin');
        remove.textContent = 'x';
        remove.addEventListener('click', () => {
            let rf = JSON.parse(localStorage.getItem('recentFiles') || '[]');
            rf = rf.filter(f => f.full_path !== file.full_path);
            localStorage.setItem('recentFiles', JSON.stringify(rf));
            loadRecentFiles();
        });

        li.appendChild(name);
        li.appendChild(remove);
        ul.appendChild(li);
    }
}

function addToRecentFiles(file) {
    let recentFiles = JSON.parse(localStorage.getItem('recentFiles') || '[]');
    // Remove if already present
    recentFiles = recentFiles.filter(f => f.full_path !== file.full_path);
    // Add to front
    recentFiles.unshift({ filename: file.filename, full_path: file.full_path });
    // Keep max 10
    recentFiles = recentFiles.slice(0, 10);
    localStorage.setItem('recentFiles', JSON.stringify(recentFiles));
    loadRecentFiles();
}

// ── Pinned Folders ──

function renderPinnedFolders() {
    const ul = document.getElementById('pinned-list');
    ul.innerHTML = '';
    if (pinnedFolders.length === 0) {
        const li = document.createElement('li');
        li.textContent = 'None yet';
        li.style.color = '#555';
        ul.appendChild(li);
        return;
    }
    for (const folder of pinnedFolders) {
        const li = document.createElement('li');
        li.classList.add('pinned-item');

        const name = document.createElement('span');
        name.textContent = shortenPath(folder);
        name.title = folder;
        name.addEventListener('click', () => {
            document.getElementById('folder-filter').value = folder;
            doSearch(false);
        });

        const unpin = document.createElement('span');
        unpin.classList.add('unpin');
        unpin.textContent = 'x';
        unpin.addEventListener('click', () => {
            pinnedFolders = pinnedFolders.filter(f => f !== folder);
            localStorage.setItem('pinnedFolders', JSON.stringify(pinnedFolders));
            renderPinnedFolders();
        });

        li.appendChild(name);
        li.appendChild(unpin);
        ul.appendChild(li);
    }
}

function pinFolder(folder) {
    if (!pinnedFolders.includes(folder)) {
        pinnedFolders.push(folder);
        localStorage.setItem('pinnedFolders', JSON.stringify(pinnedFolders));
        renderPinnedFolders();
    }
}

// ── Track Click ──

async function trackClick(folderPath) {
    try {
        await fetch(`${API}/api/track-click`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_path: folderPath }),
        });
    } catch (err) {
        // Non-critical
    }
}

// ── Reindex ──

async function triggerReindex() {
    const btn = document.getElementById('reindex-btn');
    btn.disabled = true;
    btn.textContent = 'Indexing...';
    document.getElementById('index-status').textContent = '(indexing...)';

    try {
        await fetch(`${API}/api/index?full=true`, { method: 'POST' });
        // Poll for completion
        pollIndexStatus();
    } catch (err) {
        console.error('Reindex failed:', err);
        btn.disabled = false;
        btn.textContent = 'Reindex';
    }
}

function pollIndexStatus() {
    const interval = setInterval(async () => {
        try {
            const resp = await fetch(`${API}/api/status`);
            const data = await resp.json();
            document.getElementById('file-count').textContent = data.total_files.toLocaleString();
            if (!data.indexing_in_progress) {
                clearInterval(interval);
                document.getElementById('index-status').textContent = '';
                const btn = document.getElementById('reindex-btn');
                btn.disabled = false;
                btn.textContent = 'Reindex';
                // Refresh filters
                loadFilters();
                loadRecentFiles();
            }
        } catch (err) {
            clearInterval(interval);
        }
    }, 2000);
}

// ── Settings Modal ──

async function openSettings() {
    try {
        const resp = await fetch(`${API}/api/config`);
        const cfg = await resp.json();

        // Populate folders
        const container = document.getElementById('folders-config');
        container.innerHTML = '';
        const folders = cfg.indexed_folders || {};
        for (const [label, path] of Object.entries(folders)) {
            addFolderRowWithValues(label, path);
        }

        // Extensions
        document.getElementById('extensions-input').value =
            (cfg.extensions || []).join(', ');

        // Schedule
        document.getElementById('schedule-hour').value = cfg.schedule_hour || 2;
        document.getElementById('schedule-minute').value = cfg.schedule_minute || 0;

        document.getElementById('settings-modal').classList.remove('hidden');
    } catch (err) {
        console.error('Failed to load config:', err);
        alert('Failed to load settings: ' + err.message);
    }
}

function closeSettings() {
    document.getElementById('settings-modal').classList.add('hidden');
}

function addFolderRow() {
    addFolderRowWithValues('', '');
}

function addFolderRowWithValues(label, path) {
    const container = document.getElementById('folders-config');
    const row = document.createElement('div');
    row.classList.add('folder-row');
    row.innerHTML = `
        <input type="text" placeholder="Label" value="${escAttr(label)}">
        <input type="text" placeholder="/volume1/Books" value="${escAttr(path)}">
        <button class="remove-folder-btn">x</button>
    `;
    row.querySelector('.remove-folder-btn').addEventListener('click', () => row.remove());
    container.appendChild(row);
}

async function saveSettings() {
    const rows = document.querySelectorAll('#folders-config .folder-row');
    const folders = {};
    for (const row of rows) {
        const inputs = row.querySelectorAll('input');
        const label = inputs[0].value.trim();
        const path = inputs[1].value.trim();
        if (label && path) folders[label] = path;
    }

    const extensions = document.getElementById('extensions-input').value
        .split(',')
        .map(s => s.trim().toLowerCase())
        .filter(Boolean);

    const cfg = {
        indexed_folders: folders,
        extensions: extensions,
        schedule_hour: parseInt(document.getElementById('schedule-hour').value) || 2,
        schedule_minute: parseInt(document.getElementById('schedule-minute').value) || 0,
        max_results: 100,
        fuzzy_threshold: 80,
        host: '0.0.0.0',
        port: 8080,
    };

    try {
        await fetch(`${API}/api/config`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cfg),
        });
        closeSettings();
        loadFilters();
    } catch (err) {
        console.error('Failed to save config:', err);
    }
}

// ── Helpers ──

function containerToNasPath(containerPath) {
    let nasPath = containerPath;
    for (const mapping of PATH_MAPPINGS) {
        if (containerPath.startsWith(mapping.container)) {
            nasPath = containerPath.replace(mapping.container, mapping.nas);
            break;
        }
    }
    return nasPath;
}

function buildFileStationUrl(folderPath) {
    const nasPath = containerToNasPath(folderPath);
    const encodedPath = encodeURIComponent('openfile=' + nasPath);
    return `http://${NAS_HOST}:${NAS_PORT}/?launchApp=SYNO.SDS.App.FileStation3.Instance&launchParam=${encodedPath}`;
}

// Formats browsers can play natively — use Synology VideoPlayer
const NATIVE_VIDEO = ['mp4', 'webm', 'mov'];
// Formats that need transcoding — use built-in player with ffmpeg
const TRANSCODE_VIDEO = ['mkv', 'avi', 'wmv', 'flv'];
// Comic book archives — use built-in reader
const COMIC_EXTENSIONS = ['cbz', 'cbr', 'cb7'];
// Epub — use built-in epub reader
const EPUB_EXTENSIONS = ['epub'];
// PDF — use built-in PDF reader
const PDF_EXTENSIONS = ['pdf'];
// Audio — use built-in audiobook player
const AUDIO_EXTENSIONS = ['mp3'];

function buildOpenFileUrl(fullPath, extension) {
    const ext = (extension || '').toLowerCase();
    const nasPath = containerToNasPath(fullPath);

    if (AUDIO_EXTENSIONS.includes(ext)) {
        // Open in audiobook player — folder is the book, file is the starting track
        const folder = fullPath.substring(0, fullPath.lastIndexOf('/'));
        return `/audiobook-player?folder=${encodeURIComponent(folder)}&file=${encodeURIComponent(fullPath)}`;
    }

    if (EPUB_EXTENSIONS.includes(ext)) {
        return `/epub-reader?path=${encodeURIComponent(fullPath)}`;
    }

    if (COMIC_EXTENSIONS.includes(ext)) {
        return `/reader?path=${encodeURIComponent(fullPath)}`;
    }

    if (PDF_EXTENSIONS.includes(ext)) {
        return `/pdf-reader?path=${encodeURIComponent(fullPath)}`;
    }

    if (TRANSCODE_VIDEO.includes(ext)) {
        return `/player?path=${encodeURIComponent(fullPath)}`;
    }

    if (NATIVE_VIDEO.includes(ext)) {
        const encodedPath = encodeURIComponent(nasPath);
        const launchParam = encodeURIComponent('ieMode=9&is_drive=false&path=' + encodedPath + '&file_id=' + encodedPath);
        return `http://${NAS_HOST}:${NAS_PORT}/?launchApp=SYNO.SDS.VideoPlayer2.Application&launchParam=${launchParam}&ieMode=9`;
    }

    // Other files — Synology viewer fallback
    const encodedNasPath = encodeURIComponent(nasPath);
    const launchParam = encodeURIComponent('path=' + encodedNasPath);
    return `http://${NAS_HOST}:${NAS_PORT}/?launchApp=SYNO.SDS.PDFViewer.Application&launchParam=${launchParam}`;
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB';
}

function formatDate(timestamp) {
    const d = new Date(timestamp * 1000);
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

function shortenPath(path) {
    const parts = path.split('/').filter(Boolean);
    if (parts.length <= 3) return '/' + parts.join('/');
    return '.../' + parts.slice(-3).join('/');
}

function escHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escAttr(str) {
    return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;');
}

// ── Audiobooks Tab ──

function setupTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('search-view').style.display = tab === 'search' ? '' : 'none';
            document.getElementById('audiobooks-view').style.display = tab === 'audiobooks' ? '' : 'none';
            if (tab === 'audiobooks') loadAudiobooks();
        });
    });
}

let audiobooksLoaded = false;
let abSearchTimeout = null;

function setupAudiobookSearch() {
    const input = document.getElementById('ab-search');
    if (!input) return;
    input.addEventListener('input', () => {
        clearTimeout(abSearchTimeout);
        abSearchTimeout = setTimeout(() => loadAudiobooks(), 300);
    });
}

function formatDuration(secs) {
    if (!secs || isNaN(secs)) return '0m';
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}

async function loadAudiobooks() {
    const container = document.getElementById('audiobooks-grid');
    if (!audiobooksLoaded) {
        container.innerHTML = '<p style="color:#888;text-align:center;padding:40px">Loading audiobooks...</p>';
    }

    try {
        const sortValue = document.getElementById('audiobook-sort')?.value || 'title';
        const searchValue = document.getElementById('ab-search')?.value?.trim() || '';

        const params = new URLSearchParams({ sort: sortValue });
        if (searchValue) params.set('search', searchValue);

        const resp = await fetch(`${API}/api/audiobooks?${params}`);
        const data = await resp.json();
        audiobooksLoaded = true;

        const filterValue = document.getElementById('audiobook-filter')?.value || 'all';
        const groupBySeries = document.getElementById('ab-group-toggle')?.checked || false;
        let books = data.audiobooks || [];

        // Client-side status filter
        if (filterValue === 'in-progress') {
            books = books.filter(b => b.progress && !b.progress.is_finished && b.progress.position > 0);
        } else if (filterValue === 'finished') {
            books = books.filter(b => b.progress && b.progress.is_finished);
        } else if (filterValue === 'not-started') {
            books = books.filter(b => !b.progress || b.progress.position === 0);
        }

        if (books.length === 0) {
            container.innerHTML = '<p style="color:#888;text-align:center;padding:40px">No audiobooks found.</p>';
            return;
        }

        container.innerHTML = '';

        // Recently played section (show up to 5, only on "All" filter with no search)
        if (filterValue === 'all' && !searchValue && !groupBySeries) {
            const recentBooks = books
                .filter(b => b.progress && b.progress.last_played && !b.progress.is_finished)
                .sort((a, b) => b.progress.last_played - a.progress.last_played)
                .slice(0, 5);

            if (recentBooks.length > 0) {
                const header = document.createElement('div');
                header.className = 'ab-section-header';
                header.textContent = 'Recently Played';
                container.appendChild(header);

                const recentGrid = document.createElement('div');
                recentGrid.className = 'ab-recent-grid';
                for (const book of recentBooks) {
                    recentGrid.appendChild(buildAudiobookCard(book));
                }
                container.appendChild(recentGrid);

                const allHeader = document.createElement('div');
                allHeader.className = 'ab-section-header';
                allHeader.textContent = 'All Audiobooks';
                container.appendChild(allHeader);
            }
        }

        if (groupBySeries) {
            // Group books by series
            const groups = {};
            for (const book of books) {
                const series = book.series || 'Ungrouped';
                if (!groups[series]) groups[series] = [];
                groups[series].push(book);
            }

            const sortedSeries = Object.keys(groups).sort((a, b) => {
                if (a === 'Ungrouped') return 1;
                if (b === 'Ungrouped') return -1;
                return a.toLowerCase().localeCompare(b.toLowerCase());
            });

            for (const series of sortedSeries) {
                const header = document.createElement('div');
                header.className = 'ab-series-header';
                header.textContent = series;
                container.appendChild(header);

                const grid = document.createElement('div');
                grid.className = 'ab-series-grid';
                for (const book of groups[series]) {
                    grid.appendChild(buildAudiobookCard(book));
                }
                container.appendChild(grid);
            }
        } else {
            for (const book of books) {
                container.appendChild(buildAudiobookCard(book));
            }
        }
    } catch (err) {
        console.error('Failed to load audiobooks:', err);
        container.innerHTML = '<p style="color:#e94560;text-align:center;padding:40px">Failed to load audiobooks.</p>';
    }
}

function buildAudiobookCard(book) {
    const card = document.createElement('div');
    card.className = 'audiobook-card';

    const nowPlayingFolder = localStorage.getItem('audiobook-now-playing');
    if (nowPlayingFolder === book.folder_path) {
        card.classList.add('ab-now-playing');
    }

    const coverUrl = `/api/audiobook/cover?folder=${encodeURIComponent(book.folder_path)}`;
    const playerUrl = `/audiobook-player?folder=${encodeURIComponent(book.folder_path)}`;

    let statusHtml = '';
    if (nowPlayingFolder === book.folder_path) {
        statusHtml = '<span class="ab-status ab-playing">Now Playing</span>';
    } else if (book.progress && book.progress.is_finished) {
        statusHtml = '<span class="ab-status ab-finished">Finished</span>';
    } else if (book.progress && book.progress.position > 0) {
        statusHtml = '<span class="ab-status ab-progress">In Progress</span>';
    }

    let lastPlayed = '';
    if (book.progress && book.progress.last_played) {
        lastPlayed = formatDate(book.progress.last_played);
    }

    const pct = book.completion_pct || 0;
    const progressBarHtml = (book.progress && !book.progress.is_finished && pct > 0)
        ? `<div class="ab-progress-bar"><div class="ab-progress-fill" style="width:${pct}%"></div></div>
           <div class="ab-meta">${pct}% complete</div>`
        : '';

    const durationStr = book.total_duration > 0 ? formatDuration(book.total_duration) : '';
    const metaParts = [];
    if (book.author) metaParts.push(escHtml(book.author));
    metaParts.push(`${book.file_count} file${book.file_count !== 1 ? 's' : ''}`);
    if (durationStr) metaParts.push(durationStr);

    card.innerHTML = `
        <div class="ab-cover">
            <img src="${coverUrl}" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'" />
            <div class="ab-cover-placeholder" style="display:none">&#9835;</div>
        </div>
        <div class="ab-info">
            <div class="ab-title" title="${escAttr(book.folder_path)}">${escHtml(book.title)}</div>
            <div class="ab-meta">${metaParts.join(' &middot; ')}</div>
            ${lastPlayed ? `<div class="ab-meta">${lastPlayed}</div>` : ''}
            ${progressBarHtml}
            ${statusHtml}
        </div>
    `;

    card.addEventListener('click', () => {
        window.location.href = playerUrl;
    });

    return card;
}
