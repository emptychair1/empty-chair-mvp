import inspect

import demo_mode


def test_demo_control_is_postgres_compatible():
    source = inspect.getsource(demo_mode.demo_control).lower()
    assert "rowid" not in source
