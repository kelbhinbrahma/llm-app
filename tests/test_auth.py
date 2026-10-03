def test_login_success(client):
    response = client.post("/auth/login", json={"username": "alice", "password": "alice123"})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "user"
    assert body["access_token"]


def test_login_wrong_password(client):
    response = client.post("/auth/login", json={"username": "alice", "password": "wrong"})
    assert response.status_code == 401


def test_login_unknown_user(client):
    response = client.post("/auth/login", json={"username": "nobody", "password": "x"})
    assert response.status_code == 401


def test_chat_without_token(client):
    response = client.post("/chat", json={"question": "hi"})
    assert response.status_code == 401


def test_chat_with_invalid_token(client):
    headers = {"Authorization": "Bearer not-a-real-token"}
    response = client.post("/chat", json={"question": "hi"}, headers=headers)
    assert response.status_code == 401


def test_readonly_user_cannot_chat(client, readonly_headers):
    response = client.post("/chat", json={"question": "hi"}, headers=readonly_headers)
    assert response.status_code == 403


def test_metrics_only_for_admin(client, user_headers, admin_headers):
    assert client.get("/metrics", headers=user_headers).status_code == 403
    response = client.get("/metrics", headers=admin_headers)
    assert response.status_code == 200
    assert "http_requests_total" in response.text


def test_readonly_can_see_reports(client, readonly_headers, user_headers):
    assert client.get("/reports/usage", headers=readonly_headers).status_code == 200
    assert client.get("/reports/usage", headers=user_headers).status_code == 403
