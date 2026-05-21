from __future__ import annotations

from yieldcurves.parsers.sdmx import parse_maturity_code


def test_parse_maturity_code():
    assert parse_maturity_code("R01XX") == 1.0
    assert parse_maturity_code("R10XX") == 10.0
    assert parse_maturity_code("R30XX") == 30.0
    assert parse_maturity_code("R15XX") == 15.0
    assert parse_maturity_code("UNKNOWN") is None


def test_maturity_code_map():
    codes = ["R01XX", "R02XX", "R03XX", "R05XX", "R07XX",
             "R10XX", "R15XX", "R20XX", "R25XX", "R30XX"]
    for code in codes:
        val = parse_maturity_code(code)
        assert val is not None
        assert val > 0
