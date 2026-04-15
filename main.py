"""KoShelf - AudioBookShelf client for Kodi."""

import os
import sys
import json
import time
from urllib.parse import urlencode, parse_qs

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from abs_api import ABSClient

# ── Plugin bootstrap ──

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
try:
    HANDLE = int(sys.argv[1])
except (IndexError, ValueError):
    HANDLE = -1
BASE_URL = sys.argv[0]


TOKEN_FILE = os.path.join(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')),
                          'token.json')


def _load_cached_token():
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'r') as f:
                return json.load(f).get('token', '')
    except Exception:
        pass
    return ''


def _save_cached_token(token):
    profile_dir = os.path.dirname(TOKEN_FILE)
    os.makedirs(profile_dir, exist_ok=True)
    with open(TOKEN_FILE, 'w') as f:
        json.dump({'token': token}, f)


def get_client():
    server_url = ADDON.getSetting('server_url')
    api_key = ADDON.getSetting('api_key')
    username = ADDON.getSetting('username')
    password = ADDON.getSetting('password')
    if not server_url:
        xbmcgui.Dialog().ok('KoShelf', 'Please configure the server URL in addon settings.')
        ADDON.openSettings()
        return None
    if not api_key and not (username and password):
        xbmcgui.Dialog().ok('KoShelf', 'Please configure an API key or username/password in addon settings.')
        ADDON.openSettings()
        return None
    # Use API key directly if available; otherwise use cached login token
    if api_key:
        return ABSClient(server_url, api_key=api_key)
    cached = _load_cached_token()
    if cached:
        client = ABSClient(server_url, api_key=cached)
        # Quick check the token still works
        if client.get_libraries():
            return client
    # Token missing or expired — login fresh
    client = ABSClient(server_url, username=username, password=password)
    if client.token:
        _save_cached_token(client.token)
    return client


def build_url(**kwargs):
    """Build a plugin:// URL from keyword arguments."""
    for k, v in kwargs.items():
        if isinstance(v, (dict, list)):
            kwargs[k] = json.dumps(v)
    return '{}?{}'.format(BASE_URL, urlencode(kwargs))


def add_directory(label, **kwargs):
    """Add a navigable folder item."""
    url = build_url(**kwargs)
    li = xbmcgui.ListItem(label)
    li.setIsFolder(True)
    xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=True)


def add_playable(label, url, art=None, info=None, progress=None):
    """Add a playable audio item."""
    li = xbmcgui.ListItem(label)
    li.setIsFolder(False)
    li.setProperty('IsPlayable', 'true')
    if art:
        li.setArt(art)
    if info:
        tag = li.getMusicInfoTag()
        if info.get('title'):
            tag.setTitle(info['title'])
        if info.get('artist'):
            tag.setArtist(info['artist'])
        if info.get('album'):
            tag.setAlbum(info['album'])
        if info.get('duration'):
            tag.setDuration(int(info['duration']))
        if info.get('comment'):
            tag.setComment(info['comment'])
    xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)


def format_duration(seconds):
    """Format seconds as 'Xh Ym'."""
    if not seconds:
        return ''
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    if h > 0:
        return '{}h {}m'.format(h, m)
    return '{}m'.format(m)


# ── Route handlers ──

def route_root(client):
    """Root menu: Continue Listening + libraries + settings."""
    # Continue Listening
    add_directory('[B]Continue Listening[/B]', action='continue_listening')

    # Libraries at root level
    libraries = client.get_libraries()
    for lib in libraries:
        add_directory(lib['name'], action='library', library_id=lib['id'],
                      media_type=lib['mediaType'])

    # Settings
    add_directory('[COLOR gray]Settings[/COLOR]', action='settings')

    xbmcplugin.endOfDirectory(HANDLE)


def route_settings():
    """Open addon settings dialog."""
    ADDON.openSettings()

    # After settings close, refresh the config file for inputstream.tempo.
    _write_config_file()


