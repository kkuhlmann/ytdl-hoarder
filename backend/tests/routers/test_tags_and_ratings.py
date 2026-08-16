"""Router tests for tag and rating endpoints on /media-details."""

from fastapi.testclient import TestClient

from main import app


def _setup_two_users(client):
    """Register admin + second user. Return (admin_id, user2_id, client2)."""
    admin_resp = client.get('/auth/users')
    admin_user = next(u for u in admin_resp.json() if u['username'] == 'testadmin')
    admin_id = admin_user['id']

    reg_resp = client.post('/auth/register', json={'username': 'user2', 'password': 'pass123'})
    user2_id = reg_resp.json()['id']
    client.post(f'/auth/users/{user2_id}/approve')

    client2 = TestClient(app)
    client2.post('/auth/login', json={'username': 'user2', 'password': 'pass123'})

    return admin_id, user2_id, client2


# --- Tag endpoint tests ---


def test_get_tags_empty(authenticated_client):
    response = authenticated_client.get('/media-details/tags')
    assert response.status_code == 200
    assert response.json() == []


def test_set_and_get_tags(authenticated_client):
    # Set tags on media 1
    response = authenticated_client.put(
        '/media-details/1/tags', json={'tag_names': ['rock', 'classic']}
    )
    assert response.status_code == 200
    tags = response.json()
    assert len(tags) == 2
    names = [t['name'] for t in tags]
    assert 'classic' in names
    assert 'rock' in names

    # Tags appear in user's tag list
    response = authenticated_client.get('/media-details/tags')
    assert response.status_code == 200
    all_tags = response.json()
    assert len(all_tags) == 2
    rock = next(t for t in all_tags if t['name'] == 'rock')
    assert rock['usage_count'] == 1


def test_set_tags_replaces(authenticated_client):
    authenticated_client.put('/media-details/1/tags', json={'tag_names': ['a', 'b', 'c']})
    response = authenticated_client.put('/media-details/1/tags', json={'tag_names': ['b', 'd']})
    names = sorted(t['name'] for t in response.json())
    assert names == ['b', 'd']


def test_set_tags_empty_clears(authenticated_client):
    authenticated_client.put('/media-details/1/tags', json={'tag_names': ['x']})
    response = authenticated_client.put('/media-details/1/tags', json={'tag_names': []})
    assert response.json() == []


def test_set_tags_nonexistent_media(authenticated_client):
    response = authenticated_client.put('/media-details/9999/tags', json={'tag_names': ['x']})
    assert response.status_code == 404


def test_rename_tag(authenticated_client):
    authenticated_client.put('/media-details/1/tags', json={'tag_names': ['oldname']})
    tags = authenticated_client.get('/media-details/tags').json()
    tag_id = tags[0]['id']

    response = authenticated_client.patch(f'/media-details/tags/{tag_id}', json={'name': 'newname'})
    assert response.status_code == 200
    assert response.json()['name'] == 'newname'


def test_rename_tag_not_found(authenticated_client):
    response = authenticated_client.patch('/media-details/tags/9999', json={'name': 'x'})
    assert response.status_code == 404


def test_delete_tag(authenticated_client):
    authenticated_client.put('/media-details/1/tags', json={'tag_names': ['todelete']})
    tags = authenticated_client.get('/media-details/tags').json()
    tag_id = tags[0]['id']

    response = authenticated_client.delete(f'/media-details/tags/{tag_id}')
    assert response.status_code == 204

    # Tag is gone
    tags = authenticated_client.get('/media-details/tags').json()
    assert len(tags) == 0


def test_delete_tag_not_found(authenticated_client):
    response = authenticated_client.delete('/media-details/tags/9999')
    assert response.status_code == 404


def test_deleting_media_drops_its_tag_from_dropdown(authenticated_client):
    """Soft-deleting a media removes its tags so they no longer appear in /tags."""
    authenticated_client.put('/media-details/1/tags', json={'tag_names': ['ephemeral']})
    tags = authenticated_client.get('/media-details/tags').json()
    assert [t['name'] for t in tags] == ['ephemeral']

    resp = authenticated_client.delete('/media-details/1')
    assert resp.status_code == 204

    # Tag had no other live media, so it drops out of the dropdown.
    tags = authenticated_client.get('/media-details/tags').json()
    assert tags == []


def test_tags_per_user_isolation(authenticated_client):
    """User2 cannot see user1's tags."""
    _, _, client2 = _setup_two_users(authenticated_client)

    # Admin tags media 1
    authenticated_client.put('/media-details/1/tags', json={'tag_names': ['admin-tag']})

    # User2 sees no tags
    user2_tags = client2.get('/media-details/tags').json()
    assert len(user2_tags) == 0


