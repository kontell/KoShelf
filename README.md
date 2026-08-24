# Kotome

Kodi client for [AudioBookShelf](https://www.audiobookshelf.org/). Browse and
play audiobooks and podcasts from your ABS server with pitch-corrected tempo
control, resume across devices, and per-book playback speed memory.

## Features

- Browse libraries, series, collections, authors, and podcasts from your ABS
  server.
- Pitch-corrected playback speed (0.5×–5×) via
  [`inputstream.tempo`](https://github.com/kontell/inputstream.tempo).
    - Does *not* require syncing playback to display.
- Resume where ABS last had you. Position is synced back to the server
  while you listen.
- Per-book and per-podcast playback speeds, remembered between sessions.
- Sleep timer.
- Uses VideoPlayer by default (PAPlayer is broken without Kodi patches).

## Installation

1. Install the Kontell repository:
   [`repository.kontell`](https://github.com/kontell/repository.kontell).
2. From the repository, install:
   - **inputstream.tempo**
   - **Kotome**
3. Open Kotome, set your server URL and credentials under
   *Settings → General*.

## Supported platforms

| Platform | Kodi 21 (Omega) | Kodi 22 (Piers) |
|----------|----------------|-----------------|
| Linux x86_64 | yes | yes |
| Linux armv7 (Pi 2+) | yes | yes |
| Linux aarch64 (Pi 3+) | yes | yes |
| Android ARM32 | yes | yes |
| Android ARM64 | yes | yes |
