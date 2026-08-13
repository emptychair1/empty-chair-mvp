import inspect

import demo_mode


def test_demo_control_is_postgres_compatible():
    source = inspect.getsource(demo_mode.demo_control).lower()
    assert "rowid" not in source


def test_demo_customers_satisfy_required_phone_constraint():
    source = inspect.getsource(demo_mode._reset_data)
    assert '("demo_customer_jordan", "Jordan Lee", None' not in source
    assert '("demo_customer_casey", "Casey Reed", None' not in source
    assert '("demo_customer_riley", "Riley Chen", None' not in source