def test_tags_in_media_list(authenticated_client):
    """Tags appear in the media list response."""
    authenticated_client.put('/media-details/1/tags', json={'tag_names': ['rock']})
    response = authenticated_client.get('/media-details')
    records = response.json()['records']
    media_1 = next(r for r in records if r['id'] == 1)
    assert len(media_1['tags']) == 1
    assert media_1['tags'][0]['name'] == 'rock'


def test_tags_in_single_media_detail(authenticated_client):
    """Tags appear in the single media detail response."""
    authenticated_client.put('/media-details/1/tags', json={'tag_names': ['jazz']})
    response = authenticated_client.get('/media-details/1')
    data = response.json()
    assert len(data['tags']) == 1
    assert data['tags'][0]['name'] == 'jazz'


# --- Rating endpoint tests ---


def test_set_rating(authenticated_client):
    response = authenticated_client.put('/media-details/1/rating', json={'rating': 4})
    assert response.status_code == 200
    assert response.json()['rating'] == 4


def test_update_rating(authenticated_client):
    authenticated_client.put('/media-details/1/rating', json={'rating': 3})
    response = authenticated_client.put('/media-details/1/rating', json={'rating': 5})
    assert response.json()['rating'] == 5


def test_set_rating_invalid(authenticated_client):
    response = authenticated_client.put('/media-details/1/rating', json={'rating': 0})
    assert response.status_code == 422

    response = authenticated_client.put('/media-details/1/rating', json={'rating': 6})
    assert response.status_code == 422


def test_set_rating_nonexistent_media(authenticated_client):
    response = authenticated_client.put('/media-details/9999/rating', json={'rating': 3})
    assert response.status_code == 404


def test_delete_rating(authenticated_client):
    authenticated_client.put('/media-details/1/rating', json={'rating': 4})
    response = authenticated_client.delete('/media-details/1/rating')
    assert response.status_code == 204


def test_rating_in_media_list(authenticated_client):
    """Rating appears in the media list response."""
    authenticated_client.put('/media-details/1/rating', json={'rating': 5})
    response = authenticated_client.get('/media-details')
    records = response.json()['records']
    media_1 = next(r for r in records if r['id'] == 1)
    assert media_1['rating'] == 5


def test_rating_null_when_unrated(authenticated_client):
    """Unrated media has null rating."""
    response = authenticated_client.get('/media-details')
    records = response.json()['records']
    for r in records:
        assert r['rating'] is None


def test_rating_in_single_media_detail(authenticated_client):
    """Rating appears in the single media detail response."""
    authenticated_client.put('/media-details/1/rating', json={'rating': 3})
    response = authenticated_client.get('/media-details/1')
    assert response.json()['rating'] == 3


def test_ratings_per_user_isolation(authenticated_client):
    """User2's rating is independent from user1's."""
    _, user2_id, client2 = _setup_two_users(authenticated_client)

    # Share media with user2 so they can access it
    authenticated_client.post('/media-details/1/share', json={'user_id': user2_id})

    authenticated_client.put('/media-details/1/rating', json={'rating': 5})

    # User2 sees no rating on the same media (ratings are per-user)
    response = client2.get('/media-details/1')
    assert response.status_code == 200
    assert response.json()['rating'] is None


# --- Filtering tests ---


def test_filter_by_tag_ids(authenticated_client):
    """tag_ids filter returns only media with matching tags."""
    authenticated_client.put('/media-details/1/tags', json={'tag_names': ['rock']})

    tags = authenticated_client.get('/media-details/tags').json()
    rock_id = next(t['id'] for t in tags if t['name'] == 'rock')

    response = authenticated_client.get(f'/media-details?tag_ids={rock_id}')
    records = response.json()['records']
    assert len(records) == 1
    assert records[0]['id'] == 1


def test_filter_by_min_rating(authenticated_client):
    """min_rating filter returns only media rated at or above the threshold."""
    authenticated_client.put('/media-details/1/rating', json={'rating': 5})
    authenticated_client.put('/media-details/2/rating', json={'rating': 2})

    response = authenticated_client.get('/media-details?min_rating=4')
    records = response.json()['records']
    assert len(records) == 1
    assert records[0]['id'] == 1


def test_sort_by_rating(authenticated_client):
    """sort_by=rating orders by rating descending, unrated last."""
    authenticated_client.put('/media-details/1/rating', json={'rating': 2})
    authenticated_client.put('/media-details/2/rating', json={'rating': 5})

    response = authenticated_client.get('/media-details?sort_by=rating&sort_direction=desc')
    records = response.json()['records']
    assert records[0]['id'] == 2  # rating 5
    assert records[1]['id'] == 1  # rating 2

    # Ascending
    response = authenticated_client.get('/media-details?sort_by=rating&sort_direction=asc')
    records = response.json()['records']
    assert records[0]['id'] == 1  # rating 2
    assert records[1]['id'] == 2  # rating 5
