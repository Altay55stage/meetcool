"""Optional server-only Appwrite email delivery and public map links.

Meeting persistence must finish before calling send(). Delivery is best effort:
failed or unconfigured messaging never invalidates an already saved meeting.
"""
from hashlib import sha256
import json
from math import isfinite
import os
import re
from threading import Lock
import time
from urllib.parse import urlencode, urlparse

import httpx


class Mailer:
    def __init__(self):
        self._endpoint = os.environ.get('APPWRITE_ENDPOINT', '').rstrip('/')
        self._project = os.environ.get('APPWRITE_PROJECT_ID', '')
        self._key = os.environ.get('APPWRITE_API_KEY', '')
        self._checked_at = None
        self._configured = False
        self._config_lock = Lock()
        try:
            parsed = urlparse(self._endpoint)
            local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
            self._credentials_ready = bool(
                self._endpoint and self._project and self._key and parsed.hostname
                and (parsed.scheme == 'https' or (local and parsed.scheme == 'http'))
            )
        except ValueError:
            self._credentials_ready = False

    def _request(self, method, path, *, params=None, payload=None):
        return httpx.request(
            method, self._endpoint + path,
            headers={
                'X-Appwrite-Project': self._project,
                'X-Appwrite-Key': self._key,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }, params=params, json=payload, timeout=8,
        )

    def config(self):
        """Verify an enabled email provider; cache the result for 30 seconds."""
        if not self._credentials_ready:
            return {'configured': False, 'provider': 'appwrite'}
        with self._config_lock:
            now = time.monotonic()
            if self._checked_at is not None and now - self._checked_at < 30:
                return {'configured': self._configured, 'provider': 'appwrite'}
            configured = False
            try:
                queries = [
                    {'method': 'equal', 'attribute': 'enabled', 'values': [True]},
                    {'method': 'equal', 'attribute': 'type', 'values': ['email']},
                    {'method': 'limit', 'values': [1]},
                ]
                params = [('queries[]', json.dumps(query, separators=(',', ':'))) for query in queries]
                response = self._request('GET', '/messaging/providers', params=params)
                response.raise_for_status()
                body = response.json()
                providers = body.get('providers', []) if isinstance(body, dict) else []
                configured = isinstance(providers, list) and any(
                    isinstance(provider, dict) and provider.get('enabled') is True
                    and provider.get('type') == 'email' for provider in providers
                )
            except (httpx.HTTPError, ValueError):
                # Do not expose credentials, provider configuration or upstream errors.
                configured = False
            self._configured = configured
            self._checked_at = now
            return {'configured': configured, 'provider': 'appwrite'}

    @staticmethod
    def _status(response, expected_id):
        try:
            response.raise_for_status()
            message = response.json()
            if not isinstance(message, dict) or message.get('$id', expected_id) != expected_id:
                return 'failed'
            status = message.get('status')
            if status == 'sent':
                return 'sent'
            if status in ('processing', 'scheduled'):
                return 'queued'
            return 'failed'
        except (httpx.HTTPError, ValueError):
            return 'failed'

    def send(self, event_id, recipient, subject, content):
        """Return skipped, unconfigured, queued, sent or failed; never resend a conflict.

        event_id must identify one recipient's notification, so retries reuse its
        deterministic ID while separate recipients/events receive different IDs.
        """
        if recipient is None or recipient == '':
            return 'skipped'
        if not all(isinstance(value, str) for value in (event_id, recipient, subject, content)):
            return 'failed'
        recipient = recipient.strip()
        if not recipient:
            return 'skipped'
        if not event_id or not subject or not content or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', recipient):
            return 'failed'
        if not self.config()['configured']:
            return 'unconfigured'
        try:
            message_id = 'mc' + sha256(event_id.encode('utf-8')).hexdigest()[:34]
        except UnicodeError:
            return 'failed'
        payload = {
            'messageId': message_id,
            'emails': [recipient],
            'subject': subject,
            'content': content,
            'html': False,
            'draft': False,
        }
        try:
            response = self._request('POST', '/messaging/messages/email', payload=payload)
            if response.status_code == 409:
                response = self._request('GET', f'/messaging/messages/{message_id}')
            return self._status(response, message_id)
        except (httpx.HTTPError, ValueError, UnicodeError):
            return 'failed'


def google_maps_urls(lat, lng):
    """Create key-free Google Maps links for one validated destination."""
    if isinstance(lat, bool) or isinstance(lng, bool):
        raise ValueError('Coordonnées géographiques invalides.')
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Coordonnées géographiques invalides.') from None
    if not isfinite(lat) or not isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise ValueError('Coordonnées géographiques invalides.')
    destination = f'{lat},{lng}'
    return {
        'map': 'https://www.google.com/maps/search/?' + urlencode({'api': '1', 'query': destination}),
        'directions': 'https://www.google.com/maps/dir/?' + urlencode({'api': '1', 'destination': destination}),
    }
