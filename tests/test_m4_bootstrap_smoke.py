def test_production_bootstrap_imports_and_registers_m4_routes():
    import bootstrap

    paths = {
        getattr(route, 'path', None)
        for route in bootstrap.app.router.routes
    }

    assert '/health' in paths
    assert '/meet-m4' in paths
    assert '/m4-smooth' in paths
