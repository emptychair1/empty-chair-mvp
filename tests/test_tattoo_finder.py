def test_tattoo_finder_routes_registered():
    import production_entry

    routes = {
        (getattr(route, "path", None), tuple(sorted(getattr(route, "methods", set()) or set())))
        for route in production_entry.app.router.routes
    }
    assert any(path == "/tattoo-finder/{market}" and "GET" in methods for path, methods in routes)
    assert any(path == "/tattoo-finder/{market}" and "POST" in methods for path, methods in routes)


def test_tattoo_finder_templates_exist():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    landing = (root / "templates" / "tattoo_finder.html").read_text()
    complete = (root / "templates" / "tattoo_finder_complete.html").read_text()
    assert "Find My Tattoo Fit" in landing
    assert 'name="project"' in landing
    assert 'name="budget"' in landing
    assert 'name="timing"' in landing
    assert 'name="phone"' in landing
    assert "Your tattoo request is in." in complete
