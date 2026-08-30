def test_demand_read_api_route_registered():
    import production_entry

    routes = {
        (getattr(route, "path", None), tuple(sorted(getattr(route, "methods", set()) or set())))
        for route in production_entry.app.router.routes
    }
    assert any(path == "/api/admin/demand-data" and "GET" in methods for path, methods in routes)


def test_demand_read_api_has_no_contact_fields():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = (root / "demand_read_api.py").read_text()
    assert '"phone_exposed": False' in source
    assert '"email_exposed": False' in source
    assert "arbitrary SQL" in source
    assert "hmac.compare_digest" in source
