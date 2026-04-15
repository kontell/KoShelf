"""KoShelf - background service for playback progress sync, resume, and audiobook features."""

import json
import os
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from abs_api import ABSClient

ADDON = xbmcaddon.Addon()
PROFILE_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
SESSION_FILE = os.path.join(PROFILE_DIR, 'session.json')
SPEEDS_FILE = os.path.join(PROFILE_DIR, 'speeds.json')
SLEEP_FILE = os.path.join(PROFILE_DIR, 'sleep_timer')
TOKEN_FILE = os.path.join(PROFILE_DIR, 'token.json')
TEMPO_FILE = xbmcvfs.translatePath('special://temp/inputstream_tempo')
CONFIG_FILE = xbmcvfs.translatePath('special://temp/inputstream_tempo_config')
ACTIVE_FILE = xbmcvfs.translatePath('special://temp/inputstream_tempo_active')


def _get_float(setting_id, default):
    try:
        return float(ADDON.getSetting(setting_id))
    except (ValueError, TypeError):
        return default


def write_config():
    """Write {step, min, max} as JSON for speed.py to consume."""
    step = _get_float('speed_step', 0.10)
    lo = _get_float('min_speed', 1.0)
    hi = _get_float('max_speed', 3.0)
    if lo > hi:
        lo, hi = 0.5, 5.0
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'step': step, 'min': lo, 'max': hi}, f)
    except IOError:
        pass


def load_session():
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return None


def clear_session():
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
    except Exception:
        pass


def read_tempo():
    try:
        with open(TEMPO_FILE) as f:
            return float(f.read().strip())
    except Exception:
        return 1.0


def save_book_speed(item_id, speed):
    speeds = {}
    try:
        if os.path.exists(SPEEDS_FILE):
            with open(SPEEDS_FILE, 'r') as f:
                speeds = json.load(f)
    except Exception:
        pass
    speeds[item_id] = speed
    os.makedirs(PROFILE_DIR, exist_ok=True)
    with open(SPEEDS_FILE, 'w') as f:
        json.dump(speeds, f)


def get_client():
    server_url = ADDON.getSetting('server_url')
    username = ADDON.getSetting('username')
    password = ADDON.getSetting('password')
    if not server_url or not (username and password):
        return None
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'r') as f:
                cached = json.load(f).get('token', '')
                if cached:
                    return ABSClient(server_url, token=cached)
    except Exception:
        pass
    return ABSClient(server_url, username=username, password=password)


def find_chapter(chapters, current_time):
    """Find the current chapter name given playback position in seconds."""
    for ch in chapters:
        if ch.get('start', 0) <= current_time < ch.get('end', 0):
            return ch.get('title', '')
    return ''


class KoShelfMonitor(xbmc.Monitor):
    """Detects addon settings changes and writes new tempo to the shared file."""

    def __init__(self):
        super().__init__()
        self.settings_changed = False

    def onSettingsChanged(self):
        self.settings_changed = True


def set_koshelf_properties(win, session_data, player, chapters):
    """Update KoShelf-specific window properties during playback."""
    try:
        current_time = player.getTime()
    except Exception:
        current_time = 0

    # Chapter display
    chapter_name = find_chapter(chapters, current_time)
    if chapter_name:
        win.setProperty('KoShelf.ChapterName', chapter_name)

    # Now playing info from session
    meta = session_data.get('media_metadata', {})
    if meta.get('title'):
        win.setProperty('KoShelf.NowPlaying.Title', meta['title'])
    if meta.get('author'):
        win.setProperty('KoShelf.NowPlaying.Author', meta['author'])

    # Sleep timer
    try:
        if os.path.exists(SLEEP_FILE):
            with open(SLEEP_FILE) as f:
                end_time = float(f.read().strip())
            remaining = end_time - time.time()
            if remaining <= 0:
                player.stop()
                os.remove(SLEEP_FILE)
                win.clearProperty('KoShelf.SleepTimerRemaining')
                xbmc.log('KoShelf: sleep timer expired, stopping playback', xbmc.LOGINFO)
            else:
                mins = int(remaining) // 60
                secs = int(remaining) % 60
                win.setProperty('KoShelf.SleepTimerRemaining', '{}:{:02d}'.format(mins, secs))
    except Exception:
        pass


def clear_koshelf_properties(win):
    for prop in ('KoShelf.ChapterName', 'KoShelf.NowPlaying.Title',
                 'KoShelf.NowPlaying.Author', 'KoShelf.SleepTimerRemaining'):
        win.clearProperty(prop)


