"""Router tests for the media grouping endpoint and group leaf filters."""


def test_groups_by_channel(authenticated_client):
    resp = authenticated_client.get('/media-details/groups?group_by=channel')
    assert resp.status_code == 200
    data = resp.json()
    assert 'groups' in data and 'page_count' in data
    keys = {g['key'] for g in data['groups']}
    # Fixture media: 'Rick Astley' and 'MusRest'
    assert 'Rick Astley' in keys
    assert 'MusRest' in keys
    rick = next(g for g in data['groups'] if g['key'] == 'Rick Astley')
    assert rick['count'] == 1
    assert 'sample_media_ids' in rick
    assert 'total_duration' in rick


def test_groups_invalid_group_by_returns_400(authenticated_client):
    resp = authenticated_client.get('/media-details/groups?group_by=bogus')
    assert resp.status_code == 400


def test_groups_requires_auth(test_database):
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    resp = client.get('/media-details/groups?group_by=channel')
    assert resp.status_code == 401


def test_list_filter_by_channel(authenticated_client):
    resp = authenticated_client.get('/media-details?channel=Rick Astley')
    assert resp.status_code == 200
    records = resp.json()['records']
    assert len(records) == 1
    assert records[0]['channel'] == 'Rick Astley'
