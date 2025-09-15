# TODOs for RockSync

## 🔨 Core Features
- [ ] **File/Folder Deletion**
  - [ ] Add context menu actions in Explorer and Device views.
  - [ ] Use `send2trash` where available, fallback to `os.remove` / `shutil.rmtree`.
  - [ ] Add confirmation dialog before delete.
  - [ ] Log deletions in the central logger.

- [ ] **Sync Improvements**
  - [ ] Add optional hash verification (xxhash/MD5).
  - [ ] Support resumable transfers for large files.
  - [ ] Parallel copy with bounded worker pool, progress per file, overall ETA.
  - [ ] Policies for automatic downsampling per-device capacity or remaining free space.
  - [ ] Gapless playback checks (verify encoder settings/tags).

- [ ] **Conflict Awareness**
  - [ ] Show diffs for modified/renamed files.
  - [ ] Allow user to choose keep/overwrite/skip.

- [ ] **Integrity Tools**
  - [ ] ReplayGain / loudness scanning.
  - [ ] Playlist dedupe, bulk `.m3u8` creation, convert folders to playlists.
  - [ ] Read/write Rockbox dynamic playlist files (`.tcd`).

## ⚙️ Settings & Configuration
- [x] **Optional Tabs**
  - [x] Add `enable_youtube` and `enable_tidal` settings (default: `false`).
  - [x] On startup, hide/disable tabs if settings are `false`.
  - [x] Ensure UI dynamically respects changes.

- [ ] **Onboarding Wizard**
  - [ ] Detect music root/device.
  - [ ] Check for `ffmpeg`, `yt-dlp`, `psutil` presence.
  - [ ] Offer to create the music index DB.

## 📚 Database & Search
- [ ] **Incremental Indexing**
  - [ ] Use `watchdog` or similar for live updates.

- [ ] **Search Upgrade**
  - [ ] Integrate SQLite FTS5 (fuzzy, diacritics-insensitive search).

- [ ] **Schema Handling**
  - [ ] Versioned schema with safe migrations.

## 🎨 UX & Media
- [ ] **Explorer Improvements**
  - [ ] Central thumbnail cache on disk for faster loads.
  - [ ] Show embedded vs. sidecar cover/lyrics.

- [ ] **Device UX**
  - [ ] Long-path support (Windows).
  - [ ] FAT32 filename sanitizer.
  - [ ] Better recovery when device disconnects mid-sync.

- [ ] **Themes**
  - [ ] Cache Rockbox theme screenshots.
  - [ ] Show “installed” and “updates available.”

- [ ] **Daily Mix / Smart Playlists**
  - [ ] Expose advanced weighting (recency, skip history, per-genre quotas).
  - [ ] Export directly to device playlists.

- [ ] **YouTube Enhancements**
  - [ ] Add queue manager with per-item status, retries, and space check.
  - [ ] Support SponsorBlock chapters.
  - [ ] Add “safe mode” to skip risky split-chapters.

- [ ] **TIDAL Improvements**
  - [ ] Add tooltip disclaimer in UI with link to upstream project.
  - [ ] Allow disabling the tab entirely (default off).

## 📦 Packaging & Releases
- [ ] **Installers**
  - [ ] Fix prebuilt installers (Windows/MSI, macOS `.dmg`, Linux AppImage/Flatpak).
  - [ ] Add compatibility table per OS.
  - [ ] Provide portable “zip” build that stores settings locally.

- [ ] **Signing**
  - [ ] Windows code-signing.
  - [ ] macOS notarization.

## 📖 Documentation
- [x] **README Updates**
  - [x] New section: **Experimental Integrations (YouTube & TIDAL)**.
  - [x] Explain optional, off-by-default tabs.
  - [x] Document extra dependencies (`yt-dlp`, `tidalapi` fork).
  - [x] Clarify instability of external services.

- [ ] **Visuals**
  - [ ] Add screenshots of each tab.
  - [ ] Short “60-second tour” video/gif.

- [ ] **Troubleshooting**
  - [ ] Convert tips into a quick-reference table (missing ffmpeg, device not detected, cookies, etc.).

- [ ] **Contributor Docs**
  - [ ] Contribution guide, issue templates, PR checklist.
  - [ ] Architecture overview (modules, tasks, DB).

- [ ] **Settings Handling**
  - [ ] Document `settings.json` and add import/export UI.
