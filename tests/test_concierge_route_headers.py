def test_concierge_page_response_headers_regression():
    import concierge

    class QueryParams(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class RequestStub:
        query_params = QueryParams()

    response = concierge.concierge_page(RequestStub())
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