def route_continue_listening(client):
    """Show items currently in progress - books and individual podcast episodes."""
    items = client.get_items_in_progress()
    all_progress = client.get_all_progress()

    for item in items:
        media = item.get('media', {})
        meta = media.get('metadata', {})
        media_type = item.get('mediaType', 'book')
        item_id = item['id']

        art = {'thumb': client.cover_url(item_id),
               'poster': client.cover_url(item_id)}

        if media_type == 'podcast':
            # Show the specific in-progress episode, not the podcast folder
            ep = item.get('recentEpisode')
            if not ep:
                continue
            ep_id = ep.get('id', '')
            ep_title = ep.get('title', 'Unknown Episode')
            podcast_title = meta.get('title', '')
            duration = ep.get('audioFile', {}).get('duration', 0)

            # Look up episode progress
            progress_key = '{}-{}'.format(item_id, ep_id)
            ep_progress = all_progress.get(progress_key)

            label = ep_title
            if podcast_title:
                label = '[B]{}[/B] - {}'.format(podcast_title, ep_title)
            if ep_progress:
                pct = ep_progress.get('progress', 0) * 100
                current = ep_progress.get('currentTime', 0)
                label += '  [COLOR orange]{:.0f}% ({})[/COLOR]'.format(
                    pct, format_duration(current))

            info = {
                'title': ep_title,
                'album': podcast_title,
                'duration': duration,
            }
            play_url = build_url(action='play_episode', item_id=item_id,
                                 episode_id=ep_id)
            add_playable(label, play_url, art=art, info=info, progress=ep_progress)
        else:
            # Book — skip ebook-only items (no audio)
            if media.get('numAudioFiles', 0) == 0 and not media.get('duration'):
                continue
            title = meta.get('title', 'Unknown')
            duration = media.get('duration', 0)
            item_progress = all_progress.get(item_id)

            info = {
                'title': title,
                'artist': meta.get('authorName', ''),
                'album': meta.get('seriesName', ''),
                'duration': duration,
            }
            narrator = meta.get('narratorName', '')
            label = title
            if narrator:
                label += '  [I]{}[/I]'.format(narrator)
            if item_progress:
                pct = item_progress.get('progress', 0) * 100
                current = item_progress.get('currentTime', 0)
                label += '  [COLOR orange]{:.0f}% ({})[/COLOR]'.format(
                    pct, format_duration(current))

            play_url = build_url(action='play_book', item_id=item_id)
            add_playable(label, play_url, art=art, info=info, progress=item_progress)

    xbmcplugin.endOfDirectory(HANDLE)


def route_library(client, library_id, media_type):
    """Show sub-menus for a library."""
    if media_type == 'book':
        add_directory('All Books', action='library_items', library_id=library_id,
                      media_type=media_type)
        add_directory('Series', action='series_list', library_id=library_id)
        add_directory('Authors', action='authors_list', library_id=library_id)
        add_directory('Collections', action='collections_list', library_id=library_id)
        add_directory('Search', action='search', library_id=library_id,
                      media_type=media_type)
    elif media_type == 'podcast':
        add_directory('All Podcasts', action='library_items', library_id=library_id,
                      media_type=media_type)
        add_directory('Recent Episodes', action='recent_episodes',
                      library_id=library_id)
        add_directory('Search', action='search', library_id=library_id,
                      media_type=media_type)

    xbmcplugin.endOfDirectory(HANDLE)


