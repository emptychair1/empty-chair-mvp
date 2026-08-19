import json
from pathlib import Path

import m4_synthetic_harness as h

FIXTURES = Path(__file__).parent / "fixtures" / "m4_historical_regressions.json"


def test_historical_regression_fixtures_match_expected_failures():
    cases = json.loads(FIXTURES.read_text())
    for name, case in cases.items():
        evaluation = h.evaluate(case["turns"])
        actual = {c.name for c in evaluation.checks if not c.passed}
        expected = set(case["expected_failures"])
        if expected:
            assert expected.issubset(actual), (name, evaluation.as_dict())
        else:
            assert evaluation.passed, (name, evaluation.as_dict())
