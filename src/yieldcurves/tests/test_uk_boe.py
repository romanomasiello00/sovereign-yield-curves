from __future__ import annotations

import io
import zipfile

import pandas as pd

from yieldcurves.sources.uk_boe import (
    _canonical_tenor_years,
    _normalise_date,
    _parse_boe_sheet,
    _process_zip,
)


def test_normalise_date():
    assert _normalise_date("2024-01-15") == "2024-01-15"
    assert _normalise_date("15-Jan-2024") == "2024-01-15"
    assert _normalise_date(pd.NaT) is None
    assert _normalise_date("") is None


def test_parse_boe_sheet_mock():
    df = pd.DataFrame({
        0: ["Maturity", "months:", "years:", None, "2024-01-15", "2024-01-16"],
        1: [None, "1.0", "0.08333333", None, None, 3.5],
        2: [None, "2.0", "0.16666667", None, 4.0, 4.1],
        3: [None, "3.0", "0.25", None, 4.5, 4.6],
    })
    rows = _parse_boe_sheet(df, "https://example.com", "nominal_government",
                            "zero_spot", "test_sheet", "abc123")
    assert len(rows) == 5
    assert rows[0]["country_code"] == "GB"
    assert rows[0]["tenor_years"] == 0.166667
    assert rows[0]["rate"] == 4.0
    assert rows[0]["rate_type"] == "zero_spot"
    assert rows[-1]["rate"] == 4.6


def test_empty_sheet():
    df = pd.DataFrame({0: []})
    rows = _parse_boe_sheet(df, "", "nominal_government",
                            "zero_spot", "empty", "x")
    assert rows == []


def test_no_date_column():
    df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
    rows = _parse_boe_sheet(df, "", "nominal_government",
                            "zero_spot", "no_date", "x")
    assert rows == []


def test_parse_full_curve_sheet_with_blank_header_rows():
    df = pd.DataFrame({
        0: [None, None, "Maturity", "years:", None, "2026-05-01", "2026-05-02"],
        1: [None, None, None, 0.5, None, 3.9, 4.0],
        2: [None, None, None, 10.0, None, 4.3, 4.4],
        3: [None, None, None, 40.0, None, 4.6, 4.7],
    })
    rows = _parse_boe_sheet(
        df,
        "https://example.com",
        "nominal_government",
        "zero_spot",
        "spot curve",
        "abc123",
    )
    assert len(rows) == 6
    assert {row["tenor_label"] for row in rows} == {"0.5Y", "10Y", "40Y"}
    assert max(row["tenor_years"] for row in rows) == 40.0


def test_canonical_tenor_years_and_year_labels():
    df = pd.DataFrame({
        0: [None, None, "Maturity", "years:", None, "2026-05-01"],
        1: [None, None, None, 0.49999998, None, 3.9],
        2: [None, None, None, 2.08333333, None, 4.3],
        3: [None, None, None, 35.50000001, None, 4.6],
    })
    rows = _parse_boe_sheet(
        df,
        "https://example.com",
        "nominal_government",
        "zero_spot",
        "spot curve",
        "abc123",
    )
    assert [row["tenor_years"] for row in rows] == [0.5, 2.083333, 35.5]
    assert [row["tenor_label"] for row in rows] == ["0.5Y", "2.08333Y", "35.5Y"]
    assert _canonical_tenor_years(0.49999998) == 0.5
    assert _canonical_tenor_years(2.08333333) == 2.083333


def test_process_zip_uses_workbook_name_and_spot_sheets_only():
    nominal_spot = pd.DataFrame({
        0: [None, None, "Maturity", "years:", None, "2026-05-01"],
        1: [None, None, None, 0.5, None, 3.9],
        2: [None, None, None, 10.0, None, 4.3],
    })
    nominal_forward = pd.DataFrame({
        0: [None, None, "Maturity", "years:", None, "2026-05-01"],
        1: [None, None, None, 0.5, None, 9.9],
        2: [None, None, None, 10.0, None, 9.8],
    })
    ois_spot = pd.DataFrame({
        0: [None, None, "Maturity", "years:", None, "2026-05-01"],
        1: [None, None, None, 0.5, None, 3.5],
        2: [None, None, None, 25.0, None, 4.1],
    })

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        nominal_bytes = io.BytesIO()
        with pd.ExcelWriter(nominal_bytes, engine="openpyxl") as writer:
            nominal_forward.to_excel(writer, sheet_name="2. fwd curve", header=False, index=False)
            nominal_spot.to_excel(writer, sheet_name="4. spot curve", header=False, index=False)
        zf.writestr("GLC Nominal daily data current month.xlsx", nominal_bytes.getvalue())

        ois_bytes = io.BytesIO()
        with pd.ExcelWriter(ois_bytes, engine="openpyxl") as writer:
            ois_spot.to_excel(writer, sheet_name="4. spot curve", header=False, index=False)
        zf.writestr("OIS daily data current month.xlsx", ois_bytes.getvalue())

    rows = _process_zip(zip_buffer.getvalue(), "https://example.com/latest.zip", None)

    assert len(rows) == 4
    assert {row["curve_family"] for row in rows} == {"nominal_government", "ois"}
    assert {row["rate_type"] for row in rows} == {"zero_spot", "ois_zero_spot"}
    assert max(row["tenor_years"] for row in rows if row["curve_family"] == "nominal_government") == 10.0
    assert max(row["tenor_years"] for row in rows if row["curve_family"] == "ois") == 25.0
    assert all("fwd" not in row["source_native_curve_name"].lower() for row in rows)