def route_library_items(client, library_id, media_type, page=0):
    """Paginated list of items in a library."""
    limit = 50
    data = client.get_library_items(library_id, page=page, limit=limit)
    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    results = data.get('results', [])
    total = data.get('total', 0)

    for item in results:
        _add_library_item(client, item, media_type, library_id)

    # Next page
    if (page + 1) * limit < total:
        add_directory('[COLOR yellow]Next page ({}/{})[/COLOR]'.format(
            page + 2, (total + limit - 1) // limit),
            action='library_items', library_id=library_id,
            media_type=media_type, page=page + 1)

    xbmcplugin.endOfDirectory(HANDLE)


def _add_library_item(client, item, media_type, library_id):
    """Add a single book or podcast to the directory listing."""
    media = item.get('media', {})
    meta = media.get('metadata', {})
    title = meta.get('title', 'Unknown')
    art = {'thumb': client.cover_url(item['id']),
           'poster': client.cover_url(item['id'])}

    if media_type == 'podcast':
        num_eps = media.get('numEpisodes', 0)
        label = '{}  [COLOR gray]{} episodes[/COLOR]'.format(title, num_eps)
        add_directory(label, action='podcast_episodes',
                      item_id=item['id'], library_id=library_id)
    else:
        # Book — skip ebook-only items (no audio)
        if media.get('numAudioFiles', 0) == 0 and not media.get('duration'):
            return
        duration = media.get('duration', 0)
        narrator = meta.get('narratorName', '')
        author = meta.get('authorName', '')
        dur_str = format_duration(duration)

        label = title
        if narrator:
            label += '  [I]{}[/I]'.format(narrator)
        if dur_str:
            label += '  [COLOR gray]{}[/COLOR]'.format(dur_str)

        info = {
            'title': title,
            'artist': author,
            'album': meta.get('seriesName', ''),
            'duration': duration,
            'comment': meta.get('description', ''),
        }
        play_url = build_url(action='play_book', item_id=item['id'])
        add_playable(label, play_url, art=art, info=info)


def route_series_list(client, library_id, page=0):
    """List all series in a book library."""
    limit = 50
    data = client.get_series(library_id, page=page, limit=limit)
    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    results = data.get('results', [])
    total = data.get('total', 0)

    for series in results:
        name = series.get('name', 'Unknown')
        books = series.get('books', [])
        label = '{}  [COLOR gray]{} books[/COLOR]'.format(name, len(books))
        add_directory(label, action='series_detail',
                      library_id=library_id, series_id=series['id'])

    if (page + 1) * limit < total:
        add_directory('[COLOR yellow]Next page[/COLOR]',
                      action='series_list', library_id=library_id, page=page + 1)

    xbmcplugin.endOfDirectory(HANDLE)


def route_series_detail(client, library_id, series_id):
    """Show books in a series (filter library items by series ID)."""
    from base64 import b64encode
    filter_str = 'series.' + b64encode(series_id.encode()).decode()
    data = client.get_library_items(library_id, limit=100, filter_str=filter_str)
    if data:
        for item in data.get('results', []):
            _add_library_item(client, item, 'book', library_id)
    xbmcplugin.endOfDirectory(HANDLE)


def route_authors_list(client, library_id):
    """List all authors."""
    authors = client.get_authors(library_id)
    for author in sorted(authors, key=lambda a: a.get('name', '')):
        name = author.get('name', 'Unknown')
        count = author.get('numBooks', 0)
        label = '{}  [COLOR gray]{} books[/COLOR]'.format(name, count)
        art = {}
        if author.get('imagePath'):
            art = {'thumb': client.author_image_url(author['id'])}
        url = build_url(action='author_books', library_id=library_id,
                        author_id=author['id'], author_name=name)
        li = xbmcgui.ListItem(label)
        li.setIsFolder(True)
        if art:
            li.setArt(art)
        xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=True)

    xbmcplugin.endOfDirectory(HANDLE)


def route_author_books(client, library_id, author_id, author_name):
    """Show books by a specific author (filter library items by author ID)."""
    from base64 import b64encode
    filter_str = 'authors.' + b64encode(author_id.encode()).decode()
    data = client.get_library_items(library_id, limit=100, filter_str=filter_str)
    if data:
        for item in data.get('results', []):
            _add_library_item(client, item, 'book', library_id)
    xbmcplugin.endOfDirectory(HANDLE)


