"""Koshelf - background service for playback progress sync, resume, and audiobook features."""

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
SLEEP_STATE_FILE = os.path.join(PROFILE_DIR, 'sleep_state.json')
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


def _close_active_session(client, session, label='session'):
    """Sync + close an ABS session, but never sync position=0 over a valid
    resume point — playback may have failed to start (e.g. HTTP error),
    leaving last_time at 0 even though start_time was the user's bookmark.
    Syncing 0 back to ABS would clobber the bookmark and remove the book
    from Continue Listening.
    """
    if not (client and session):
        return
    sid = session.get('session_id')
    last = session.get('last_time', 0) or 0
    start = session.get('start_time', 0) or 0
    dur = session.get('duration', 0)
    try:
        if last < 5 and start > 30:
            xbmc.log('Koshelf: skip sync on close ({} last={:.0f}s, '
                     'start={:.0f}s — playback never resumed)'.format(
                         label, last, start), xbmc.LOGINFO)
        else:
            client.sync_session(sid, last, dur, 0)
        client.close_session(sid)
        xbmc.log('Koshelf: closed {} {}'.format(label, sid), xbmc.LOGINFO)
    except Exception as e:
        xbmc.log('Koshelf: error closing {}: {}'.format(label, e),
                 xbmc.LOGWARNING)


def _jsonrpc(method, params=None):
    """Run a JSON-RPC call and return the result dict (or {})."""
    try:
        req = {'jsonrpc': '2.0', 'id': 1, 'method': method}
        if params is not None:
            req['params'] = params
        resp = json.loads(xbmc.executeJSONRPC(json.dumps(req)))
        return resp.get('result', {}) or {}
    except Exception as e:
        xbmc.log('Koshelf: JSON-RPC error ({}): {}'.format(method, e),
                 xbmc.LOGWARNING)
        return {}


