"""AudioBookShelf API client."""

import requests
import xbmc


class ABSClient:
    """Client for the AudioBookShelf REST API."""

    def __init__(self, server_url, api_key=None, username=None, password=None):
        self.server_url = server_url.rstrip('/')
        self.token = api_key
        self.session = requests.Session()
        if not self.token and username and password:
            self._login(username, password)
        if self.token:
            self.session.headers['Authorization'] = 'Bearer ' + self.token

    def _login(self, username, password):
        """Authenticate with username/password and store the token."""
        resp = self._post('/login', json={'username': username, 'password': password})
        if resp and 'user' in resp:
            self.token = resp['user'].get('token', '')

    def _get(self, path, params=None):
        url = self.server_url + path
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            xbmc.log('ABSClient GET {} failed: {}'.format(path, e), xbmc.LOGERROR)
            return None

    def _post(self, path, json=None):
        url = self.server_url + path
        try:
            r = self.session.post(url, json=json or {}, timeout=15)
            r.raise_for_status()
            ct = r.headers.get('content-type', '')
            if 'application/json' in ct and r.text:
                return r.json()
            return {}
        except Exception as e:
            xbmc.log('ABSClient POST {} failed: {}'.format(path, e), xbmc.LOGERROR)
            return None

    def _patch(self, path, json=None):
        url = self.server_url + path
        try:
            r = self.session.patch(url, json=json or {}, timeout=15)
            r.raise_for_status()
            if r.text:
                return r.json()
            return {}
        except Exception as e:
            xbmc.log('ABSClient PATCH {} failed: {}'.format(path, e), xbmc.LOGERROR)
            return None

    # ── Libraries ──

    def get_libraries(self):
        data = self._get('/api/libraries')
        return data.get('libraries', []) if data else []

    def get_library(self, library_id):
        return self._get('/api/libraries/{}'.format(library_id))

    # ── Library items (books / podcasts) ──

    def get_library_items(self, library_id, page=0, limit=50, sort=None, desc=False, filter_str=None):
        params = {'page': page, 'limit': limit}
        if sort:
            params['sort'] = sort
        if desc:
            params['desc'] = 1
        if filter_str:
            params['filter'] = filter_str
        return self._get('/api/libraries/{}/items'.format(library_id), params=params)

    def get_item(self, item_id, expanded=True):
        params = {'expanded': 1} if expanded else {}
        return self._get('/api/items/{}'.format(item_id), params=params)

    # ── Series ──

    def get_series(self, library_id, page=0, limit=50):
        return self._get('/api/libraries/{}/series'.format(library_id),
                         params={'page': page, 'limit': limit})

    def get_series_detail(self, library_id, series_id):
        return self._get('/api/libraries/{}/series/{}'.format(library_id, series_id))

    # ── Authors ──

    def get_authors(self, library_id):
        data = self._get('/api/libraries/{}/authors'.format(library_id))
        return data.get('authors', []) if data else []

    # ── Collections ──

    def get_collections(self, library_id):
        data = self._get('/api/libraries/{}/collections'.format(library_id))
        return data.get('results', []) if data else []

    # ── Search ──

    def search(self, library_id, query, limit=20):
        return self._get('/api/libraries/{}/search'.format(library_id),
                         params={'q': query, 'limit': limit})

    # ── Podcast episodes ──

    def get_recent_episodes(self, library_id, limit=50):
        return self._get('/api/libraries/{}/recent-episodes'.format(library_id),
                         params={'limit': limit})

    # ── Continue listening ──

    def get_items_in_progress(self):
        data = self._get('/api/me/items-in-progress')
        return data.get('libraryItems', []) if data else []

    def get_all_progress(self):
        """Fetch /api/me and return a dict of progress keyed by libraryItemId.
        For podcast episodes, key is 'libraryItemId-episodeId'."""
        data = self._get('/api/me')
        if not data:
            return {}
        progress = {}
        for p in data.get('mediaProgress', []):
            item_id = p.get('libraryItemId', '')
            ep_id = p.get('episodeId')
            if ep_id:
                progress['{}-{}'.format(item_id, ep_id)] = p
            else:
                progress[item_id] = p
        return progress

    # ── Playback sessions ──

    def start_playback(self, item_id, episode_id=None, use_hls=False):
        """Create a playback session. Direct play by default, HLS if use_hls=True."""
        path = '/api/items/{}/play'.format(item_id)
        if episode_id:
            path = '/api/items/{}/play/{}'.format(item_id, episode_id)
        body = {
            'deviceInfo': {
                'clientName': 'KoShelf',
                'deviceId': 'kodi-koshelf',
            },
        }
        if not use_hls:
            body['forceDirectPlay'] = True
        else:
            body['forceTranscode'] = True
        return self._post(path, json=body)

    def sync_session(self, session_id, current_time, duration, time_listened):
        return self._post('/api/session/{}/sync'.format(session_id), json={
            'currentTime': current_time,
            'duration': duration,
            'timeListened': time_listened,
        })

    def close_session(self, session_id):
        return self._post('/api/session/{}/close'.format(session_id))

    # ── Progress ──

    def get_progress(self, item_id, episode_id=None):
        path = '/api/me/progress/{}'.format(item_id)
        if episode_id:
            path += '/' + episode_id
        return self._get(path)

    def update_progress(self, item_id, current_time, duration, is_finished=False, episode_id=None):
        path = '/api/me/progress/{}'.format(item_id)
        if episode_id:
            path += '/' + episode_id
        progress = current_time / duration if duration > 0 else 0
        return self._patch(path, json={
            'currentTime': current_time,
            'progress': progress,
            'isFinished': is_finished,
        })

    # ── URLs ──

    def cover_url(self, item_id):
        return '{}/api/items/{}/cover'.format(self.server_url, item_id)

    def author_image_url(self, author_id):
        return '{}/api/authors/{}/image'.format(self.server_url, author_id)

    def stream_url(self, content_url):
        """Turn a relative content URL from a play session into an absolute URL."""
        if content_url.startswith('http'):
            return content_url
        url = self.server_url + content_url
        if self.token and '?' not in url:
            url += '?token=' + self.token
        elif self.token:
            url += '&token=' + self.token
        return url
