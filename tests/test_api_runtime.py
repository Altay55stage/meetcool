"""Application boundaries: persistence, privacy and routing provenance."""
import pytest
from fastapi.testclient import TestClient
import server
from storage import MeetingStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    for key in ('APPWRITE_ENDPOINT', 'APPWRITE_PROJECT_ID', 'APPWRITE_API_KEY', 'APPWRITE_DATABASE_ID'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv('VERCEL', raising=False)
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_KEY', raising=False)
    monkeypatch.setenv('MEETCOOL_DB', str(tmp_path / 'meetings.db'))
    monkeypatch.setattr(server, 'store', MeetingStore())
    monkeypatch.setattr(server, 'road_matrix', lambda participants, venues: None)
    with TestClient(server.app) as api:
        yield api


def test_meeting_invite_privacy_and_confirmation(client):
    venue = {'id':'test','name':'Paris','lat':48.85,'lng':2.35}
    created=client.post('/api/meetings',json={'name':'Projet mondial','venues':[venue],'objective':'fair'}).json()
    identifier=created['meeting']['id']; token=created['admin_token']
    assert client.post(f'/api/meetings/{identifier}/join',json={'name':'Camille','lat':48.8,'lng':2.3}).status_code==200
    public=client.get(f'/api/meetings/{identifier}').json()
    assert 'lat' not in public['participants'][0]
    assert 'admin_token' not in public
    assert client.get(f'/api/meetings/{identifier}/admin',params={'token':'wrong'}).status_code==403
    assert client.get(f'/api/meetings/{identifier}/admin',params={'token':token}).json()['participants'][0]['lat']==48.8
    confirmed=client.patch(f'/api/meetings/{identifier}/admin',params={'token':token},json={'status':'confirmed','chosen_venue':'test'}).json()
    assert confirmed['meeting']['status']=='confirmed'
    assert confirmed['meeting']['objective']=='fair'


def test_hosted_storage_unconfigured_never_claims_persistence(client, monkeypatch):
    monkeypatch.setenv('VERCEL','1')
    monkeypatch.setattr(server, 'store', MeetingStore())
    config=client.get('/api/config').json()
    assert config['shared'] is False
    assert config['persistent'] is False
    assert client.post('/api/meetings',json={'name':'Impossible sans DB'}).status_code==503


def test_road_matrix_provenance_and_invalid_coordinates(client, monkeypatch):
    data=client.get('/api/demo').json()
    monkeypatch.setattr(server,'road_matrix',lambda p,v:[[10]*len(v) for _ in p])
    response=client.post('/api/optimize',json=data)
    assert response.status_code==200
    assert response.json()['routing']=='osrm'
    data['participants'][0]['lat']=200
    assert client.post('/api/optimize',json=data).status_code==422


def test_large_group_can_join_and_optimize(client):
    venue = {'id': 'paris', 'name': 'Paris', 'lat': 48.85, 'lng': 2.35}
    created = client.post('/api/meetings', json={'name': 'Grande rencontre', 'venues': [venue]}).json()
    meeting_id = created['meeting']['id']
    for i in range(65):
        response = client.post(f'/api/meetings/{meeting_id}/join', json={'name': f'Invité {i}', 'lat': 48.8, 'lng': 2.3})
        assert response.status_code == 200
    public = client.get(f'/api/meetings/{meeting_id}').json()
    assert len(public['participants']) == 65
    people = [{**p, 'lat': 48.8, 'lng': 2.3} for p in public['participants']]
    result = client.post('/api/optimize', json={'participants': people, 'venues': [venue]})
    assert result.status_code == 200
    assert len(result.json()['matrix']) == 65


def test_invitation_collects_planned_departures_before_calculating(client):
    created = client.post('/api/meetings', json={'name': 'Vendredi ensemble', 'date': '2026-11-20T18:00', 'venues': []}).json()
    meeting_id = created['meeting']['id']
    token = created['admin_token']
    assert created['meeting']['venues'] == []
    assert client.get(f'/api/meetings/{meeting_id}/analysis', params={'token': token}).json()['ranking'] == []
    for name, lat, source in [('Sam', 45.76, 'planned'), ('Alex', 45.78, 'current')]:
        response = client.post(f'/api/meetings/{meeting_id}/join', json={
            'name': name, 'lat': lat, 'lng': 4.83, 'location_source': source,
            'location_label': 'Lyon au moment du rendez-vous'})
        assert response.status_code == 200
    admin = client.get(f'/api/meetings/{meeting_id}/admin', params={'token': token}).json()
    assert [p['status'] for p in admin['participants']] == ['accepted', 'accepted']
    assert admin['participants'][0]['location_source'] == 'planned'
    assert admin['participants'][1]['location_source'] == 'current'
    result = client.get(f'/api/meetings/{meeting_id}/analysis', params={'token': token}).json()
    assert len(result['matrix']) == 2
    assert all(45.7 < venue['lat'] < 45.9 for venue in result['venues'])
    assert {p['name'] for p in result['participants']} == {'Sam', 'Alex'}
    assert all('lat' not in p for p in client.get(f'/api/meetings/{meeting_id}').json()['participants'])
    client.patch(f'/api/meetings/{meeting_id}/admin', params={'token': token}, json={'status': 'cancelled'})
    assert client.post(f'/api/meetings/{meeting_id}/join', json={'name': 'Tard', 'lat': 45.76, 'lng': 4.83}).status_code == 409
