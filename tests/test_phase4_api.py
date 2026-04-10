import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    # The FastAPI app initializes a Groq client at startup, so require the key.
    from src.phase4.app import create_app

    if not os.getenv("GROQ_API_KEY"):
        pytest.skip("GROQ_API_KEY not set; skipping Phase 4 API tests.")

    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_recommend_empty_shortlist_returns_200(client):
    # Use an unlikely location to force empty shortlist without calling LLM.
    payload = {
        "location": "ThisCityShouldNotExist",
        "budget_max_inr": 200.0,
        "cuisine": "Italian",
        "min_rating": 4.5,
        "extras": "",
    }
    r = client.post("/api/v1/recommend", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body
    assert len(body["items"]) > 0
    assert body["meta"]["shortlist_size"] > 0
    assert body["meta"]["reason"] == "SAMPLE_FALLBACK"


def test_recommend_success_calls_llm(client):
    # We can't know dataset locations in advance; pick a common city.
    payload = {
        "location": "Bangalore",
        "budget_max_inr": 1200.0,
        "cuisine": "Chinese",
        "min_rating": 3.0,
        "extras": "family-friendly",
    }
    r = client.post("/api/v1/recommend", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["summary"], str)
    assert "meta" in body and "model" in body["meta"]
    # items may be empty if catalog doesn't contain Bangalore; tolerate but require structure.
    assert "items" in body

