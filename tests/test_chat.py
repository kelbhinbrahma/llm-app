from app import llm


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["database"] == "up"
    assert response.json()["redis"] == "up"


def test_chat_returns_answer(client, user_headers):
    response = client.post("/chat", json={"question": "What is Docker?"}, headers=user_headers)
    assert response.status_code == 200
    body = response.json()
    assert "What is Docker?" in body["answer"]
    assert body["cached"] is False
    assert body["prompt_tokens"] > 0
    assert body["latency_ms"] >= 0


def test_same_question_comes_from_cache(client, user_headers):
    client.post("/chat", json={"question": "What is Redis?"}, headers=user_headers)
    response = client.post("/chat", json={"question": "what is redis?  "}, headers=user_headers)
    assert response.json()["cached"] is True


def test_empty_question_rejected(client, user_headers):
    response = client.post("/chat", json={"question": ""}, headers=user_headers)
    assert response.status_code == 422


def test_rate_limit(client, user_headers):
    # RATE_LIMIT_PER_MINUTE is 5 in tests
    for i in range(5):
        response = client.post("/chat", json={"question": f"question {i}"}, headers=user_headers)
        assert response.status_code == 200
    response = client.post("/chat", json={"question": "one too many"}, headers=user_headers)
    assert response.status_code == 429


def test_retry_then_success(client, user_headers, monkeypatch):
    # The first call fails, the second (retry) works.
    calls = []
    real_call_model = llm.call_model

    def flaky_call_model(model, question):
        calls.append(model)
        if len(calls) == 1:
            raise TimeoutError("LLM timed out")
        return real_call_model(model, question)

    monkeypatch.setattr(llm, "call_model", flaky_call_model)
    response = client.post("/chat", json={"question": "retry test"}, headers=user_headers)
    assert response.status_code == 200
    assert len(calls) == 2


def test_fallback_model_used(client, user_headers, monkeypatch):
    # The main model always fails, so the fallback model must answer.
    monkeypatch.setattr(llm.config, "LLM_MODEL", "main-model")
    monkeypatch.setattr(llm.config, "LLM_FALLBACK_MODEL", "backup-model")

    def call_model(model, question):
        if model == "main-model":
            raise ConnectionError("main model down")
        return {"answer": "from backup", "model": model, "prompt_tokens": 1, "answer_tokens": 2}

    monkeypatch.setattr(llm, "call_model", call_model)
    response = client.post("/chat", json={"question": "fallback test"}, headers=user_headers)
    assert response.status_code == 200
    assert response.json()["model"] == "backup-model"


def test_all_llm_calls_fail_returns_503(client, user_headers, monkeypatch):
    def always_fail(model, question):
        raise TimeoutError("LLM timed out")

    monkeypatch.setattr(llm, "call_model", always_fail)
    response = client.post("/chat", json={"question": "fail test"}, headers=user_headers)
    assert response.status_code == 503


def test_chat_is_logged_in_database(client, user_headers, admin_headers):
    client.post("/chat", json={"question": "log me"}, headers=user_headers)
    report = client.get("/reports/usage", headers=admin_headers).json()
    alice = [row for row in report if row["username"] == "alice"][0]
    assert alice["requests"] >= 1
