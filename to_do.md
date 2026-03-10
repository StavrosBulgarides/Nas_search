# Search Wizard - Audiobook Feature To Do

## Phase 1 - Core Player [DONE]

- [x] Audio player page (`/audiobook-player`)
- [x] Play / pause
- [x] Seek bar with current time and total duration
- [x] Skip back / forward (configurable 10, 15, or 30 seconds)
- [x] Playback speed control (0.5x to 3x)
- [x] Volume control
- [x] Chapter / file list sidebar with prev/next navigation
- [x] File ordering by disc number, track number, then natural filename sort
- [x] Auto-save position on pause, close, and every 5 seconds
- [x] Resume where you left off
- [x] MP3 files indexed and routed to audiobook player from search results
- [x] Keyboard shortcuts (space = play/pause, arrows = skip)
- [x] `mutagen` added for MP3 metadata reading
- [x] Database tables for progress and bookmarks

## Phase 2 - Bookmarks & Progress [DONE]

- [x] Manual bookmarks with optional notes
- [x] Jump to bookmark (file + position)
- [x] Delete bookmarks
- [x] Sleep timer (15/30/45/60/90 minutes)
- [x] Sleep at end of current file
- [x] Cancel sleep timer
- [x] Audiobooks tab in main UI with library grid
- [x] Filter: All / In Progress / Finished / Not Started
- [x] Cover art from MP3 ID3 tags

## Phase 3 - Library & Metadata [DONE]

- [x] Per-book completion percentage displayed on library cards with progress bar
- [x] "Finished" marking (toggle button in player) and status on library cards
- [x] Author display from ID3 artist tag on library cards
- [x] Duration per book (sum of all file durations via mutagen) on library cards
- [x] Sort library by title, author, recently played, duration, series
- [x] Search within audiobooks library (searches title, author, album, series)
- [x] Series grouping (toggle to group by parent folder with collapsible headers)
- [x] Metadata cache table (`audiobook_meta`) for fast library loading
- [x] Refresh metadata endpoint (`POST /api/audiobooks/refresh-meta`)

## Phase 4 - Chapter Navigation [DONE]

- [x] Embedded CHAP frame extraction from MP3 ID3 tags via mutagen
- [x] Unified chapter model: embedded chapters for files that have them, whole file = chapter otherwise
- [x] Chapter list in sidebar with names and durations
- [x] Multi-file books show file headers with nested chapters underneath
- [x] Click any chapter to jump to it (seeks within file or loads new file)
- [x] Prev/next buttons now navigate chapters (not just files)
- [x] Prev chapter restarts current chapter if >3 seconds in, otherwise goes to previous
- [x] Chapter-aware now-playing display (shows chapter title + position within book)
- [x] Active chapter highlighted in sidebar, auto-scrolls into view
- [x] "End of chapter" sleep timer option (shown when embedded chapters are present)
- [x] "End of current file" sleep timer preserved as separate option
- [x] Ctrl+Left / Ctrl+Right keyboard shortcuts for chapter navigation

## Phase 5 - Polish [DONE]

- [x] Now playing indicator on audiobooks tab (purple glow + "Now Playing" badge)
- [x] Now playing state stored in localStorage, set on play, cleared on finish
- [x] Swipe gestures for mobile (swipe left/right on player area for prev/next chapter)
- [x] Responsive file list on mobile (hidden by default, "Chapters" button in toolbar to open as full-screen overlay, close button and auto-close on chapter select)
- [x] Recently played section on audiobooks tab (shows up to 5 most recently played, unfinished books above the main grid)
- [x] Position sync across devices (works via server-side SQLite — no extra work needed)

## All Phases Complete

## Deployment Notes

- Add `mp3` to `config.yml` extensions list
- Add audiobook folder mounts to `docker-compose.yml` if needed
- Rebuild: `sudo docker-compose up -d --build`
- Reindex to pick up MP3 files
- Update README with audiobook feature documentation
