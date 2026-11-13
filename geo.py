"""Bounded OpenStreetMap-backed search, routing and nearby map information.

Public endpoints are best-effort demo services, configurable for a dedicated host.
No traffic, signal phases or signal countdowns are inferred from map features.
"""
import asyncio
from collections import OrderedDict
from copy import deepcopy
from math import isfinite
import os
import threading
import time
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from engine import DETOUR, approx_minutes, haversine

router = APIRouter()
GEOCODER_URL = os.environ.get('GEOCODER_URL', 'https://photon.komoot.io/api/')
OSRM_URL = os.environ.get('OSRM_URL', 'https://router.project-osrm.org').rstrip('/')
OVERPASS_URL = os.environ.get('OVERPASS_URL', 'https://overpass-api.de/api/interpreter')
USER_AGENT = 'meetcool/1.0 (meeting-point planner; OpenStreetMap data)'
HEADERS = {'User-Agent': USER_AGENT, 'Accept': 'application/json'}
_cache = OrderedDict()
_cache_lock = threading.Lock()
_geocode_lock = threading.Lock()
_last_geocode = 0.0
CACHE_LIMIT = 256


class Point(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class Participant(Point):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    mode: Literal['car', 'walk', 'bike', 'transit'] = 'car'


class RouteRequest(BaseModel):
    participants: list[Participant] = Field(min_length=1)
    destination: Point


def _cached(key):
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires <= time.monotonic():
            del _cache[key]
            return None
        _cache.move_to_end(key)
        return deepcopy(value)


def _store(key, value, ttl=600):
    with _cache_lock:
        _cache[key] = (time.monotonic() + ttl, deepcopy(value))
        _cache.move_to_end(key)
        while len(_cache) > CACHE_LIMIT:
            _cache.popitem(last=False)
    return value


def _fetch_json(method, url, **kwargs):
    with httpx.Client(timeout=httpx.Timeout(7.0, connect=3.0), headers=HEADERS) as client:
        response = client.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json()


def _valid_coordinate(lat, lng):
    return (isinstance(lat, (int, float)) and isinstance(lng, (int, float))
            and isfinite(lat) and isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180)


@router.get('/api/geocode')
def geocode(q: str = Query(min_length=3, max_length=180)):
    """Explicit searches only; no automatic per-keystroke requests."""
    global _last_geocode
    query = q.strip()
    if len(query) < 3:
        raise HTTPException(422, 'Saisis au moins trois caractères.')
    key = ('geocode', GEOCODER_URL, query.casefold())
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        # Keep explicit address searches modest on the shared Photon demo service.
        with _geocode_lock:
            cached = _cached(key)
            if cached is not None:
                return cached
            wait = 1.0 - (time.monotonic() - _last_geocode)
            if wait > 0:
                time.sleep(wait)
            _last_geocode = time.monotonic()
            payload = _fetch_json('GET', GEOCODER_URL, params={'q': query, 'limit': 5})
        results = []
        for feature in payload.get('features', []):
            coordinates = feature.get('geometry', {}).get('coordinates', [])
            props = feature.get('properties', {})
            if len(coordinates) < 2 or not _valid_coordinate(coordinates[1], coordinates[0]):
                continue
            names = [props.get(k) for k in ('name', 'street', 'city', 'state', 'country')]
            name = ', '.join(dict.fromkeys(str(n) for n in names if n))
            results.append({'name': name or query, 'lat': coordinates[1], 'lng': coordinates[0]})
        return _store(key, {'results': results, 'source': 'Photon · OpenStreetMap'}, ttl=3600)
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise HTTPException(502, 'La recherche d’adresse est indisponible. Réessaie ou choisis un point sur la carte.')


def _estimated_route(person, destination, reason):
    start = person.model_dump()
    end = destination.model_dump()
    return {
        'participant_id': person.id, 'name': person.name, 'mode': person.mode,
        'geometry': {'type': 'LineString', 'coordinates': [[person.lng, person.lat], [destination.lng, destination.lat]]},
        'minutes': approx_minutes(start, end, person.mode),
        'distance_km': round(haversine(start, end) * DETOUR[person.mode], 2),
        'estimated': True, 'reason': reason,
    }


async def _road_route(client, person, destination):
    coordinates = f'{person.lng},{person.lat};{destination.lng},{destination.lat}'
    response = await client.get(f'{OSRM_URL}/route/v1/driving/{coordinates}', params={
        'overview': 'full', 'geometries': 'geojson', 'steps': 'false', 'alternatives': 'false',
    })
    response.raise_for_status()
    payload = response.json()
    if payload.get('code') != 'Ok' or not payload.get('routes'):
        raise ValueError('No road route')
    route = payload['routes'][0]
    geometry = route['geometry']
    coordinates = geometry.get('coordinates', [])
    duration, distance = float(route['duration']), float(route['distance'])
    if (geometry.get('type') != 'LineString' or len(coordinates) < 2
            or not isfinite(duration) or duration < 0 or not isfinite(distance) or distance < 0
            or any(len(point) < 2 or not _valid_coordinate(point[1], point[0]) for point in coordinates)):
        raise ValueError('Invalid road route')
    return {
        'participant_id': person.id, 'name': person.name, 'mode': person.mode,
        'geometry': geometry, 'minutes': round(duration / 60, 1),
        'distance_km': round(distance / 1000, 2), 'estimated': False,
    }


@router.post('/api/routes')
async def routes(data: RouteRequest):
    key = ('routes', OSRM_URL, data.model_dump_json())
    cached = _cached(key)
    if cached is not None:
        return cached
    results = [_estimated_route(p, data.destination,
               'Modèle géométrique : itinéraire routier indisponible.' if p.mode == 'car'
               else 'Modèle géométrique : routage de ce mode non connecté.') for p in data.participants]
    pending = iter(enumerate(data.participants))
    async with httpx.AsyncClient(timeout=httpx.Timeout(4.0, connect=2.0), headers=HEADERS) as client:
        async def calculate():
            # Four workers bound provider traffic even when the group is large.
            for index, person in pending:
                if person.mode != 'car':
                    continue
                try:
                    results[index] = await _road_route(client, person, data.destination)
                except (httpx.HTTPError, ValueError, TypeError, KeyError):
                    pass  # Keep the explicit geometric fallback for this participant.
        try:
            await asyncio.wait_for(asyncio.gather(*(calculate() for _ in range(4))), timeout=10)
        except asyncio.TimeoutError:
            pass  # Completed routes remain, pending routes retain their labelled fallback.
    response = {'routes': results, 'provider': 'OSRM · OpenStreetMap', 'live_traffic': False,
                'note': 'Durées routières hors trafic en direct. Segments pointillés : estimations géométriques.'}
    return _store(key, response, ttl=300)


@router.get('/api/map-features')
def map_features(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180),
                 radius: int = Query(default=1200, ge=100, le=2000)):
    if not _valid_coordinate(lat, lng):
        raise HTTPException(422, 'Coordonnées invalides.')
    key = ('features', OVERPASS_URL, round(lat, 4), round(lng, 4), radius)
    cached = _cached(key)
    if cached is not None:
        return cached
    query = (f'[out:json][timeout:6];('
             f'node["highway"="traffic_signals"](around:{radius},{lat},{lng});'
             f'nwr["amenity"~"^(cafe|restaurant|library|community_centre)$"](around:{radius},{lat},{lng});'
             ');out center 120;')
    try:
        payload = _fetch_json('POST', OVERPASS_URL, data={'data': query})
        features = []
        for item in payload.get('elements', []):
            center = item.get('center') or item
            plat, plng = center.get('lat'), center.get('lon')
            if not _valid_coordinate(plat, plng):
                continue
            tags = item.get('tags', {})
            signal = tags.get('highway') == 'traffic_signals'
            kind = 'traffic_signal' if signal else tags.get('amenity')
            if kind not in ('traffic_signal', 'cafe', 'restaurant', 'library', 'community_centre'):
                continue
            features.append({'id': f"{item.get('type', 'node')}/{item['id']}", 'kind': kind,
                             'name': tags.get('name') or ('Feu cartographié' if signal else {
                                 'cafe': 'Café', 'restaurant': 'Restaurant', 'library': 'Bibliothèque',
                                 'community_centre': 'Espace collectif',
                             }[kind]), 'lat': plat, 'lng': plng})
        return _store(key, {'features': features, 'source': 'OpenStreetMap', 'live': False,
                           'note': 'Données cartographiques : présence des feux, sans état, durée ni compte à rebours en direct.'})
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError):
        raise HTTPException(502, 'Les données de proximité sont temporairement indisponibles.')


