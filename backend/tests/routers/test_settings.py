"""Settings endpoints, focused on the lane-concurrency and subscription-cadence fields
and their live apply, plus the yt-dlp throttling fields whose off-switch is 0 rather
than absence."""

from unittest.mock import patch

import pytest

from orchestrator.scheduler import subscription_schedule

LANE_FIELDS = (
    'default_lane_concurrency',
    'downloads_lane_concurrency',
    'subscriptions_lane_concurrency',
    'ml_lane_concurrency',
)


def test_get_settings_exposes_lane_concurrency_defaults(authenticated_client):
    data = authenticated_client.get('/settings').json()
    assert data['default_lane_concurrency'] == 2
    assert data['downloads_lane_concurrency'] == 1
    assert data['subscriptions_lane_concurrency'] == 1
    assert data['ml_lane_concurrency'] == 1


def test_update_lane_concurrency_persists_and_applies(authenticated_client):
    with patch('routers.settings.orch.set_lane_concurrency') as apply_mock:
        response = authenticated_client.put(
            '/settings', json={'downloads_lane_concurrency': 3, 'ml_lane_concurrency': 2}
        )

    assert response.status_code == 200
    assert response.json()['downloads_lane_concurrency'] == 3
    assert response.json()['ml_lane_concurrency'] == 2
    apply_mock.assert_called_once()
    assert apply_mock.call_args[0][0]['downloads'] == 3
    assert apply_mock.call_args[0][0]['ml'] == 2

    assert authenticated_client.get('/settings').json()['downloads_lane_concurrency'] == 3


@pytest.mark.parametrize('field', LANE_FIELDS)
@pytest.mark.parametrize('value', [0, 9])
def test_lane_concurrency_out_of_range_is_rejected(authenticated_client, field, value):
    response = authenticated_client.put('/settings', json={field: value})
    assert response.status_code == 400
    assert 'between 1 and 8' in response.json()['detail']


def test_reset_lane_concurrency_restores_default_and_applies(authenticated_client):
    authenticated_client.put('/settings', json={'downloads_lane_concurrency': 4})

    with patch('routers.settings.orch.set_lane_concurrency') as apply_mock:
        response = authenticated_client.put('/settings/reset/downloads_lane_concurrency')

    assert response.status_code == 200
    assert response.json()['downloads_lane_concurrency'] == 1
    assert apply_mock.call_args[0][0]['downloads'] == 1


def test_reset_all_restores_every_lane_and_applies(authenticated_client):
    authenticated_client.put(
        '/settings', json={'default_lane_concurrency': 6, 'ml_lane_concurrency': 4}
    )

    with patch('routers.settings.orch.set_lane_concurrency') as apply_mock:
        response = authenticated_client.put('/settings/reset')

    data = response.json()
    assert (data['default_lane_concurrency'], data['ml_lane_concurrency']) == (2, 1)
    assert apply_mock.call_args[0][0] == {
        'default': 2,
        'downloads': 1,
        'subscriptions': 1,
        'ml': 1,
    }


def test_get_settings_exposes_the_subscription_cadence_default(authenticated_client):
    assert authenticated_client.get('/settings').json()['subscription_check_minutes'] == 10


def test_update_subscription_cadence_persists_and_retargets_the_cron(authenticated_client):
    response = authenticated_client.put('/settings', json={'subscription_check_minutes': 45})

    assert response.status_code == 200
    assert response.json()['subscription_check_minutes'] == 45
    assert subscription_schedule.minutes == 45
    assert authenticated_client.get('/settings').json()['subscription_check_minutes'] == 45


@pytest.mark.parametrize('value', [0, 1441])
def test_subscription_cadence_out_of_range_is_rejected(authenticated_client, value):
    response = authenticated_client.put('/settings', json={'subscription_check_minutes': value})
    assert response.status_code == 400
    assert 'between 1 and 1440' in response.json()['detail']


def test_reset_subscription_cadence_restores_default_and_retargets(authenticated_client):
    authenticated_client.put('/settings', json={'subscription_check_minutes': 45})

    response = authenticated_client.put('/settings/reset/subscription_check_minutes')

    assert response.status_code == 200
    assert response.json()['subscription_check_minutes'] == 10
    assert subscription_schedule.minutes == 10


def test_get_settings_exposes_throttling_defaults(authenticated_client):
    data = authenticated_client.get('/settings').json()
    assert data['download_rate_limit_kbps'] == 0
    assert data['request_sleep_seconds'] == 0


def test_update_throttling_persists(authenticated_client):
    response = authenticated_client.put(
        '/settings', json={'download_rate_limit_kbps': 512, 'request_sleep_seconds': 2}
    )

    assert response.status_code == 200
    assert response.json()['download_rate_limit_kbps'] == 512
    assert response.json()['request_sleep_seconds'] == 2

    data = authenticated_client.get('/settings').json()
    assert (data['download_rate_limit_kbps'], data['request_sleep_seconds']) == (512, 2)


def test_zero_is_an_accepted_throttling_value(authenticated_client):
    """0 is the off-switch, so it must survive the router's `is not None` partial filter
    rather than being dropped as a falsy no-op."""
    authenticated_client.put('/settings', json={'download_rate_limit_kbps': 512})

    response = authenticated_client.put(
        '/settings', json={'download_rate_limit_kbps': 0, 'request_sleep_seconds': 0}
    )

    assert response.status_code == 200
    assert response.json()['download_rate_limit_kbps'] == 0
    assert authenticated_client.get('/settings').json()['download_rate_limit_kbps'] == 0


def test_negative_rate_limit_is_rejected(authenticated_client):
    response = authenticated_client.put('/settings', json={'download_rate_limit_kbps': -1})
    assert response.status_code == 400
    assert 'non-negative' in response.json()['detail']


@pytest.mark.parametrize('value', [-1, 61])
def test_request_sleep_out_of_range_is_rejected(authenticated_client, value):
    response = authenticated_client.put('/settings', json={'request_sleep_seconds': value})
    assert response.status_code == 400
    assert 'between 0 and 60' in response.json()['detail']


def test_reset_throttling_restores_defaults(authenticated_client):
    authenticated_client.put(
        '/settings', json={'download_rate_limit_kbps': 512, 'request_sleep_seconds': 2}
    )

    assert (
        authenticated_client.put('/settings/reset/download_rate_limit_kbps').json()[
            'download_rate_limit_kbps'
        ]
        == 0
    )

    data = authenticated_client.put('/settings/reset').json()
    assert (data['download_rate_limit_kbps'], data['request_sleep_seconds']) == (0, 0)
