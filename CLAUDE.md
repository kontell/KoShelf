# Koshelf

AudioBookShelf client for Kodi. Pure Python addon (`plugin.audio`).

## Architecture

- `main.py` — plugin entry point, routing, library browsing, playback resolution
- `service.py` — background service for ABS session sync, chapter display, sleep timer, per-book speed tracking
- `abs_api.py` — AudioBookShelf REST API client

## Playback pipeline

1. `_resolve_playback()` creates an ABS play session, gets stream URL + resume position
2. Sets ListItem properties for inputstream.tempo (tempo, tempo_file) and PAPlayer (audiobook_bookmark)
3. `setResolvedUrl()` hands the ListItem to Kodi
4. PAPlayer opens the stream via inputstream.tempo, which handles tempo processing
5. PAPlayer's native audiobook resume reads `audiobook_bookmark` (milliseconds) and seeks before audio output — no Python seek needed

## Resume mechanism

Resume uses PAPlayer's built-in audiobook bookmark support:
```python
li.setProperty('audiobook_bookmark', str(int(start_time * 1000)))
```
PAPlayer reads this in `QueueNextFileEx()`, converts to a frame offset, and seeks in `ProcessStream()` before audio output begins. This avoids race conditions with PAPlayer's init `SeekTime(0)` calls.

The `inputstream.tempo.start_time` property is also set on resume. The C++ addon uses it to (a) pre-populate `m_currentPts` so `GetTime()` reads the resume position before the bookmark seek executes, and (b) arm an initial-seek hold that gates `DemuxRead` output until the bookmark seek arrives — without this hold, PAPlayer's sink `Resume()` can play ~50 ms of pts=0 audio from the stream start before `SeekTime(bookmark)` lands. Requires inputstream.tempo 0.3.6+.

## Speed control

Speed settings (step, min, max) are written as JSON to `special://temp/inputstream_tempo_config`. inputstream.tempo's `speed.py` reads this for keyboard/dialog stepping. Per-book speeds are stored in `speeds.json` in the addon profile.

## Sentinel file

`special://temp/inputstream_tempo_active` exists while tempo is the active inputstream. Controls:
- Whether speed.py keys/dialog are active (no-ops otherwise)
- Whether runner.py sets the `InputstreamTempo.Active` window property
- Whether the "Now playing" root menu item appears

## Settings

New format (`settings version="1"`) with string IDs in `resources/language/resource.language.en_gb/strings.po`. Playback section first, General section second.

## Build

```bash
./build.sh                          # local build to ../builds/
./build.sh --output /path/to/dir    # CI build
```

GitHub Actions: `build.yml` (every push), `release.yml` (on v* tag → draft release).
