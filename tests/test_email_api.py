"""End-to-end email/privacy checks against a temporary local database.

Delivery is mocked: these tests never contact Appwrite or send real mail.
"""
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
import httpx
import pytest

import server
from storage import MeetingStore


class FakeMailer:
    def __init__(self):
        self.calls = []
        self.statuses = {}

    def config(self):
        return {'configured': True, 'provider': 'appwrite'}

    def send(self, event_id, recipient, subject, content):
        self.calls.append({'event_id': event_id, 'recipient': recipient, 'subject': subject, 'content': content})
        return self.statuses.get(recipient, 'queued') if recipient else 'skipped'


@pytest.fixture
def email_api(monkeypatch, tmp_path):
    for name in ('SUPABASE_URL', 'SUPABASE_SERVICE_KEY', 'VERCEL', 'APPWRITE_ENDPOINT',
                 'APPWRITE_PROJECT_ID', 'APPWRITE_API_KEY', 'APPWRITE_DATABASE_ID'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('MEETCOOL_DB', str(tmp_path / 'email-api.sqlite3'))
    monkeypatch.setattr(server, 'store', MeetingStore())
    monkeypatch.setattr(server, 'PUBLIC_APP_URL', 'https://meetcool.example')
    mailer = FakeMailer()
    monkeypatch.setattr(server, 'mailer', mailer)
    monkeypatch.setattr(httpx, 'request', lambda *a, **k: pytest.fail('Unexpected external HTTP request'))
    with TestClient(server.app) as client:
        yield client, mailer


def create(client, **extra):
    response = client.post('/api/meetings', json={
        'name': 'Café du projet', 'date': '2026-12-01T15:00',
        'venues': [{'id': 'cafe-one', 'name': 'Café commun', 'lat': 48.8566, 'lng': 2.3522}],
        **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()


def join(client, meeting_id, *, email=None, name='Camille'):
    response = client.post(f'/api/meetings/{meeting_id}/join', json={
        'name': name, 'email': email, 'lat': 47.123456, 'lng': 6.654321,
        'mode': 'walk', 'location_source': 'planned', 'location_label': 'Départ privé',
    })
    assert response.status_code == 200, response.text
    return response.json()


def confirmation(client, created):
    return client.patch(
        f'/api/meetings/{created["meeting"]["id"]}/admin',
        params={'token': created['admin_token']},
        json={'status': 'confirmed', 'chosen_venue': 'cafe-one'},
    )


def test_organizer_creation_email_contains_private_admin_link_only_for_organizer(email_api):
    client, mailer = email_api
    created = create(client, organizer_email=' organizer@example.com ')
    assert created['email_status'] == 'queued'
    assert len(mailer.calls) == 1
    email = mailer.calls[0]
    assert email['recipient'] == 'organizer@example.com'
    assert created['admin_token'] in email['content']
    assert 'https://meetcool.example' + created['admin_path'] in email['content']
    assert 'https://meetcool.example' + created['invite_path'] in email['content']
    assert email['event_id'] == created['meeting']['id'] + ':created'


def test_guest_receipt_and_public_endpoint_do_not_reveal_private_details(email_api):
    client, mailer = email_api
    created = create(client, organizer_email='organizer@example.com')
    meeting_id = created['meeting']['id']
    guest = join(client, meeting_id, email='guest@example.com')
    receipt = mailer.calls[-1]
    assert guest['email_status'] == 'queued'
    assert receipt['recipient'] == 'guest@example.com'
    assert f'https://meetcool.example/?join={meeting_id}' in receipt['content']
    assert created['admin_token'] not in receipt['content']
    assert 'admin=' not in receipt['content']
    assert 'organizer@example.com' not in receipt['content']
    public = client.get(f'/api/meetings/{meeting_id}')
    assert public.status_code == 200
    body = public.json()
    assert 'organizer_email' not in body['meeting']
    assert body['participants'] == [{
        'id': guest['participant_id'], 'name': 'Camille', 'mode': 'walk', 'status': 'accepted',
    }]
    for private_value in ('guest@example.com', 'organizer@example.com', created['admin_token'],
                          '47.123456', '6.654321', 'Départ privé'):
        assert private_value not in public.text


def test_confirmation_emails_have_maps_links_and_per_recipient_status_summary(email_api):
    client, mailer = email_api
    created = create(client, organizer_email='organizer@example.com')
    meeting_id = created['meeting']['id']
    join(client, meeting_id, email='guest@example.com')
    join(client, meeting_id, email='other@example.com', name='Alex')
    # Duplicate addresses receive one final notification.
    join(client, meeting_id, email='guest@example.com', name='Camille bis')
    mailer.calls.clear()
    mailer.statuses['other@example.com'] = 'failed'
    result = confirmation(client, created)
    assert result.status_code == 200, result.text
    assert result.json()['email_summary'] == {'queued': 2, 'failed': 1}
    assert {email['recipient'] for email in mailer.calls} == {
        'organizer@example.com', 'guest@example.com', 'other@example.com',
    }
    assert len(mailer.calls) == 3
    for email in mailer.calls:
        assert email['event_id'].endswith(':' + email['recipient'])
        assert ':confirmed:cafe-one:' in email['event_id']
        assert 'Café commun' in email['content']
        assert '2026-12-01T15:00' in email['content']
        assert created['admin_token'] not in email['content']
        links = [word for word in email['content'].split() if word.startswith('https://www.google.com/')]
        assert len(links) == 2
        map_link = next(link for link in links if '/search/' in link)
        directions = next(link for link in links if '/dir/' in link)
        assert parse_qs(urlparse(map_link).query) == {'api': ['1'], 'query': ['48.8566,2.3522']}
        assert parse_qs(urlparse(directions).query) == {'api': ['1'], 'destination': ['48.8566,2.3522']}
        assert '%2C' in map_link and '%2C' in directions
    # Persistence succeeds even when one delivery fails.
    assert client.get(f'/api/meetings/{meeting_id}').json()['meeting']['status'] == 'confirmed'


def test_repeated_confirmation_does_not_send_more_emails(email_api):
    client, mailer = email_api
    created = create(client, organizer_email='organizer@example.com')
    join(client, created['meeting']['id'], email='guest@example.com')
    assert confirmation(client, created).status_code == 200
    before = len(mailer.calls)
    repeated = confirmation(client, created)
    assert repeated.status_code == 200
    assert repeated.json()['email_summary'] == {}
    assert len(mailer.calls) == before


@pytest.mark.parametrize('address', ['not-an-email', 'two@@example.com', 'someone@', 'person @example.com'])
def test_malformed_organizer_and_guest_emails_are_rejected(email_api, address):
    client, mailer = email_api
    invalid_create = client.post('/api/meetings', json={'name': 'Café', 'organizer_email': address})
    assert invalid_create.status_code == 422
    assert mailer.calls == []
    created = create(client)
    before = len(mailer.calls)
    invalid_join = client.post(f'/api/meetings/{created["meeting"]["id"]}/join', json={
        'name': 'Camille', 'email': address, 'lat': 48, 'lng': 2,
    })
    assert invalid_join.status_code == 422
    assert len(mailer.calls) == before
    assert client.get(f'/api/meetings/{created["meeting"]["id"]}').json()['participants'] == []


def test_no_email_flow_still_creates_joins_and_confirms(email_api):
    client, mailer = email_api
    created = create(client)
    assert created['email_status'] == 'skipped'
    joined = join(client, created['meeting']['id'])
    assert joined['email_status'] == 'skipped'
    result = confirmation(client, created)
    assert result.status_code == 200
    assert result.json()['email_summary'] == {}
    assert all(email['recipient'] is None for email in mailer.calls)


def test_unconfigured_delivery_does_not_lose_a_created_meeting(email_api):
    client, mailer = email_api
    mailer.statuses['organizer@example.com'] = 'unconfigured'
    created = create(client, organizer_email='organizer@example.com')
    assert created['email_status'] == 'unconfigured'
    public = client.get(f'/api/meetings/{created["meeting"]["id"]}')
    assert public.status_code == 200
    assert public.json()['meeting']['name'] == 'Café du projet'
