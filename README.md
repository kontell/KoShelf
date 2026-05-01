# Koshelf

Kodi client for [AudioBookShelf](https://www.audiobookshelf.org/). Browse and
play audiobooks and podcasts from your ABS server with pitch-corrected tempo
control, resume across devices, and per-book playback speed memory.

## Features

- Browse libraries, series, collections, authors, and podcasts from your ABS
  server.
- Pitch-corrected playback speed (0.5×–5×) via
  [`inputstream.tempo`](https://github.com/kontell/inputstream.tempo).
- Resume where ABS last had you. Position is synced back to the server
  while you listen.
- Per-book and per-podcast playback speeds, remembered between sessions.
- Uses VideoPlayer by default (PAPlayer is broken without Kodi patches).

## Installation

1. Install the Kontell repository:
   [`repository.kontell`](https://github.com/kontell/repository.kontell).
2. From the repository, install:
   - **inputstream.tempo**
   - **Koshelf**
3. Open Koshelf, set your server URL and credentials under
   *Settings → General*.

## Links

- [AudioBookShelf](https://www.audiobookshelf.org/)
- [`inputstream.tempo` (fork)](https://github.com/kontell/inputstream.tempo)
- [`repository.kontell`](https://github.com/kontell/repository.kontell)
