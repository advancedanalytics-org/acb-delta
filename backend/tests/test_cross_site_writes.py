"""State-changing requests sent by a browser from another site are refused."""

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())

# Empty body: an allowed request reaches the route and fails validation (422) without touching
# the database or the LLM; a refused one gets 403.
URL = "/api/ai/suggest-edit"


def test_cross_site_delete_is_refused():
    response = client.post(URL, json={}, headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
    response = client.post(URL, json={}, headers={"Sec-Fetch-Site": "same-site"})
    assert response.status_code == 403


def test_same_origin_and_non_browser_requests_pass():
    assert client.post(URL, json={}, headers={"Sec-Fetch-Site": "same-origin"}).status_code != 403
    assert client.post(URL, json={}).status_code != 403


def test_origin_fallback_without_fetch_metadata():
    evil = {"Origin": "https://evil.example", "Host": "testserver"}
    assert client.post(URL, json={}, headers=evil).status_code == 403
    own = {"Origin": "https://testserver", "Host": "testserver"}
    assert client.post(URL, json={}, headers=own).status_code != 403
    assert client.post(URL, json={}, headers={"Origin": "null"}).status_code == 403


def test_reads_and_configured_origins_pass():
    assert client.get("/health", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200
    dev = {"Sec-Fetch-Site": "same-site", "Origin": "http://localhost:5173"}
    assert client.post(URL, json={}, headers=dev).status_code != 403