class SleepModeController:
    """Owns sleep-timer side effects: screensaver swap, volume ramp-down,
    display-off-on-expire, and crash recovery.

    The controller is driven by the existence of SLEEP_FILE — main.py writes
    it (epoch seconds = end_time) to start a timer. The service polls it and
    when the file appears we save the current screensaver mode + volume,
    swap the screensaver to the user's chosen sleep mode, and start watching
    for idle/ramp-down. When the file disappears (expiry or external cancel)
    we restore everything.
    """

    def __init__(self):
        self.active = False
        self.original_screensaver_mode = None
        self.original_volume = None
        self.last_applied_volume = None
        self.user_overrode_volume = False
        # Crash recovery: a previous Kodi run crashed mid-timer and left
        # state behind. Restore the user's screensaver and volume now so
        # they don't stay stuck on the sleep-mode settings.
        if os.path.exists(SLEEP_STATE_FILE) and not os.path.exists(SLEEP_FILE):
            self._restore_from_state_file()

    def _restore_from_state_file(self):
        try:
            with open(SLEEP_STATE_FILE) as f:
                state = json.load(f)
            mode = state.get('screensaver_mode')
            if mode:
                _jsonrpc('Settings.SetSettingValue',
                         {'setting': 'screensaver.mode', 'value': mode})
            vol = state.get('volume')
            if vol is not None:
                _jsonrpc('Application.SetVolume', {'volume': int(vol)})
            os.remove(SLEEP_STATE_FILE)
            xbmc.log('Koshelf: restored orphaned sleep-mode state',
                     xbmc.LOGINFO)
        except Exception as e:
            xbmc.log('Koshelf: error restoring sleep state: {}'.format(e),
                     xbmc.LOGWARNING)

    def tick(self, player, win):
        """Poll once. Called from the service loop while playback is active.

        Returns True if the timer expired this tick (caller may want to
        skip remaining work), False otherwise.
        """
        sleep_file_exists = os.path.exists(SLEEP_FILE)

        if sleep_file_exists and not self.active:
            self._enter()
        elif not sleep_file_exists and self.active:
            self._exit()
            win.clearProperty('Koshelf.SleepTimerRemaining')
            return False

        if not self.active:
            return False

        try:
            with open(SLEEP_FILE) as f:
                end_time = float(f.read().strip())
        except Exception:
            self._exit()
            win.clearProperty('Koshelf.SleepTimerRemaining')
            return False

        remaining = end_time - time.time()

        if remaining <= 0:
            self._expire(player)
            win.clearProperty('Koshelf.SleepTimerRemaining')
            return True

        mins = int(remaining) // 60
        secs = int(remaining) % 60
        win.setProperty('Koshelf.SleepTimerRemaining',
                        '{}:{:02d}'.format(mins, secs))

        self._maybe_activate_screensaver()
        self._maybe_ramp_volume(remaining)
        return False

    def on_playback_stopped(self, win):
        """Called when playback stops while we're not in tick(). Cancels the
        timer and restores state so a manual stop doesn't leave the screen
        dimmed or volume faded."""
        if os.path.exists(SLEEP_FILE):
            try:
                os.remove(SLEEP_FILE)
            except OSError:
                pass
        if self.active:
            self._exit()
        win.clearProperty('Koshelf.SleepTimerRemaining')

    def _enter(self):
        self.active = True
        self.user_overrode_volume = False
        # Save originals
        mode = _jsonrpc('Settings.GetSettingValue',
                        {'setting': 'screensaver.mode'}).get('value', '')
        vol = _jsonrpc('Application.GetProperties',
                       {'properties': ['volume']}).get('volume')
        self.original_screensaver_mode = mode
        self.original_volume = vol
        self.last_applied_volume = vol
        # Persist for crash recovery
        try:
            with open(SLEEP_STATE_FILE, 'w') as f:
                json.dump({'screensaver_mode': mode, 'volume': vol}, f)
        except IOError:
            pass
        # Apply sleep screensaver (only if user enabled the dim-screen feature)
        if ADDON.getSetting('sleep_dim_screen') != 'false':
            sleep_mode = (ADDON.getSetting('sleep_screensaver_mode')
                          or 'screensaver.xbmc.builtin.black')
            if sleep_mode and sleep_mode != mode:
                _jsonrpc('Settings.SetSettingValue',
                         {'setting': 'screensaver.mode', 'value': sleep_mode})
        xbmc.log('Koshelf: sleep mode entered (saved screensaver={!r}, '
                 'volume={})'.format(mode, vol), xbmc.LOGINFO)

    def _exit(self):
        # Restore originals
        if self.original_screensaver_mode is not None:
            _jsonrpc('Settings.SetSettingValue',
                     {'setting': 'screensaver.mode',
                      'value': self.original_screensaver_mode})
        if self.original_volume is not None and not self.user_overrode_volume:
            _jsonrpc('Application.SetVolume',
                     {'volume': int(self.original_volume)})
        try:
            if os.path.exists(SLEEP_STATE_FILE):
                os.remove(SLEEP_STATE_FILE)
        except OSError:
            pass
        xbmc.log('Koshelf: sleep mode exited', xbmc.LOGINFO)
        self.active = False
        self.original_screensaver_mode = None
        self.original_volume = None
        self.last_applied_volume = None
        self.user_overrode_volume = False

    def _expire(self, player):
        xbmc.log('Koshelf: sleep timer expired, stopping playback',
                 xbmc.LOGINFO)
        try:
            player.stop()
        except Exception:
            pass
        try:
            os.remove(SLEEP_FILE)
        except OSError:
            pass
        display_off = ADDON.getSetting('sleep_display_off') == 'true'
        # Restore *before* CEC standby so the volume restore JSON-RPC has
        # a chance to land before the display goes to sleep.
        self._exit()
        if display_off:
            xbmc.log('Koshelf: sending CEC standby', xbmc.LOGINFO)
            xbmc.executebuiltin('CECStandby')

    def _maybe_activate_screensaver(self):
        if ADDON.getSetting('sleep_dim_screen') == 'false':
            return
        try:
            idle_thresh = int(ADDON.getSetting('sleep_idle_seconds'))
        except (ValueError, TypeError):
            idle_thresh = 30
        try:
            idle = xbmc.getGlobalIdleTime()
        except Exception:
            return
        if idle >= idle_thresh and not xbmc.getCondVisibility(
                'System.ScreenSaverActive'):
            xbmc.executebuiltin('ActivateScreenSaver')

    def _maybe_ramp_volume(self, remaining):
        try:
            ramp = int(ADDON.getSetting('sleep_rampdown_seconds'))
        except (ValueError, TypeError):
            ramp = 30
        if ramp <= 0 or remaining > ramp or self.original_volume is None:
            return
        if self.user_overrode_volume:
            return
        # Detect user volume override: current volume differs from what we
        # last set. If so, back off — don't fight the user, and don't
        # restore on cancel either (they want their new volume).
        cur = _jsonrpc('Application.GetProperties',
                       {'properties': ['volume']}).get('volume')
        if (self.last_applied_volume is not None and cur is not None
                and cur != self.last_applied_volume):
            xbmc.log('Koshelf: volume ramp backed off (user adjusted from '
                     '{} to {})'.format(self.last_applied_volume, cur),
                     xbmc.LOGINFO)
            self.user_overrode_volume = True
            return
        target = max(0, int(round(self.original_volume * remaining / ramp)))
        if cur is None or target == cur:
            return
        _jsonrpc('Application.SetVolume', {'volume': target})
        self.last_applied_volume = target


