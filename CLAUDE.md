# Koshelf

AudioBookShelf client for Kodi. Pure Python add-on — `plugin.audio` with
`<provides>audio</provides>`.

## Kodi knowledge lives in kodi-drive

Shared Kodi knowledge is **not** in this file. Use the `kodi-drive:*` skills, or
read `../kodi-drive/README.md`.

Directly relevant: `kodi-playback-resume` (which resume property each player core
takes, and in what units), `kodi-paplayer`, `kodi-addon-manifest`,
`kodi-idle-screensaver`, `kodi-python-runtime`, `kodi-addon-release`,
`kodi-inputstream`.

**Do not add generally-useful Kodi findings here** — contribute them to kodi-drive.
This file holds only what is specific to *this* add-on.

## Layout

| Path | |
|---|---|
| `main.py` | plugin entry point, routing, browsing, playback resolution |
| `service.py` | ABS session sync, chapter display, sleep timer, per-book speed |
| `abs_api.py` | AudioBookShelf REST client |

## Playback pipeline

1. `_resolve_playback()` creates an ABS play session, gets the stream URL and
   resume position.
2. Reads the `player` setting (0 = VideoPlayer, 1 = PAPlayer) and branches the
   ListItem setup.
3. Sets `inputstream` plus tempo properties (`tempo`, `tempo_file`, `start_time`)
   on both branches.
4. VideoPlayer branch: `VideoInfoTag` (mediaType `musicvideo`) + `StartOffset`
   (ms) + `ResumeTime`/`TotalTime` (s).
5. PAPlayer branch: `MusicInfoTag` + `audiobook_bookmark` (ms).
6. `setResolvedUrl()` hands off; the matching core opens the stream via
   `inputstream.tempo`.

**The `musicvideo` VideoInfoTag is what selects VideoPlayer**, not `<provides>`.
This add-on deliberately does *not* declare `<provides>video</provides>` — see
`kodi-addon-manifest` for what that would break.

Both cores route audio-only content to `WINDOW_VISUALISATION`; the visible
difference is which OSD infolabels populate. Details in `kodi-playback-resume`.

Requires `inputstream.tempo` 0.3.10+ (0.3.9 added VideoPlayer OSD content-time
tracking; 0.3.10 fixed a startup crash on FFmpeg-6 Kodi builds with Opus/webm).

## Sleep timer

`SLEEP_FILE` (`special://profile/sleep_timer`) is the source of truth: `main.py`
writes the wall-clock end time, the service polls for it.

`SleepModeController` in `service.py` owns the side effects. On the file appearing
it saves the current screensaver mode and volume to `sleep_state.json`, then
watches `getGlobalIdleTime()` against `sleep_idle_seconds`.

`sleep_screen_action` selects what fires after idle:

| Value | |
|---|---|
| `screensaver_black` / `screensaver_dim` | swap Kodi's screensaver and trigger it |
| `screen_off_cec` | `CECStandby` |
| `screen_off_android` | DPMS toggle |
| `none` | nothing |

Fires once per idle period, re-arming on interaction. Volume ramps to zero over
`sleep_rampdown_seconds`, backing off if the user adjusts it mid-ramp.

On expiry: stop, restore volume and screensaver, leave the screen dark. On cancel
or playback stop: restore everything including waking the screen.

**`sleep_state.json` is the crash-recovery breadcrumb** — if it exists at service
start with no live `SLEEP_FILE`, restore the saved values. `kodi-idle-screensaver`
explains why that file is not optional.

## Cross-add-on wiring

- `special://temp/inputstream_tempo_config` — speed step/min/max as JSON, read by
  `inputstream.tempo`'s `speed.py`.
- `special://temp/inputstream_tempo_active` — sentinel; gates `speed.py`'s keys,
  `runner.py`'s `InputstreamTempo.Active` window property, and the "Now playing"
  root menu item.
- `speeds.json` in the add-on profile — per-book speeds.

## Build

```bash
tox                       # what CI gates on: black, compileall
tools/build.py [OUTDIR]   # Kodi-installable zip, default ./dist
tools/dev-install.sh      # rsync into the addons dir, bounce the service
```

`tools/build.py` walks the tree and excludes dev-only paths. It replaced a
`build.sh` that copied a hand-written list of seven paths — `resources/black.png`,
which the sleep timer's screen-off overlay draws, had never been in a published
zip. `kodi-addon-release` covers why include-lists fail this way.

No mypy gate: strict over the three modules reports ~104 errors, nearly all
missing annotations across `main.py`'s 1200 lines. `tox.ini` records what adding
it would take — start with `abs_api.py`.

Workflows: `ci.yml` (black, compileall, an `assets` job that fails on a referenced
resource missing from the tree, and a PR zip), `release.yml`, `notify-repo.yml`.

`release.yml` warns when `addon.xml`'s hand-maintained `<news>` does not mention
the version being released — because `<news>` is present, the repo generator will
not fall back to `changelog.txt`, so a stale one advertises the wrong notes.
