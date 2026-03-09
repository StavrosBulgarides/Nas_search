const API = '';
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
});

function setupEventListeners() {
    const searchInput = document.getElementById('search-input');
    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => doSearch(false), 300);
    });
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            clearTimeout(searchTimeout);
            doSearch(false);
        }
    });

    document.getElementById('folder-filter').addEventListener('change', () => doSearch(false));
    document.getElementById('extension-filter').addEventListener('change', () => doSearch(false));
    document.getElementById('fuzzy-toggle').addEventListener('change', () => doSearch(false));

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

async function doSearch(loadMore) {
    const query = document.getElementById('search-input').value.trim();
    if (!query) {
        clearResults();
        return;
    }

    if (!loadMore) {
        currentOffset = 0;
        currentQuery = query;
    }

    const folder = document.getElementById('folder-filter').value;
    const extension = document.getElementById('extension-filter').value;
    const fuzzy = document.getElementById('fuzzy-toggle').checked;

    const params = new URLSearchParams({
        q: query,
        limit: '20',
        offset: String(currentOffset),
        fuzzy: String(fuzzy),
    });
    if (folder) params.set('folder', folder);
    if (extension) params.set('extension', extension);

    try {
        const resp = await fetch(`${API}/api/search?${params}`);
        const data = await resp.json();
        currentTotal = data.total;

        if (!loadMore) {
            document.getElementById('results-body').innerHTML = '';
        }

        if (data.results.length === 0 && currentOffset === 0) {
            showNoResults(fuzzy);
        } else {
            hideNoResults();
            renderResults(data.results);
            currentOffset += data.results.length;
        }

        document.getElementById('results-info').textContent =
            `${currentTotal} result${currentTotal !== 1 ? 's' : ''} for "${query}"` +
            (fuzzy ? ' (fuzzy)' : '');

        const loadMoreBtn = document.getElementById('load-more-btn');
        loadMoreBtn.style.display = currentOffset < currentTotal ? '' : 'none';

    } catch (err) {
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
        li.textContent = file.filename;
        li.title = file.full_path;
        li.addEventListener('click', () => {
            document.getElementById('search-input').value = file.filename.replace(/\.[^.]+$/, '');
            doSearch(false);
        });
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

function buildOpenFileUrl(fullPath, extension) {
    const ext = (extension || '').toLowerCase();
    const nasPath = containerToNasPath(fullPath);

    if (COMIC_EXTENSIONS.includes(ext)) {
        return `/reader?path=${encodeURIComponent(fullPath)}`;
    }

    if (TRANSCODE_VIDEO.includes(ext)) {
        return `/player?path=${encodeURIComponent(fullPath)}`;
    }

    if (NATIVE_VIDEO.includes(ext)) {
        const encodedPath = encodeURIComponent(nasPath);
        const launchParam = encodeURIComponent('ieMode=9&is_drive=false&path=' + encodedPath + '&file_id=' + encodedPath);
        return `http://${NAS_HOST}:${NAS_PORT}/?launchApp=SYNO.SDS.VideoPlayer2.Application&launchParam=${launchParam}&ieMode=9`;
    }

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
