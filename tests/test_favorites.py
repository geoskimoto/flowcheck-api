import pytest


@pytest.fixture()
def auth_headers(client):
    resp = client.post("/auth/register", json={"email": "fav_user@example.com", "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_list_favorites_empty(client, auth_headers):
    resp = client.get("/favorites/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_add_favorite(client, auth_headers):
    resp = client.post("/favorites/", json={"station_number": "14211720"}, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["station_number"] == "14211720"


def test_list_favorites_after_add(client, auth_headers):
    client.post("/favorites/", json={"station_number": "14211720"}, headers=auth_headers)
    resp = client.get("/favorites/", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["station_number"] == "14211720"


def test_add_duplicate_favorite_returns_409(client, auth_headers):
    client.post("/favorites/", json={"station_number": "14211720"}, headers=auth_headers)
    resp = client.post("/favorites/", json={"station_number": "14211720"}, headers=auth_headers)
    assert resp.status_code == 409


def test_delete_favorite(client, auth_headers):
    client.post("/favorites/", json={"station_number": "14211720"}, headers=auth_headers)
    resp = client.delete("/favorites/14211720", headers=auth_headers)
    assert resp.status_code == 204
    assert client.get("/favorites/", headers=auth_headers).json() == []


def test_delete_nonexistent_favorite(client, auth_headers):
    resp = client.delete("/favorites/XXXXXXXX", headers=auth_headers)
    assert resp.status_code == 404


def test_favorites_require_auth(client):
    resp = client.get("/favorites/")
    assert resp.status_code == 403 or resp.status_code == 401