def road_matrix(participants, venues):
    """Return OSRM car travel minutes, or None when unavailable/mixed/unreachable.

    The existing optimizer can use this as travel_matrix; never pass partial/null
    matrices to it, since an unreachable road must not become a zero-minute trip.
    """
    if not (1 <= len(participants) <= 12 and 1 <= len(venues) <= 20):
        return None
    if any(p.get('mode', 'car') != 'car' for p in participants):
        return None
    points = participants + venues
    if any(not _valid_coordinate(p.get('lat'), p.get('lng')) for p in points):
        return None
    coordinates = ';'.join(f"{p['lng']},{p['lat']}" for p in points)
    sources = ';'.join(str(i) for i in range(len(participants)))
    destinations = ';'.join(str(i) for i in range(len(participants), len(points)))
    key = ('matrix', OSRM_URL, coordinates, sources, destinations)
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        payload = _fetch_json('GET', f'{OSRM_URL}/table/v1/driving/{coordinates}', params={
            'sources': sources, 'destinations': destinations, 'annotations': 'duration',
        })
        values = payload.get('durations')
        if payload.get('code') != 'Ok' or not isinstance(values, list) or len(values) != len(participants):
            return None
        if any(not isinstance(row, list) or len(row) != len(venues) for row in values):
            return None
        if any(not isinstance(value, (int, float)) or not isfinite(value) or value < 0 for row in values for value in row):
            return None
        return _store(key, [[round(value / 60, 1) for value in row] for row in values], ttl=300)
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return None
