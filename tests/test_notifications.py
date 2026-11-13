"""Messaging verification uses mocked requests; no external emails are sent."""
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

import notifications
from notifications import Mailer, google_maps_urls


@pytest.fixture(autouse=True)
def appwrite_environment(monkeypatch):
    monkeypatch.setenv('APPWRITE_ENDPOINT', 'https://fra.cloud.appwrite.io/v1')
    monkeypatch.setenv('APPWRITE_PROJECT_ID', 'project')
    monkeypatch.setenv('APPWRITE_API_KEY', 'server-key-never-expose')


def response(method, url, data, status=200):
    return httpx.Response(status, json=data, request=httpx.Request(method, url))


def test_config_checks_provider_and_caches_for_thirty_seconds(monkeypatch):
    calls = []
    now = [100.0]
    monkeypatch.setattr(notifications.time, 'monotonic', lambda: now[0])

    def request(method, url, **kwargs):
        calls.append(url)
        assert method == 'GET'
        assert url.endswith('/messaging/providers')
        assert kwargs['headers']['X-Appwrite-Key'] == 'server-key-never-expose'
        assert kwargs['headers']['X-Appwrite-Project'] == 'project'
        queries = [json.loads(value) for _, value in kwargs['params']]
        assert {'method': 'equal', 'attribute': 'type', 'values': ['email']} in queries
        return response(method, url, {'providers': [{'enabled': True, 'type': 'email'}]})

    monkeypatch.setattr(httpx, 'request', request)
    mailer = Mailer()
    assert mailer.config() == {'configured': True, 'provider': 'appwrite'}
    now[0] = 129.9
    assert mailer.config()['configured']
    assert len(calls) == 1
    now[0] = 130
    assert mailer.config()['configured']
    assert len(calls) == 2


@pytest.mark.parametrize('providers', [[], [{'enabled': False, 'type': 'email'}], [{'enabled': True, 'type': 'sms'}]])
def test_missing_disabled_or_non_email_provider_is_unconfigured(monkeypatch, providers):
    calls = []
    def request(method, url, **kwargs):
        calls.append(method)
        return response(method, url, {'providers': providers})
    monkeypatch.setattr(httpx, 'request', request)
    mailer = Mailer()
    assert mailer.send('invite-one', 'camille@example.com', 'Invitation', 'Bonjour') == 'unconfigured'
    assert calls == ['GET']


def test_incomplete_credentials_never_contact_upstream(monkeypatch):
    monkeypatch.delenv('APPWRITE_API_KEY')
    monkeypatch.setattr(httpx, 'request', lambda *a, **k: pytest.fail('Unexpected network call'))
    mailer = Mailer()
    assert not mailer.config()['configured']
    assert mailer.send('invite-one', 'camille@example.com', 'Invitation', 'Bonjour') == 'unconfigured'


@pytest.mark.parametrize('upstream_status,expected', [('processing', 'queued'), ('scheduled', 'queued'), ('sent', 'sent'), ('failed', 'failed'), ('draft', 'failed'), (None, 'failed')])
def test_delivery_only_reports_sent_when_provider_confirms(monkeypatch, upstream_status, expected):
    def request(method, url, **kwargs):
        if method == 'GET':
            return response(method, url, {'providers': [{'enabled': True, 'type': 'email'}]})
        payload = kwargs['json']
        assert payload['emails'] == ['camille@example.com']
        assert payload['html'] is False and payload['draft'] is False
        assert len(payload['messageId']) <= 36
        assert payload['messageId'].isalnum()
        return response(method, url, {'$id': payload['messageId'], 'status': upstream_status}, 201)
    monkeypatch.setattr(httpx, 'request', request)
    assert Mailer().send('invite-one', 'camille@example.com', 'Invitation', 'Bonjour') == expected


def test_conflict_verifies_existing_message_without_retrying_post(monkeypatch):
    calls = []
    ids = []
    def request(method, url, **kwargs):
        calls.append((method, url))
        if url.endswith('/providers'):
            return response(method, url, {'providers': [{'enabled': True, 'type': 'email'}]})
        if method == 'POST':
            ids.append(kwargs['json']['messageId'])
            return response(method, url, {'message': 'already exists'}, 409)
        assert url.endswith('/messaging/messages/' + ids[-1])
        return response(method, url, {'$id': ids[-1], 'status': 'sent'})
    monkeypatch.setattr(httpx, 'request', request)
    mailer = Mailer()
    assert mailer.send('same-event', 'camille@example.com', 'Invitation', 'Bonjour') == 'sent'
    assert mailer.send('same-event', 'camille@example.com', 'Invitation', 'Bonjour') == 'sent'
    assert ids[0] == ids[1]
    assert [method for method, _ in calls] == ['GET', 'POST', 'GET', 'POST', 'GET']


@pytest.mark.parametrize('failed_stage', ['provider', 'send', 'conflict_lookup'])
def test_upstream_failures_are_safe_statuses_not_raw_errors(monkeypatch, caplog, failed_stage):
    def request(method, url, **kwargs):
        if url.endswith('/providers'):
            if failed_stage == 'provider':
                raise httpx.ConnectError('server-key-never-expose')
            return response(method, url, {'providers': [{'enabled': True, 'type': 'email'}]})
        if failed_stage == 'conflict_lookup' and method == 'POST':
            return response(method, url, {'message': 'exists'}, 409)
        return response(method, url, {'message': 'server-key-never-expose'}, 500)
    monkeypatch.setattr(httpx, 'request', request)
    status = Mailer().send('invite-one', 'camille@example.com', 'Invitation', 'Bonjour')
    assert status == ('unconfigured' if failed_stage == 'provider' else 'failed')
    assert 'server-key-never-expose' not in caplog.text


def test_missing_recipient_skips_without_provider_probe(monkeypatch):
    monkeypatch.setattr(httpx, 'request', lambda *a, **k: pytest.fail('Unexpected network call'))
    assert Mailer().send('event', None, 'Invitation', 'Bonjour') == 'skipped'
    assert Mailer().send('event', ' ', 'Invitation', 'Bonjour') == 'skipped'


def test_maps_links_encode_coordinates_and_api_version():
    links = google_maps_urls(48.8566, 2.3522)
    for kind, parameter in [('map', 'query'), ('directions', 'destination')]:
        assert '%2C' in links[kind]
        assert urlparse(links[kind]).netloc == 'www.google.com'
        assert parse_qs(urlparse(links[kind]).query) == {'api': ['1'], parameter: ['48.8566,2.3522']}


@pytest.mark.parametrize('lat,lng', [(91, 0), (0, -181), (float('nan'), 0), (0, float('inf')), ('bad', 0), (True, 0), (None, 0)])
def test_maps_reject_invalid_coordinates(lat, lng):
    with pytest.raises(ValueError, match='Coordonnées'):
        google_maps_urls(lat, lng)


def test_invalid_endpoint_is_unconfigured_without_throwing(monkeypatch):
    monkeypatch.setenv('APPWRITE_ENDPOINT', 'https://[')
    monkeypatch.setattr(httpx, 'request', lambda *a, **k: pytest.fail('Unexpected network call'))
    assert Mailer().config() == {'configured': False, 'provider': 'appwrite'}
