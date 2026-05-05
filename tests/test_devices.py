import pytest


@pytest.fixture()
def auth_headers(client):
    resp = client.post("/auth/register", json={"email": "device_user@example.com", "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_register_device(client, auth_headers):
    resp = client.post("/devices/register", json={"fcm_token": "fake-fcm-token-abc123", "platform": "android"}, headers=auth_headers)
    assert resp.status_code == 201


def test_register_device_ios(client, auth_headers):
    resp = client.post("/devices/register", json={"fcm_token": "fake-ios-token-xyz", "platform": "ios"}, headers=auth_headers)
    assert resp.status_code == 201


def test_register_device_upsert(client, auth_headers):
    client.post("/devices/register", json={"fcm_token": "shared-token", "platform": "android"}, headers=auth_headers)
    # Registering same token again should succeed (upsert)
    resp = client.post("/devices/register", json={"fcm_token": "shared-token", "platform": "android"}, headers=auth_headers)
    assert resp.status_code == 201


def test_register_device_invalid_platform(client, auth_headers):
    resp = client.post("/devices/register", json={"fcm_token": "token", "platform": "windows"}, headers=auth_headers)
    assert resp.status_code == 422


def test_devices_require_auth(client):
    resp = client.post("/devices/register", json={"fcm_token": "token", "platform": "android"})
    assert resp.status_code in (401, 403)