def route_collections_list(client, library_id):
    """List all collections."""
    collections = client.get_collections(library_id)
    for col in collections:
        name = col.get('name', 'Unknown')
        books = col.get('books', [])
        label = '{}  [COLOR gray]{} books[/COLOR]'.format(name, len(books))
        add_directory(label, action='collection_detail',
                      library_id=library_id, collection_id=col['id'])
    xbmcplugin.endOfDirectory(HANDLE)


def route_collection_detail(client, library_id, collection_id):
    """Show books in a collection."""
    from abs_api import ABSClient
    data = client._get('/api/collections/{}'.format(collection_id))
    if data:
        for item in data.get('books', []):
            _add_library_item(client, item, 'book', library_id)
    xbmcplugin.endOfDirectory(HANDLE)


def route_podcast_episodes(client, item_id, library_id):
    """List episodes for a podcast."""
    data = client.get_item(item_id, expanded=True)
    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    media = data.get('media', {})
    meta = media.get('metadata', {})
    podcast_title = meta.get('title', '')
    episodes = media.get('episodes', [])

    # Sort by most recent first
    episodes.sort(key=lambda e: e.get('publishedAt', 0) or 0, reverse=True)

    for ep in episodes:
        ep_title = ep.get('title', 'Unknown Episode')
        duration = ep.get('audioFile', {}).get('duration', 0)
        dur_str = format_duration(duration)

        label = ep_title
        if dur_str:
            label += '  [COLOR gray]{}[/COLOR]'.format(dur_str)

        art = {'thumb': client.cover_url(item_id),
               'poster': client.cover_url(item_id)}
        info = {
            'title': ep_title,
            'album': podcast_title,
            'duration': duration,
            'comment': ep.get('description', ''),
        }
        play_url = build_url(action='play_episode', item_id=item_id,
                             episode_id=ep['id'])
        add_playable(label, play_url, art=art, info=info)

    xbmcplugin.endOfDirectory(HANDLE)


def route_recent_episodes(client, library_id):
    """Show recently added podcast episodes."""
    data = client.get_recent_episodes(library_id, limit=50)
    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    episodes = data.get('episodes', [])
    for ep in episodes:
        item_id = ep.get('libraryItemId', '')
        ep_id = ep.get('id', '')
        ep_title = ep.get('title', 'Unknown')
        podcast_title = ep.get('audioFile', {}).get('metaTags', {}).get('tagAlbum', '')
        duration = ep.get('audioFile', {}).get('duration', 0)
        dur_str = format_duration(duration)

        label = ep_title
        if podcast_title:
            label = '[B]{}[/B] - {}'.format(podcast_title, ep_title)
        if dur_str:
            label += '  [COLOR gray]{}[/COLOR]'.format(dur_str)

        art = {'thumb': client.cover_url(item_id),
               'poster': client.cover_url(item_id)}
        info = {
            'title': ep_title,
            'album': podcast_title,
            'duration': duration,
        }
        play_url = build_url(action='play_episode', item_id=item_id,
                             episode_id=ep_id)
        add_playable(label, play_url, art=art, info=info)

    xbmcplugin.endOfDirectory(HANDLE)


