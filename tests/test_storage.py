"""Persistence checks without contacting any hosted database."""
import json
import httpx
import pytest

from storage import MeetingNotFound, MeetingStore, StorageUnavailable


@pytest.fixture(autouse=True)
def clean_storage_environment(monkeypatch, tmp_path):
    for name in ('SUPABASE_URL', 'SUPABASE_SERVICE_KEY', 'VERCEL', 'APPWRITE_ENDPOINT',
                 'APPWRITE_PROJECT_ID', 'APPWRITE_API_KEY', 'APPWRITE_DATABASE_ID'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('MEETCOOL_DB', str(tmp_path / 'meetings.sqlite3'))


def test_sqlite_survives_a_new_store_instance():
    store = MeetingStore()
    meeting = {'id': 'first', 'name': 'Café'}
    store.create(meeting, 'private-organizer-token')
    store.add_participant('first', {'id': 'guest', 'name': 'Camille', 'lat': 48.8, 'lng': 2.3})
    meeting['status'] = 'confirmed'
    store.update(meeting)
    second = MeetingStore()
    token, saved, people = second.retrieve('first')
    assert token == 'private-organizer-token'
    assert saved == meeting
    assert people[0]['name'] == 'Camille'
    assert second.config() == {'storage': 'sqlite', 'persistent': True, 'shared': False}


def test_missing_local_meeting_is_explicit():
    store = MeetingStore()
    with pytest.raises(MeetingNotFound):
        store.retrieve('missing')
    with pytest.raises(MeetingNotFound):
        store.update({'id': 'missing'})
    with pytest.raises(MeetingNotFound):
        store.add_participant('missing', {'id': 'guest'})


def test_vercel_without_database_never_creates_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv('VERCEL', '1')
    store = MeetingStore()
    assert store.config() == {'storage': 'unconfigured', 'persistent': False, 'shared': False}
    for operation in [lambda: store.create({'id': 'x'}, 'token'), lambda: store.retrieve('x'), lambda: store.update({'id': 'x'}), lambda: store.add_participant('x', {'id': 'p'})]:
        with pytest.raises(StorageUnavailable, match='pas encore connectée'):
            operation()
    assert not (tmp_path / 'meetings.sqlite3').exists()


def test_incomplete_supabase_configuration_is_not_silently_local(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    assert MeetingStore().config()['storage'] == 'unconfigured'


@pytest.mark.parametrize('key,has_bearer', [('sb_secret_test_value', False), ('legacy.service.role', True)])
def test_supabase_uses_server_headers_and_reads_payloads(monkeypatch, key, has_bearer):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co/')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', key)
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        if url.endswith('meetcool_meetings'):
            data = [{'admin_token': 'private', 'payload': {'id': 'x'}}]
        else:
            data = [{'payload': {'id': 'p', 'name': 'Camille'}}]
        return httpx.Response(200, json=data, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, 'request', request)
    store = MeetingStore()
    assert store.retrieve('x') == ('private', {'id': 'x'}, [{'id': 'p', 'name': 'Camille'}])
    assert store.config()['shared']
    headers = requests[0][2]['headers']
    assert headers['apikey'] == key
    assert ('Authorization' in headers) is has_bearer
    assert requests[0][2]['params']['id'] == 'eq.x'


def test_supabase_failure_does_not_expose_credentials_or_upstream_body(monkeypatch):
    secret = 'sb_secret_do_not_leak'
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', secret)

    def request(method, url, **kwargs):
        return httpx.Response(401, json={'error': secret}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, 'request', request)
    with pytest.raises(StorageUnavailable) as error:
        MeetingStore().retrieve('x')
    assert secret not in str(error.value)


def test_supabase_missing_meeting(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'sb_secret_test')
    monkeypatch.setattr(httpx, 'request', lambda method, url, **kwargs: httpx.Response(200, json=[], request=httpx.Request(method, url)))
    with pytest.raises(MeetingNotFound):
        MeetingStore().retrieve('missing')


def test_supabase_participants_are_paginated(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'sb_secret_test')
    people = [{'payload': {'id': f'p-{i}'}} for i in range(1205)]
    offsets = []
    def request(method, url, **kwargs):
        if url.endswith('meetcool_meetings'):
            rows = [{'admin_token': 'private', 'payload': {'id': 'x'}}]
        else:
            params = kwargs['params']
            offset, limit = int(params['offset']), int(params['limit'])
            offsets.append(offset)
            assert params['order'] == 'id.asc'
            rows = people[offset:offset + limit]
        return httpx.Response(200, json=rows, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx, 'request', request)
    _, _, retrieved = MeetingStore().retrieve('x')
    assert retrieved == [p['payload'] for p in people]
    assert offsets == [0, 200, 400, 600, 800, 1000, 1200]


@pytest.fixture
def appwrite_environment(monkeypatch):
    monkeypatch.setenv('APPWRITE_ENDPOINT', 'https://fra.cloud.appwrite.io/v1/')
    monkeypatch.setenv('APPWRITE_PROJECT_ID', 'project')
    monkeypatch.setenv('APPWRITE_API_KEY', 'server-appwrite-secret')


def test_appwrite_create_join_update_and_retrieve(monkeypatch, appwrite_environment):
    records = {'meetings': {}, 'participants': {}}
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        assert kwargs['headers']['X-Appwrite-Project'] == 'project'
        assert kwargs['headers']['X-Appwrite-Key'] == 'server-appwrite-secret'
        assert '/tablesdb/meetcool/tables/' in url
        table = url.split('/tables/')[1].split('/')[0]
        payload = kwargs['json']
        if method == 'POST':
            assert payload['permissions'] == []
            result = {'$id': payload['rowId'], **payload['data']}
            records[table][payload['rowId']] = result
        elif method == 'PATCH':
            assert payload['permissions'] == []
            result = records[table][url.rsplit('/', 1)[1]]
            result.update(payload['data'])
        elif table == 'meetings':
            result = records[table][url.rsplit('/', 1)[1]]
        else:
            queries = [json.loads(value) for key, value in kwargs['params'] if key == 'queries[]']
            equal = next(query for query in queries if query['method'] == 'equal')
            assert equal == {'method': 'equal', 'attribute': 'meeting_id', 'values': ['m1']}
            result = {'rows': list(records[table].values()), 'total': len(records[table])}
        return httpx.Response(200, json=result, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, 'request', request)
    store = MeetingStore()
    assert store.config() == {'storage': 'appwrite', 'persistent': True, 'shared': True}
    meeting = {'id': 'm1', 'name': 'Café'}
    store.create(meeting, 'private-admin')
    store.add_participant('m1', {'id': 'p1', 'name': 'Camille'})
    meeting['status'] = 'confirmed'
    store.update(meeting)
    assert store.retrieve('m1') == ('private-admin', meeting, [{'id': 'p1', 'name': 'Camille'}])
    assert json.loads(records['meetings']['m1']['payload']) == meeting
    assert records['participants']['p1']['meeting_id'] == 'm1'
    assert len(calls) == 5


def test_appwrite_participants_cursor_pagination(monkeypatch, appwrite_environment):
    people = [{'$id': f'p{i:03d}', 'payload': json.dumps({'id': f'p{i:03d}'})} for i in range(205)]
    cursors = []

    def request(method, url, **kwargs):
        if '/meetings/rows/' in url:
            result = {'admin_token': 'private', 'payload': '{"id":"m1"}'}
        else:
            queries = [json.loads(value) for _, value in kwargs['params']]
            cursor = next((query['values'][0] for query in queries if query['method'] == 'cursorAfter'), None)
            cursors.append(cursor)
            index = int(cursor[1:]) + 1 if cursor else 0
            assert next(query['values'][0] for query in queries if query['method'] == 'limit') == 100
            result = {'rows': people[index:index + 100], 'total': len(people)}
        return httpx.Response(200, json=result, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, 'request', request)
    _, _, result = MeetingStore().retrieve('m1')
    assert len(result) == 205
    assert cursors == [None, 'p099', 'p199']
    assert result[-1] == {'id': 'p204'}


def test_appwrite_missing_meeting_and_failed_write_are_sanitized(monkeypatch, appwrite_environment):
    status = 404

    def request(method, url, **kwargs):
        return httpx.Response(status, json={'message': 'server-appwrite-secret'}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, 'request', request)
    store = MeetingStore()
    with pytest.raises(MeetingNotFound):
        store.retrieve('missing')
    status = 401
    with pytest.raises(StorageUnavailable) as error:
        store.create({'id': 'x'}, 'private')
    assert 'server-appwrite-secret' not in str(error.value)


def test_incomplete_appwrite_does_not_fall_back_to_supabase(monkeypatch):
    monkeypatch.setenv('APPWRITE_PROJECT_ID', 'project')
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'sb_secret_test')
    assert MeetingStore().config()['storage'] == 'unconfigured'


def test_appwrite_requires_secure_endpoint(monkeypatch, appwrite_environment):
    monkeypatch.setenv('APPWRITE_ENDPOINT', 'http://remote.example/v1')
    with pytest.raises(StorageUnavailable, match='HTTPS'):
        MeetingStore()
