"""KoShelf - background service for playback progress sync and resume."""

import json
import os
import time

import xbmc
import xbmcaddon
import xbmcvfs

from abs_api import ABSClient

ADDON = xbmcaddon.Addon()
SESSION_FILE = os.path.join(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')),
                            'session.json')


def load_session():
    """Read session info written by the plugin."""
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return None


def clear_session():
    """Remove the session file."""
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
    except Exception:
        pass


TOKEN_FILE = os.path.join(os.path.dirname(SESSION_FILE), 'token.json')


def get_client():
    server_url = ADDON.getSetting('server_url')
    api_key = ADDON.getSetting('api_key')
    username = ADDON.getSetting('username')
    password = ADDON.getSetting('password')
    if not server_url:
        return None
    if not api_key and not (username and password):
        return None
    if api_key:
        return ABSClient(server_url, api_key=api_key)
    # Use cached token from main plugin
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'r') as f:
                cached = json.load(f).get('token', '')
                if cached:
                    return ABSClient(server_url, api_key=cached)
    except Exception:
        pass
    return ABSClient(server_url, username=username, password=password)


def run():
    monitor = xbmc.Monitor()
    player = xbmc.Player()

    sync_interval = 30
    try:
        sync_interval = int(ADDON.getSetting('sync_interval'))
    except (ValueError, TypeError):
        pass

    active_session = None
    last_sync = 0
    client = None
    seek_done = False

    xbmc.log('KoShelf service started', xbmc.LOGINFO)

    while not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break

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
                clear_session()
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
            last_sync = time.time()
            client = get_client()
            seek_done = False
            xbmc.log('KoShelf: tracking session {}'.format(session_id),
                     xbmc.LOGINFO)

        # Seek to resume position once after playback starts
        if not seek_done:
            start_time = active_session.get('start_time', 0)
            if start_time > 5:
                # Wait briefly for the player to stabilise before seeking
                xbmc.sleep(500)
                try:
                    player.seekTime(start_time)
                    xbmc.log('KoShelf: seeked to {:.0f}s'.format(start_time),
                             xbmc.LOGINFO)
                except Exception as e:
                    xbmc.log('KoShelf: seek error: {}'.format(e),
                             xbmc.LOGWARNING)
            seek_done = True
            continue

        # Periodic sync
        now = time.time()
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

    xbmc.log('KoShelf service stopped', xbmc.LOGINFO)


if __name__ == '__main__':
    run()
