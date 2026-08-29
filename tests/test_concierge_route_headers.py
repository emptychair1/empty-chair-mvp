from fastapi.testclient import TestClient

import concierge  # noqa: F401
import app as core


def test_concierge_page_response_headers_regression():
    with TestClient(core.app) as client:
        response = client.get("/concierge")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
