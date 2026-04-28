# Koshelf

AudioBookShelf client for Kodi. Pure Python addon (`plugin.audio` + `<provides>audio video</provides>` so VideoPlayer can be selected too).

## Architecture

- `main.py` — plugin entry point, routing, library browsing, playback resolution
- `service.py` — background service for ABS session sync, chapter display, sleep timer, per-book speed tracking
- `abs_api.py` — AudioBookShelf REST API client

## Playback pipeline

1. `_resolve_playback()` creates an ABS play session, gets stream URL + resume position
2. Reads the `player` setting (0 = VideoPlayer default, 1 = PAPlayer) and branches the ListItem setup
3. Sets `inputstream` + tempo properties (`tempo`, `tempo_file`, `start_time`) for both branches
4. VideoPlayer branch: `VideoInfoTag` (mediaType `musicvideo`) + `StartOffset` (ms) + `ResumeTime`/`TotalTime` (s)
5. PAPlayer branch: `MusicInfoTag` + `audiobook_bookmark` (ms)
6. `setResolvedUrl()` hands the ListItem to Kodi; the matching player core opens the stream via inputstream.tempo, which handles tempo processing

Both player cores route audio-only content to `WINDOW_VISUALISATION` — Kodi picks the fullscreen window from `IsPlayingAudio()`/`IsPlayingVideo()`, not the player core. The visible difference is which OSD info-labels populate (e.g. `Player.ChapterCount` is always 0 under PAPlayer) and which time-tracking path runs.

## Resume mechanism

Resume property differs by player:
- **VideoPlayer**: `StartOffset` (milliseconds). Kodi consumes it via `CFileItem::SetStartOffset` and queues a `SeekTime` after demuxer open.
- **PAPlayer**: `audiobook_bookmark` (milliseconds). Read in `QueueNextFileEx()`, converted to a frame offset, and applied in `ProcessStream()` before audio output begins.

In both modes Koshelf also sets `inputstream.tempo.start_time` (seconds). The C++ addon uses it to (a) pre-populate `m_currentPts` so `GetTime()` reads the resume position before the seek executes, and (b) arm a player-agnostic initial-seek hold that gates `DemuxRead` output until any `SeekTime > 100 ms` arrives — without this hold, the audio sink can play ~50 ms of pts=0 audio from the stream start before the resume seek lands. Requires inputstream.tempo 0.3.10+ (0.3.9 added VideoPlayer OSD content-time tracking via dynamic `ptsStart`; 0.3.10 also fixes a startup crash for FFmpeg-6 patched Kodi builds with Opus/webm sources).

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
