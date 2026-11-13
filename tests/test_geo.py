"""Geospatial API tests use mocked providers and never hit public services."""
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import geo

app = FastAPI()
app.include_router(geo.router)
client = TestClient(app)
PERSON = {'id': 'a', 'name': 'Camille', 'lat': 48.85, 'lng': 2.34, 'mode': 'car'}
DESTINATION = {'lat': 48.87, 'lng': 2.35}


@pytest.fixture(autouse=True)
def clear_caches(monkeypatch):
    geo._cache.clear()
    monkeypatch.setattr(geo, '_last_geocode', 0.0)


def test_address_search_normalizes_photon_and_caches(monkeypatch):
    calls = []
    def provider(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {'features': [{'properties': {'name': 'Paris', 'city': 'Paris', 'country': 'France'},
                              'geometry': {'coordinates': [2.35, 48.85]}}]}
    monkeypatch.setattr(geo, '_fetch_json', provider)
    first = client.get('/api/geocode', params={'q': 'Paris'})
    second = client.get('/api/geocode', params={'q': ' paris '})
    assert first.status_code == 200
    assert first.json()['results'] == [{'name': 'Paris, France', 'lat': 48.85, 'lng': 2.35}]
    assert second.json() == first.json()
    assert len(calls) == 1
    assert calls[0][2]['params']['limit'] == 5


@pytest.mark.parametrize('query', ['ab', '   ', 'a' * 181])
def test_search_input_limits(query):
    assert client.get('/api/geocode', params={'q': query}).status_code == 422


def test_provider_failure_has_explicit_error(monkeypatch):
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(geo, '_fetch_json', unavailable)
    assert client.get('/api/geocode', params={'q': 'Paris'}).status_code == 502
    assert client.get('/api/map-features', params={'lat': 48.85, 'lng': 2.34}).status_code == 502


def test_nearby_features_filter_and_never_invent_signal_state(monkeypatch):
    def provider(method, url, **kwargs):
        assert '[timeout:6]' in kwargs['data']['data']
        assert 'out center 120' in kwargs['data']['data']
        return {'elements': [
            {'type': 'node', 'id': 1, 'lat': 48.85, 'lon': 2.34, 'tags': {'highway': 'traffic_signals'}},
            {'type': 'way', 'id': 2, 'center': {'lat': 48.86, 'lon': 2.35}, 'tags': {'amenity': 'cafe', 'name': 'Café du coin'}},
            {'type': 'node', 'id': 3, 'lat': 150, 'lon': 2, 'tags': {'amenity': 'cafe'}},
        ]}
    monkeypatch.setattr(geo, '_fetch_json', provider)
    data = client.get('/api/map-features', params={'lat': 48.85, 'lng': 2.34}).json()
    assert [f['kind'] for f in data['features']] == ['traffic_signal', 'cafe']
    assert data['live'] is False
    assert 'durée' in data['note']
    assert not any('duration' in f or 'countdown' in f for f in data['features'])


@pytest.mark.parametrize('params', [
    {'lat': 91, 'lng': 2}, {'lat': 48, 'lng': 181},
    {'lat': 48, 'lng': 2, 'radius': 2001}, {'lat': 'nan', 'lng': 2},
])
def test_nearby_bounds(params):
    assert client.get('/api/map-features', params=params).status_code == 422


def test_car_geometry_and_walking_estimate_are_distinguished(monkeypatch):
    async def provider(client, person, destination):
        assert person.mode == 'car'
        return {'participant_id': person.id, 'name': person.name, 'mode': person.mode,
                'geometry': {'type': 'LineString', 'coordinates': [[2.34, 48.85], [2.345, 48.86], [2.35, 48.87]]},
                'minutes': 8.5, 'distance_km': 2.1, 'estimated': False}
    monkeypatch.setattr(geo, '_road_route', provider)
    response = client.post('/api/routes', json={'participants': [PERSON, {**PERSON, 'id': 'b', 'mode': 'walk'}], 'destination': DESTINATION})
    assert response.status_code == 200
    data = response.json()
    assert data['live_traffic'] is False
    assert data['routes'][0]['minutes'] == 8.5
    assert data['routes'][0]['estimated'] is False
    assert data['routes'][1]['estimated'] is True
    assert len(data['routes'][1]['geometry']['coordinates']) == 2


def test_car_routing_failure_retains_explicit_estimate(monkeypatch):
    async def unavailable(*args):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(geo, '_road_route', unavailable)
    response = client.post('/api/routes', json={'participants': [PERSON], 'destination': DESTINATION})
    route = response.json()['routes'][0]
    assert response.status_code == 200
    assert route['estimated'] is True
    assert route['minutes'] > 0
    assert 'indisponible' in route['reason']


@pytest.mark.parametrize('payload', [
    {'participants': [], 'destination': DESTINATION},
    {'participants': [{**PERSON, 'lat': 91}], 'destination': DESTINATION},
    {'participants': [{**PERSON, 'mode': 'plane'}], 'destination': DESTINATION},
])
def test_routes_payload_bounds(payload):
    assert client.post('/api/routes', json=payload).status_code == 422


def test_road_matrix_uses_minutes_and_explicit_sources(monkeypatch):
    calls = []
    def provider(method, url, **kwargs):
        calls.append(kwargs['params'])
        return {'code': 'Ok', 'durations': [[120, 240], [180, 300]]}
    monkeypatch.setattr(geo, '_fetch_json', provider)
    people = [PERSON, {**PERSON, 'id': 'b', 'lat': 48.86}]
    venues = [DESTINATION, {**DESTINATION, 'lat': 48.88}]
    assert geo.road_matrix(people, venues) == [[2.0, 4.0], [3.0, 5.0]]
    assert geo.road_matrix(people, venues) == [[2.0, 4.0], [3.0, 5.0]]
    assert calls == [{'sources': '0;1', 'destinations': '2;3', 'annotations': 'duration'}]


def test_matrix_does_not_treat_unreachable_as_zero(monkeypatch):
    monkeypatch.setattr(geo, '_fetch_json', lambda *args, **kwargs: {'code': 'Ok', 'durations': [[None]]})
    assert geo.road_matrix([PERSON], [DESTINATION]) is None
    assert geo.road_matrix([{**PERSON, 'mode': 'walk'}], [DESTINATION]) is None
    assert geo.road_matrix([{**PERSON, 'lng': float('inf')}], [DESTINATION]) is None


def test_osrm_response_is_decoded_without_losing_road_shape():
    import asyncio
    async def run():
        async def handler(request):
            assert request.url.params['geometries'] == 'geojson'
            assert '/route/v1/driving/2.34,48.85;2.35,48.87' in str(request.url)
            return httpx.Response(200, json={'code': 'Ok', 'routes': [{
                'duration': 510, 'distance': 2100,
                'geometry': {'type': 'LineString', 'coordinates': [[2.34, 48.85], [2.345, 48.86], [2.35, 48.87]]},
            }]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
            return await geo._road_route(upstream, geo.Participant(**PERSON), geo.Point(**DESTINATION))
    route = asyncio.run(run())
    assert route['minutes'] == 8.5
    assert route['distance_km'] == 2.1
    assert len(route['geometry']['coordinates']) == 3
    assert route['estimated'] is False


def test_large_group_routes_include_every_person(monkeypatch):
    async def unavailable(*args):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(geo, '_road_route', unavailable)
    people = [{**PERSON, 'id': f'guest-{i}'} for i in range(65)]
    response = client.post('/api/routes', json={'participants': people, 'destination': DESTINATION})
    assert response.status_code == 200
    assert [route['participant_id'] for route in response.json()['routes']] == [p['id'] for p in people]
    assert all(route['estimated'] for route in response.json()['routes'])
