import pytest


@pytest.fixture()
def auth_headers(client):
    resp = client.post("/auth/register", json={"email": "alert_user@example.com", "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_list_subscriptions_empty(client, auth_headers):
    resp = client.get("/alerts/subscriptions/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_subscribe(client, auth_headers):
    resp = client.post("/alerts/subscriptions/", json={"station_number": "14211720"}, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["station_number"] == "14211720"
    assert resp.json()["active"] is True


def test_subscribe_duplicate_returns_409(client, auth_headers):
    client.post("/alerts/subscriptions/", json={"station_number": "14211720"}, headers=auth_headers)
    resp = client.post("/alerts/subscriptions/", json={"station_number": "14211720"}, headers=auth_headers)
    assert resp.status_code == 409


def test_unsubscribe(client, auth_headers):
    client.post("/alerts/subscriptions/", json={"station_number": "14211720"}, headers=auth_headers)
    resp = client.delete("/alerts/subscriptions/14211720", headers=auth_headers)
    assert resp.status_code == 204
    assert client.get("/alerts/subscriptions/", headers=auth_headers).json() == []


def test_unsubscribe_nonexistent(client, auth_headers):
    resp = client.delete("/alerts/subscriptions/XXXXXXXX", headers=auth_headers)
    assert resp.status_code == 404


def test_alert_history_empty(client, auth_headers):
    resp = client.get("/alerts/history/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_alerts_require_auth(client):
    resp = client.get("/alerts/subscriptions/")
    assert resp.status_code in (401, 403)