def route_search(client, library_id, media_type):
    """Prompt user for search query and show results."""
    kb = xbmc.Keyboard('', 'Search')
    kb.doModal()
    if not kb.isConfirmed():
        xbmcplugin.endOfDirectory(HANDLE)
        return

    query = kb.getText().strip()
    if not query:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    data = client.search(library_id, query)
    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    if media_type == 'book':
        for entry in data.get('book', []):
            item = entry.get('libraryItem', entry)
            _add_library_item(client, item, 'book', library_id)
        for entry in data.get('series', []):
            series = entry.get('series', entry)
            name = series.get('name', 'Unknown')
            books = series.get('books', [])
            label = '[Series] {}  [COLOR gray]{} books[/COLOR]'.format(name, len(books))
            add_directory(label, action='series_detail',
                          library_id=library_id, series_id=series['id'])
        for entry in data.get('authors', []):
            author = entry.get('author', entry)
            name = author.get('name', 'Unknown')
            label = '[Author] {}'.format(name)
            add_directory(label, action='author_books', library_id=library_id,
                          author_id=author['id'], author_name=name)
    elif media_type == 'podcast':
        for entry in data.get('podcast', []):
            item = entry.get('libraryItem', entry)
            _add_library_item(client, item, 'podcast', library_id)

    xbmcplugin.endOfDirectory(HANDLE)


# ── Playback ──

PROFILE_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
SESSION_FILE = os.path.join(PROFILE_DIR, 'session.json')
SPEEDS_FILE = os.path.join(PROFILE_DIR, 'speeds.json')
SLEEP_FILE = os.path.join(PROFILE_DIR, 'sleep_timer')
# Standardised files shared with inputstream.tempo
TEMPO_FILE = xbmcvfs.translatePath('special://temp/inputstream_tempo')
CONFIG_FILE = xbmcvfs.translatePath('special://temp/inputstream_tempo_config')


def _save_session(data):
    """Write session info to disk for the background service to pick up."""
    os.makedirs(PROFILE_DIR, exist_ok=True)
    with open(SESSION_FILE, 'w') as f:
        json.dump(data, f)


def _get_float(setting_id, default):
    try:
        return float(ADDON.getSetting(setting_id))
    except (ValueError, TypeError):
        return default


def _speed_config():
    """Return (step, min, max) from settings, with sane defaults."""
    step = _get_float('speed_step', 0.10)
    lo = _get_float('min_speed', 1.0)
    hi = _get_float('max_speed', 3.0)
    # Defensive: make sure min <= max; fall back to sane range if inverted.
    if lo > hi:
        lo, hi = 0.5, 5.0
    return step, lo, hi


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _get_tempo(media_type='book'):
    """Default playback speed for the given media type, clamped to min/max."""
    _step, lo, hi = _speed_config()
    raw = _get_float('podcast_speed' if media_type == 'podcast' else 'book_speed', 1.0)
    return round(_clamp(raw, lo, hi), 2)


def _write_tempo(tempo):
    """Write tempo value to the shared inputstream.tempo file."""
    with open(TEMPO_FILE, 'w') as f:
        f.write(str(tempo))


def _write_config_file():
    """Write {step, min, max} as JSON for inputstream.tempo's speed.py."""
    step, lo, hi = _speed_config()
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'step': step, 'min': lo, 'max': hi}, f)
    except IOError:
        pass


def _load_book_speed(item_id):
    """Load saved speed for a specific book. Returns None if not found."""
    try:
        if os.path.exists(SPEEDS_FILE):
            with open(SPEEDS_FILE, 'r') as f:
                speeds = json.load(f)
                return speeds.get(item_id)
    except Exception:
        pass
    return None


def _save_book_speed(item_id, speed):
    """Save speed for a specific book."""
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


