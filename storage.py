"""Meeting persistence: SQLite or server-only Appwrite/Supabase REST access.

A Vercel deployment without shared database credentials deliberately does not
write to ephemeral disk. No hosted resources are created by this module.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import quote, urlparse

import httpx


class StorageUnavailable(Exception):
    """The configured storage cannot safely serve the request."""


class MeetingNotFound(Exception):
    """No meeting exists for the supplied identifier."""


class MeetingStore:
    def __init__(self):
        self.url = os.environ.get('SUPABASE_URL', '').rstrip('/')
        self._key = os.environ.get('SUPABASE_SERVICE_KEY', '')
        self.appwrite_url = os.environ.get('APPWRITE_ENDPOINT', '').rstrip('/')
        self.appwrite_project = os.environ.get('APPWRITE_PROJECT_ID', '')
        self._appwrite_key = os.environ.get('APPWRITE_API_KEY', '')
        self.appwrite_database = os.environ.get('APPWRITE_DATABASE_ID', 'meetcool')
        self.path = Path(os.environ.get('MEETCOOL_DB', str(Path(__file__).parent / 'meetcool.sqlite3')))
        appwrite_values = (self.appwrite_url, self.appwrite_project, self._appwrite_key)
        if all(appwrite_values):
            parsed = urlparse(self.appwrite_url)
            local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
            if not parsed.hostname or (parsed.scheme != 'https' and not (local and parsed.scheme == 'http')):
                raise StorageUnavailable('L’adresse Appwrite doit utiliser HTTPS.')
            self.backend = 'appwrite'
        elif any(appwrite_values):
            self.backend = 'unconfigured'
        elif self.url and self._key:
            parsed = urlparse(self.url)
            local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
            if not parsed.hostname or (parsed.scheme != 'https' and not (local and parsed.scheme == 'http')):
                raise StorageUnavailable('L’adresse Supabase doit utiliser HTTPS.')
            self.backend = 'supabase'
        elif self.url or self._key or os.environ.get('VERCEL'):
            self.backend = 'unconfigured'
        else:
            self.backend = 'sqlite'
            with self._connection() as connection:
                connection.execute('CREATE TABLE IF NOT EXISTS meetings (id TEXT PRIMARY KEY, admin_token TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)')
                connection.execute('CREATE TABLE IF NOT EXISTS participants (meeting_id TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(meeting_id,id))')

    def config(self):
        return {
            'storage': self.backend,
            'persistent': self.backend != 'unconfigured',
            'shared': self.backend in ('supabase', 'appwrite'),
        }

    def _require_storage(self):
        if self.backend == 'unconfigured':
            raise StorageUnavailable('La base partagée n’est pas encore connectée. Les réunions et invitations seront disponibles après la configuration du stockage partagé.')

    @contextmanager
    def _connection(self):
        connection = None
        try:
            connection = sqlite3.connect(self.path, timeout=5)
            connection.row_factory = sqlite3.Row
            with connection:
                yield connection
        except sqlite3.Error:
            raise StorageUnavailable('Le stockage local est temporairement indisponible.') from None
        finally:
            if connection is not None:
                connection.close()

    def _request(self, method, table, *, params=None, payload=None):
        headers = {'apikey': self._key, 'Content-Type': 'application/json'}
        # Modern sb_secret keys are opaque, not JWTs. Supabase accepts them via
        # apikey; only legacy service_role JWTs belong in Authorization.
        if not self._key.startswith('sb_secret_'):
            headers['Authorization'] = f'Bearer {self._key}'
        if method in ('POST', 'PATCH'):
            headers['Prefer'] = 'return=representation'
        try:
            response = httpx.request(
                method, f'{self.url}/rest/v1/{table}', headers=headers,
                params=params, json=payload, timeout=10,
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                raise ValueError('Unexpected storage response')
            return rows
        except (httpx.HTTPError, ValueError):
            # Upstream bodies and exception strings may include operational
            # details; neither credentials nor backend responses reach clients.
            raise StorageUnavailable('La base partagée est temporairement indisponible. Réessaie dans un instant.') from None

    def _appwrite_request(self, method, table, *, row_id=None, params=None, payload=None):
        path = f'/tablesdb/{quote(self.appwrite_database, safe="")}/tables/{table}/rows'
        if row_id is not None:
            path += '/' + quote(str(row_id), safe='')
        headers = {
            'X-Appwrite-Project': self.appwrite_project,
            'X-Appwrite-Key': self._appwrite_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        try:
            response = httpx.request(method, self.appwrite_url + path, headers=headers,
                                     params=params, json=payload, timeout=10)
            if response.status_code == 404 and table == 'meetings' and row_id is not None:
                raise MeetingNotFound(row_id)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError('Unexpected storage response')
            return result
        except (httpx.HTTPError, ValueError):
            raise StorageUnavailable('La base partagée est temporairement indisponible. Réessaie dans un instant.') from None

    @staticmethod
    def _decode_appwrite_payload(row):
        try:
            payload = json.loads(row['payload'])
            if not isinstance(payload, dict):
                raise ValueError('Unexpected storage payload')
            return payload
        except (KeyError, TypeError, ValueError):
            raise StorageUnavailable('Les données de la réunion sont temporairement indisponibles.') from None

    def create(self, meeting, admin_token):
        self._require_storage()
        created = datetime.now(timezone.utc).isoformat()
        if self.backend == 'appwrite':
            self._appwrite_request('POST', 'meetings', payload={
                'rowId': meeting['id'], 'permissions': [],
                'data': {'admin_token': admin_token, 'payload': json.dumps(meeting)},
            })
        elif self.backend == 'supabase':
            self._request('POST', 'meetcool_meetings', payload={
                'id': meeting['id'], 'admin_token': admin_token,
                'payload': meeting, 'created_at': created,
            })
        else:
            with self._connection() as connection:
                connection.execute('INSERT INTO meetings VALUES (?,?,?,?)', (meeting['id'], admin_token, json.dumps(meeting), created))

    def retrieve(self, meeting_id):
        self._require_storage()
        if self.backend == 'appwrite':
            meeting = self._appwrite_request('GET', 'meetings', row_id=meeting_id)
            people = []
            cursor = None
            while True:
                queries = [
                    {'method': 'equal', 'attribute': 'meeting_id', 'values': [meeting_id]},
                    {'method': 'limit', 'values': [100]},
                    {'method': 'orderAsc', 'attribute': '$id'},
                ]
                if cursor is not None:
                    queries.append({'method': 'cursorAfter', 'values': [cursor]})
                params = [('queries[]', json.dumps(query, separators=(',', ':'))) for query in queries]
                result = self._appwrite_request('GET', 'participants', params=params)
                page = result.get('rows')
                if not isinstance(page, list):
                    raise StorageUnavailable('Les participants sont temporairement indisponibles.')
                people.extend(self._decode_appwrite_payload(row) for row in page)
                if len(page) < 100:
                    break
                next_cursor = page[-1].get('$id')
                if not next_cursor or next_cursor == cursor:
                    raise StorageUnavailable('Les participants sont temporairement indisponibles.')
                cursor = next_cursor
            return meeting['admin_token'], self._decode_appwrite_payload(meeting), people
        if self.backend == 'supabase':
            rows = self._request('GET', 'meetcool_meetings', params={
                'id': f'eq.{meeting_id}', 'select': 'admin_token,payload', 'limit': '1',
            })
            if not rows:
                raise MeetingNotFound(meeting_id)
            people = []
            while True:
                page = self._request('GET', 'meetcool_participants', params={
                    'meeting_id': f'eq.{meeting_id}', 'select': 'payload',
                    'order': 'id.asc', 'limit': '200', 'offset': str(len(people)),
                })
                people.extend(page)
                if len(page) < 200:
                    break
            return rows[0]['admin_token'], rows[0]['payload'], [row['payload'] for row in people]
        with self._connection() as connection:
            row = connection.execute('SELECT admin_token,payload FROM meetings WHERE id=?', (meeting_id,)).fetchone()
            if row is None:
                raise MeetingNotFound(meeting_id)
            people = connection.execute('SELECT payload FROM participants WHERE meeting_id=? ORDER BY rowid', (meeting_id,)).fetchall()
            return row['admin_token'], json.loads(row['payload']), [json.loads(person['payload']) for person in people]

    def add_participant(self, meeting_id, participant):
        self._require_storage()
        if self.backend == 'appwrite':
            self._appwrite_request('POST', 'participants', payload={
                'rowId': participant['id'], 'permissions': [],
                'data': {'meeting_id': meeting_id, 'payload': json.dumps(participant)},
            })
        elif self.backend == 'supabase':
            self._request('POST', 'meetcool_participants', payload={
                'meeting_id': meeting_id, 'id': participant['id'], 'payload': participant,
            })
        else:
            with self._connection() as connection:
                if connection.execute('SELECT 1 FROM meetings WHERE id=?', (meeting_id,)).fetchone() is None:
                    raise MeetingNotFound(meeting_id)
                connection.execute('INSERT INTO participants VALUES (?,?,?)', (meeting_id, participant['id'], json.dumps(participant)))

    def update(self, meeting):
        self._require_storage()
        if self.backend == 'appwrite':
            self._appwrite_request('PATCH', 'meetings', row_id=meeting['id'], payload={
                'data': {'payload': json.dumps(meeting)}, 'permissions': [],
            })
        elif self.backend == 'supabase':
            rows = self._request('PATCH', 'meetcool_meetings', params={
                'id': f'eq.{meeting["id"]}',
            }, payload={'payload': meeting})
            if not rows:
                raise MeetingNotFound(meeting['id'])
        else:
            with self._connection() as connection:
                result = connection.execute('UPDATE meetings SET payload=? WHERE id=?', (json.dumps(meeting), meeting['id']))
                if result.rowcount == 0:
                    raise MeetingNotFound(meeting['id'])
