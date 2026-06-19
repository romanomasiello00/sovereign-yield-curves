from __future__ import annotations

import json

from yieldcurves.sources.canada_bankofcanada import _parse_observations

_SAMPLE = json.dumps(
    {
        "observations": [
            {
                "d": "2026-06-17",
                "BD.CDN.RRB.DQ.YLD": {"v": "1.77"},
                "BD.CDN.2YR.DQ.YLD": {"v": "2.82"},
                "BD.CDN.10YR.DQ.YLD": {"v": "3.42"},
                "BD.CDN.LONG.DQ.YLD": {"v": "3.82"},
            },
            {"d": "2026-06-16", "BD.CDN.2YR.DQ.YLD": {"v": ""}},
        ]
    }
).encode("utf-8")


def test_parse_observations_maps_tenors():
    rows = _parse_observations(_SAMPLE, "http://x")
    by_tenor = {r["tenor_label"]: r for r in rows}
    # RRB excluded, LONG -> 30Y, empty value skipped
    assert set(by_tenor) == {"2Y", "10Y", "30Y"}
    assert by_tenor["30Y"]["rate"] == 3.82
    assert by_tenor["2Y"]["observation_date"] == "2026-06-17"
    assert by_tenor["10Y"]["country_code"] == "CA"
    assert all("RRB" not in r["source_native_tenor"] for r in rows)


def test_parse_observations_skips_empty():
    rows = _parse_observations(_SAMPLE, "http://x")
    # the 2026-06-16 obs has only an empty 2YR -> no rows from it
    assert all(r["observation_date"] == "2026-06-17" for r in rows)