def _resolve_playback(client, item_id, episode_id=None):
    """Create an ABS session and resolve the stream URL via inputstream.tempo."""
    # Clear the playlist so Kodi doesn't auto-advance to next item
    xbmc.PlayList(xbmc.PLAYLIST_MUSIC).clear()

    session = client.start_playback(item_id, episode_id=episode_id)
    if not session:
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    tracks = session.get('audioTracks', [])
    if not tracks:
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    meta = session.get('mediaMetadata', {})
    title = meta.get('title', '')
    authors = meta.get('authors', [])
    author_str = ', '.join(a.get('name', '') for a in authors) if authors else meta.get('author', '')
    cover_url = client.cover_url(item_id)
    start_time = session.get('currentTime', 0)
    duration = session.get('duration', 0)

    # Save session info for the background service (handles sync + resume seek)
    _save_session({
        'session_id': session['id'],
        'item_id': item_id,
        'episode_id': episode_id,
        'duration': duration,
        'start_time': start_time,
        'started_at': time.time(),
        'chapters': session.get('chapters', []),
        'media_metadata': {
            'title': title,
            'author': author_str,
        },
    })

    track = tracks[0]
    url = client.stream_url(track['contentUrl'])

    # Per-item speed takes priority over global setting
    # For podcasts, speed is keyed by podcast item_id (shared across episodes)
    media_type = session.get('mediaType', 'book')
    use_per_item = ADDON.getSetting('per_book_speed') != 'false'
    saved_speed = _load_book_speed(item_id) if use_per_item else None
    raw_tempo = saved_speed if saved_speed is not None else _get_tempo(media_type)
    # Clamp against current settings in case min/max has been tightened since save.
    _step, lo, hi = _speed_config()
    tempo = round(_clamp(raw_tempo, lo, hi), 2)
    _write_tempo(tempo)
    _write_config_file()

    li = xbmcgui.ListItem(path=url)
    li.setArt({'thumb': cover_url, 'poster': cover_url})
    li.setContentLookup(False)

    tag = li.getMusicInfoTag()
    tag.setTitle(title)
    if author_str:
        tag.setArtist(author_str)
    tag.setDuration(int(duration))

    # Route through inputstream.tempo for playback speed control
    li.setProperty('inputstream', 'inputstream.tempo')
    li.setProperty('inputstream.tempo.mime_type', track.get('mimeType', 'audio/mp4'))
    if tempo != 1.0:
        li.setProperty('inputstream.tempo.tempo', str(tempo))
    li.setProperty('inputstream.tempo.tempo_file', TEMPO_FILE)

    xbmcplugin.setResolvedUrl(HANDLE, True, li)


def route_play_book(client, item_id):
    _resolve_playback(client, item_id)


def route_play_episode(client, item_id, episode_id):
    _resolve_playback(client, item_id, episode_id=episode_id)


# ── Router ──

def router():
    """Parse the plugin URL and dispatch to the right handler."""
    params = parse_qs(sys.argv[2][1:])

    # Unwrap single-value lists
    args = {}
    for k, v in params.items():
        args[k] = v[0] if len(v) == 1 else v

    client = get_client()
    if not client:
        return

    action = args.get('action', '')

    if not action:
        route_root(client)
    elif action == 'continue_listening':
        route_continue_listening(client)
    elif action == 'library':
        route_library(client, args['library_id'], args['media_type'])
    elif action == 'library_items':
        route_library_items(client, args['library_id'], args['media_type'],
                            page=int(args.get('page', 0)))
    elif action == 'series_list':
        route_series_list(client, args['library_id'],
                          page=int(args.get('page', 0)))
    elif action == 'series_detail':
        route_series_detail(client, args['library_id'], args['series_id'])
    elif action == 'authors_list':
        route_authors_list(client, args['library_id'])
    elif action == 'author_books':
        route_author_books(client, args['library_id'], args['author_id'],
                           args['author_name'])
    elif action == 'collections_list':
        route_collections_list(client, args['library_id'])
    elif action == 'collection_detail':
        route_collection_detail(client, args['library_id'], args['collection_id'])
    elif action == 'podcast_episodes':
        route_podcast_episodes(client, args['item_id'], args.get('library_id', ''))
    elif action == 'recent_episodes':
        route_recent_episodes(client, args['library_id'])
    elif action == 'search':
        route_search(client, args['library_id'], args['media_type'])
    elif action == 'play_book':
        route_play_book(client, args['item_id'])
    elif action == 'play_episode':
        route_play_episode(client, args['item_id'], args['episode_id'])
    elif action == 'settings':
        route_settings()


if __name__ == '__main__':
    router()
