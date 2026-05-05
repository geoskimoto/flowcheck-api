import pytest


def test_register_success(client):
    resp = client.post("/auth/register", json={"email": "test@example.com", "password": "securepass123"})
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_register_duplicate_email(client):
    client.post("/auth/register", json={"email": "dup@example.com", "password": "password1"})
    resp = client.post("/auth/register", json={"email": "dup@example.com", "password": "password2"})
    assert resp.status_code == 409


def test_register_invalid_email(client):
    resp = client.post("/auth/register", json={"email": "not-an-email", "password": "pass"})
    assert resp.status_code == 422


def test_register_short_password(client):
    resp = client.post("/auth/register", json={"email": "pw@example.com", "password": "abc"})
    assert resp.status_code == 422


def test_login_success(client):
    client.post("/auth/register", json={"email": "login@example.com", "password": "mypassword"})
    resp = client.post("/auth/login", json={"email": "login@example.com", "password": "mypassword"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


def test_login_wrong_password(client):
    client.post("/auth/register", json={"email": "wp@example.com", "password": "correct"})
    resp = client.post("/auth/login", json={"email": "wp@example.com", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_email(client):
    resp = client.post("/auth/login", json={"email": "ghost@example.com", "password": "anything"})
    assert resp.status_code == 401


def test_refresh_token(client):
    reg = client.post("/auth/register", json={"email": "refresh@example.com", "password": "mypassword"})
    refresh_token = reg.json()["refresh_token"]
    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_refresh_invalid_token(client):
    resp = client.post("/auth/refresh", json={"refresh_token": "bogus.token.here"})
    assert resp.status_code == 401


def test_delete_account(client):
    reg = client.post("/auth/register", json={"email": "delete@example.com", "password": "mypassword"})
    token = reg.json()["access_token"]
    resp = client.delete("/auth/account", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 204
    # Subsequent login should fail
    resp2 = client.post("/auth/login", json={"email": "delete@example.com", "password": "mypassword"})
    assert resp2.status_code == 401
