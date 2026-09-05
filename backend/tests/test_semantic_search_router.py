"""The /semantic/search endpoint forwards the library filter it is given."""

import pytest
from fastapi.testclient import TestClient

import routers.media_details as media_details_router
from main import app
from utils import get_model


@pytest.fixture
def captured_kwargs(monkeypatch, authenticated_client):
    """Swap the search service for a recorder, so no ONNX model is loaded."""
    captured: dict = {}

    async def fake_search(model, search_query, standard_search=None, **kwargs):
        captured['search_query'] = search_query
        captured['standard_search'] = standard_search
        captured.update(kwargs)
        return []

    monkeypatch.setattr(media_details_router, 'get_hybrid_search_results', fake_search)
    # Keyed on the function the route closed over at import, not the router's attribute.
    app.dependency_overrides[get_model] = lambda: None
    yield captured, authenticated_client
    app.dependency_overrides.clear()


def test_every_filter_param_reaches_the_service(captured_kwargs):
    captured, client = captured_kwargs

    response = client.get(
        '/media-details/semantic/search',
        params={
            'semantic_search': 'lunar lander',
            'standard_search': 'NASA',
            'semantic_weight': 1.0,
            'tag_ids': '3,4',
            'min_rating': 4,
            'channel': 'NASA',
            'date_field': 'released',
            'date_year': 2024,
            'date_month': 3,
        },
    )

    assert response.status_code == 200
    assert captured['standard_search'] == 'NASA'
    assert captured['tag_ids'] == [3, 4]
    assert captured['min_rating'] == 4
    assert captured['channel'] == 'NASA'
    assert (captured['date_field'], captured['date_year'], captured['date_month']) == (
        'released',
        2024,
        3,
    )


def test_rating_user_id_is_the_caller_not_the_access_filter(captured_kwargs):
    """Tags and ratings are per-user, so they key on the caller even in admin view."""
    captured, client = captured_kwargs

    response = client.get(
        '/media-details/semantic/search',
        params={'semantic_search': 'lunar lander', 'admin_view': 'true'},
    )

    assert response.status_code == 200
    # admin_view drops the access filter but must not reassign whose tags these are.
    assert captured['user_id'] is None
    assert captured['rating_user_id'] is not None


def test_status_is_not_forwarded(captured_kwargs):
    """Transcript search spans every status; a status would also narrow the access tier."""
    captured, client = captured_kwargs

    client.get('/media-details/semantic/search', params={'semantic_search': 'lunar lander'})

    assert 'status' not in captured


def test_unparseable_tag_ids_filter_nothing_rather_than_422(captured_kwargs):
    captured, client = captured_kwargs

    response = client.get(
        '/media-details/semantic/search',
        params={'semantic_search': 'lunar lander', 'tag_ids': 'not-a-number'},
    )

    assert response.status_code == 200
    assert captured['tag_ids'] is None


def test_search_requires_authentication():
    client = TestClient(app)

    response = client.get('/media-details/semantic/search', params={'semantic_search': 'x'})

    assert response.status_code == 401
