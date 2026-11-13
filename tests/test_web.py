"""HTTP checks for the animated entry point and its Algorithm Lab destination."""
from fastapi.testclient import TestClient
from server import app


def test_motion_script_is_served():
    with TestClient(app) as client:
        response = client.get('/motion.js')
        assert response.status_code == 200
        assert 'javascript' in response.headers['content-type']


def test_algorithm_lab_serializes_unreachable_distances():
    with TestClient(app) as client:
        response = client.get('/api/algorithms/demo')
        assert response.status_code == 200
        data = response.json()
        assert data['floyd_warshall']['D']['A'] is None
        assert data['floyd_warshall']['A']['D'] == 9
        assert data['dijkstra']['path_A_D'] == ['A', 'B', 'C', 'D']


def test_language_assets_and_selectors_are_served():
    with TestClient(app) as client:
        html = client.get('/').text
        assert html.count('data-language aria-label=') == 2
        for path in ('/i18n.js', '/translations.js'):
            response = client.get(path)
            assert response.status_code == 200
            assert 'javascript' in response.headers['content-type']
        assert 'window.MEETCOOL_EN' in client.get('/translations.js').text