def run():
    monitor = KoShelfMonitor()
    player = xbmc.Player()
    win = xbmcgui.Window(10000)

    sync_interval = 30
    try:
        sync_interval = int(ADDON.getSetting('sync_interval'))
    except (ValueError, TypeError):
        pass

    active_session = None
    last_sync = 0
    client = None
    seek_done = False
    chapters = []
    last_book_speed_save = 0
    last_active = False

    # Seed the shared tempo config so speed.py has min/max/step ready even
    # if the user triggers keys before opening playback from KoShelf.
    write_config()

    xbmc.log('KoShelf service started', xbmc.LOGINFO)

    # 0.25s poll keeps the resume-seek latency down once the stream is ready,
    # so the user hears as little of the pre-resume audio as possible.
    while not monitor.abortRequested():
        if monitor.waitForAbort(0.25):
            break

        # When the sentinel appears or disappears, refresh a KoShelf listing
        # if that's what the user is currently looking at — so the root shows
        # the "Now playing" item without needing a manual re-entry.
        active_now = os.path.exists(ACTIVE_FILE)
        if active_now != last_active:
            folder = xbmc.getInfoLabel('Container.FolderPath') or ''
            if 'plugin.audio.koshelf' in folder:
                xbmc.executebuiltin('Container.Refresh')
            last_active = active_now

        # Handle settings change — refresh sync interval and tempo config.
        if monitor.settings_changed:
            monitor.settings_changed = False
            try:
                sync_interval = int(ADDON.getSetting('sync_interval'))
            except (ValueError, TypeError):
                pass
            # Refresh shared tempo config so speed.py sees new step/min/max.
            # Speed changes during playback are driven by inputstream.tempo's
            # keyboard/remote shortcuts which write directly to TEMPO_FILE.
            write_config()

        # Check if audio is playing
        if not player.isPlayingAudio():
            if active_session:
                # Playback stopped — close the session
                if client:
                    try:
                        current = active_session.get('last_time', 0)
                        duration = active_session.get('duration', 0)
                        session_id = active_session['session_id']
                        now = time.time()
                        listened = now - last_sync if last_sync > 0 else 0
                        client.sync_session(session_id, current, duration, listened)
                        client.close_session(session_id)
                        xbmc.log('KoShelf: closed session {}'.format(session_id),
                                 xbmc.LOGINFO)
                    except Exception as e:
                        xbmc.log('KoShelf: error closing session: {}'.format(e),
                                 xbmc.LOGWARNING)
                active_session = None
                client = None
                seek_done = False
                chapters = []
                clear_session()
                clear_koshelf_properties(win)
                try:
                    if os.path.exists(ACTIVE_FILE):
                        os.remove(ACTIVE_FILE)
                except OSError:
                    pass
            continue

        # Audio is playing — check if we have a session to track
        session_data = load_session()
        if not session_data:
            continue

        session_id = session_data.get('session_id')
        if not session_id:
            continue

        # New session detected
        if not active_session or active_session.get('session_id') != session_id:
            # Close the previous session before tracking the new one
            if active_session and client:
                old_id = active_session.get('session_id')
                try:
                    old_time = active_session.get('last_time', 0)
                    old_dur = active_session.get('duration', 0)
                    client.sync_session(old_id, old_time, old_dur, 0)
                    client.close_session(old_id)
                    xbmc.log('KoShelf: closed previous session {}'.format(old_id),
                             xbmc.LOGINFO)
                except Exception:
                    pass

            active_session = session_data
            chapters = session_data.get('chapters', [])
            last_sync = time.time()
            client = get_client()
            seek_done = False
            xbmc.log('KoShelf: tracking session {}'.format(session_id),
                     xbmc.LOGINFO)

        # Seek to resume position once the stream is fully ready.
        # getTotalTime() returns 0 until the demuxer has stream info, which is
        # when seekTime() can actually reach the inputstream without being lost.
        if not seek_done:
            start_time = active_session.get('start_time', 0)
            if start_time > 5:
                try:
                    if player.getTotalTime() <= 0:
                        continue  # not ready yet, retry next tick
                    player.seekTime(start_time)
                    xbmc.log('KoShelf: seeked to {:.0f}s'.format(start_time),
                             xbmc.LOGINFO)
                except Exception as e:
                    xbmc.log('KoShelf: seek error: {}'.format(e),
                             xbmc.LOGWARNING)
            seek_done = True
            continue

        # Update KoShelf window properties (chapter, now playing, sleep timer)
        set_koshelf_properties(win, active_session, player, chapters)

        # Save per-book speed periodically (every 10s, if changed)
        now = time.time()
        if ADDON.getSetting('per_book_speed') != 'false' and now - last_book_speed_save > 10:
            last_book_speed_save = now
            item_id = active_session.get('item_id')
            if item_id:
                current_tempo = read_tempo()
                save_book_speed(item_id, current_tempo)

        # Periodic sync
        if now - last_sync < sync_interval:
            continue

        if client:
            try:
                current_time = player.getTime()
                duration = active_session.get('duration', 0)
                listened = now - last_sync
                last_sync = now
                active_session['last_time'] = current_time
                client.sync_session(session_id, current_time, duration, listened)
                xbmc.log('KoShelf: synced {:.0f}s/{:.0f}s'.format(
                    current_time, duration), xbmc.LOGINFO)
            except Exception as e:
                xbmc.log('KoShelf: sync error: {}'.format(e), xbmc.LOGWARNING)

    # Kodi is shutting down — close any active session
    if active_session and client:
        try:
            current = active_session.get('last_time', 0)
            duration = active_session.get('duration', 0)
            client.sync_session(active_session['session_id'], current, duration, 0)
            client.close_session(active_session['session_id'])
        except Exception:
            pass
        clear_session()
    clear_koshelf_properties(win)

    xbmc.log('KoShelf service stopped', xbmc.LOGINFO)


if __name__ == '__main__':
    run()