class KoshelfMonitor(xbmc.Monitor):
    """Detects addon settings changes and writes new tempo to the shared file."""

    def __init__(self):
        super().__init__()
        self.settings_changed = False

    def onSettingsChanged(self):
        self.settings_changed = True


def set_koshelf_properties(win, session_data, player, chapters):
    """Update Koshelf-specific window properties during playback."""
    try:
        current_time = player.getTime()
    except Exception:
        current_time = 0

    # Chapter display
    chapter_name = find_chapter(chapters, current_time)
    if chapter_name:
        win.setProperty('Koshelf.ChapterName', chapter_name)

    # Now playing info from session
    meta = session_data.get('media_metadata', {})
    if meta.get('title'):
        win.setProperty('Koshelf.NowPlaying.Title', meta['title'])
    if meta.get('author'):
        win.setProperty('Koshelf.NowPlaying.Author', meta['author'])

def clear_koshelf_properties(win):
    for prop in ('Koshelf.ChapterName', 'Koshelf.NowPlaying.Title',
                 'Koshelf.NowPlaying.Author', 'Koshelf.SleepTimerRemaining'):
        win.clearProperty(prop)


def run():
    monitor = KoshelfMonitor()
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
    chapters = []
    last_book_speed_save = 0
    last_active = False
    sleep_controller = SleepModeController()

    # Seed the shared tempo config so speed.py has min/max/step ready even
    # if the user triggers keys before opening playback from Koshelf.
    write_config()

    xbmc.log('Koshelf service started', xbmc.LOGINFO)

    # 0.25s poll keeps the resume-seek latency down once the stream is ready,
    # so the user hears as little of the pre-resume audio as possible.
    while not monitor.abortRequested():
        if monitor.waitForAbort(0.25):
            break

        # When the sentinel appears or disappears, refresh a Koshelf listing
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

        if not player.isPlaying():
            if active_session:
                # Playback stopped — close the session
                _close_active_session(client, active_session, 'session')
                active_session = None
                client = None
                chapters = []
                clear_session()
                clear_koshelf_properties(win)
                try:
                    if os.path.exists(ACTIVE_FILE):
                        os.remove(ACTIVE_FILE)
                except OSError:
                    pass
            sleep_controller.on_playback_stopped(win)
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
            if active_session:
                _close_active_session(client, active_session, 'previous session')

            active_session = session_data
            chapters = session_data.get('chapters', [])
            last_sync = time.time()
            client = get_client()
            xbmc.log('Koshelf: tracking session {}'.format(session_id),
                     xbmc.LOGINFO)

        # Update Koshelf window properties (chapter, now playing)
        set_koshelf_properties(win, active_session, player, chapters)

        # Sleep timer + screensaver swap + volume ramp-down
        sleep_controller.tick(player, win)

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
                start_time = active_session.get('start_time', 0)
                # Guard: don't overwrite a valid resume position with 0.
                # Can happen if GetTime() hasn't caught up after an initial
                # seek (e.g. m_currentPts not yet set in the inputstream).
                if current_time < 5 and start_time > 30:
                    continue
                listened = now - last_sync
                last_sync = now
                active_session['last_time'] = current_time
                client.sync_session(session_id, current_time, duration, listened)
                xbmc.log('Koshelf: synced {:.0f}s/{:.0f}s'.format(
                    current_time, duration), xbmc.LOGINFO)
            except Exception as e:
                xbmc.log('Koshelf: sync error: {}'.format(e), xbmc.LOGWARNING)

    # Kodi is shutting down — close any active session and restore any
    # in-flight sleep-mode state so the user's screensaver/volume aren't
    # left on the sleep-mode values across a Kodi restart.
    if active_session:
        _close_active_session(client, active_session, 'session on shutdown')
        clear_session()
    sleep_controller.on_playback_stopped(win)
    clear_koshelf_properties(win)

    xbmc.log('Koshelf service stopped', xbmc.LOGINFO)


if __name__ == '__main__':
    run()
