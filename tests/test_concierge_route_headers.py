def test_concierge_page_response_headers_regression():
    import concierge
    import app as core
    from starlette.requests import Request

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/concierge",
        "raw_path": b"/concierge",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "root_path": "",
        "app": core.app,
        "router": core.app.router,
    }
    response = concierge.concierge_page(Request(scope))
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
