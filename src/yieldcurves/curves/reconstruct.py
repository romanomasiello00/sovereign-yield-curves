from __future__ import annotations

from typing import Any

import numpy as np
from scipy.interpolate import PchipInterpolator, interp1d
from scipy.optimize import minimize

from yieldcurves.config import standard_tenor_labels, standard_tenor_years, standard_tenors
from yieldcurves.storage import build_row, ingestion_timestamp

EPS = 1e-10
TENOR_MATCH_EPS = 1e-6


def clean_curve_points(
    points: list[tuple[float, float]],
    min_rate: float = -5.0,
    max_rate: float = 50.0,
) -> list[tuple[float, float]]:
    cleaned: list[tuple[float, float]] = []
    for t, r in points:
        if t <= 0:
            continue
        if not np.isfinite(t) or not np.isfinite(r):
            continue
        if r < min_rate or r > max_rate:
            continue
        cleaned.append((t, r))
    cleaned.sort(key=lambda x: x[0])
    return cleaned


def _points_to_arrays(points: list[tuple[float, float]]):
    xs = np.array([p[0] for p in points], dtype=float)
    ys = np.array([p[1] for p in points], dtype=float)
    return xs, ys


def fit_pchip_curve(
    points: list[tuple[float, float]],
    target_tenors: list[float] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    if target_tenors is None:
        target_tenors = standard_tenor_years()
    xs, ys = _points_to_arrays(points)
    if len(xs) < 2:
        raise ValueError("Need at least 2 points for PCHIP interpolation")
    pchip = PchipInterpolator(xs, ys, extrapolate=False)
    target_arr = np.array(target_tenors, dtype=float)
    valid_mask = (target_arr >= xs.min()) & (target_arr <= xs.max())
    result = np.full_like(target_arr, np.nan, dtype=float)
    result[valid_mask] = pchip(target_arr[valid_mask])
    return target_arr, result


def fit_linear_curve(
    points: list[tuple[float, float]],
    target_tenors: list[float] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    if target_tenors is None:
        target_tenors = standard_tenor_years()
    xs, ys = _points_to_arrays(points)
    if len(xs) < 2:
        raise ValueError("Need at least 2 points for linear interpolation")
    linear = interp1d(xs, ys, kind="linear", bounds_error=False, fill_value=np.nan)
    target_arr = np.array(target_tenors, dtype=float)
    result = linear(target_arr)
    return target_arr, result


def _nss_yield(
    T: float, beta0: float, beta1: float, beta2: float, beta3: float,
    tau1: float, tau2: float,
) -> float:
    if abs(T) < EPS:
        return beta0 + beta1
    t1 = T / tau1 if tau1 > EPS else 1e6
    t2 = T / tau2 if tau2 > EPS else 1e6
    term1 = (1 - np.exp(-t1)) / t1
    term2 = ((1 - np.exp(-t1)) / t1) - np.exp(-t1)
    term3 = ((1 - np.exp(-t2)) / t2) - np.exp(-t2)
    return beta0 + beta1 * term1 + beta2 * term2 + beta3 * term3


def _nss_error(params, Ts, ys):
    beta0, beta1, beta2, beta3, tau1, tau2 = params
    tau1 = max(tau1, 0.1)
    tau2 = max(tau2, 0.1)
    fitted = np.array([_nss_yield(T, beta0, beta1, beta2, beta3, tau1, tau2) for T in Ts])
    return np.sum((fitted - ys) ** 2)


def fit_nelson_siegel_svensson(
    points: list[tuple[float, float]],
    target_tenors: list[float] | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, float] | None]:
    if target_tenors is None:
        target_tenors = standard_tenor_years()
    xs, ys = _points_to_arrays(points)
    if len(xs) < 6:
        raise ValueError("Need at least 6 points for NSS fit")
    x0 = [np.mean(ys), -1.0, 0.0, 0.0, 2.0, 5.0]
    bounds = [
        (-10, 20),
        (-15, 15),
        (-15, 15),
        (-15, 15),
        (0.1, 30),
        (0.1, 30),
    ]
    try:
        result = minimize(
            _nss_error,
            x0,
            args=(xs, ys),
            bounds=bounds,
            method="L-BFGS-B",
        )
        beta0, beta1, beta2, beta3, tau1, tau2 = result.x
    except Exception:
        nan_arr = np.full(len(target_tenors), np.nan)
        return np.array(target_tenors), nan_arr, None
    params = {
        "beta0": beta0, "beta1": beta1, "beta2": beta2,
        "beta3": beta3, "tau1": tau1, "tau2": tau2,
    }
    target_arr = np.array(target_tenors, dtype=float)
    result_vals = np.array(
        [_nss_yield(T, beta0, beta1, beta2, beta3, tau1, tau2) for T in target_tenors]
    )
    return target_arr, result_vals, params


def reconstruct_country_curve(
    country: str,
    date_str: str,
    points: list[tuple[float, float]],
    method_priority: list[str] | None = None,
    extrapolation_limits: tuple[float, float] = (0.5, 2.0),
    rate_type: str = "reconstructed_curve_yield",
    curve_family: str = "reconstructed_nominal_government",
) -> list[dict[str, Any]]:
    if method_priority is None:
        method_priority = ["pchip", "linear"]
    cleaned = clean_curve_points(points)
    if len(cleaned) < 2:
        return []
    target_tenors = standard_tenor_years()
    target_labels = standard_tenor_labels()
    if not target_tenors:
        return []
    min_t = min(p[0] for p in cleaned)
    max_t = max(p[0] for p in cleaned)
    short_limit, long_limit = extrapolation_limits
    fit_method: str = "linear_interpolation"
    rates_out: np.ndarray = np.full(len(target_tenors), np.nan)
    nss_params: dict[str, float] | None = None
    for method in method_priority:
        try:
            if method == "nelson_siegel_svensson":
                if len(cleaned) >= 6:
                    _, rates_out, nss_params = fit_nelson_siegel_svensson(cleaned, target_tenors)
                    fit_method = "nelson_siegel_svensson"
                    break
            elif method == "pchip":
                if len(cleaned) >= 4:
                    _, rates_out = fit_pchip_curve(cleaned, target_tenors)
                    fit_method = "pchip_interpolation"
                    if not np.all(np.isnan(rates_out)):
                        break
            elif method == "linear":
                _, rates_out = fit_linear_curve(cleaned, target_tenors)
                fit_method = "linear_interpolation"
                if not np.all(np.isnan(rates_out)):
                    break
        except (ValueError, RuntimeError):
            continue
    ts = ingestion_timestamp()
    rows: list[dict[str, Any]] = []
    for i, ty in enumerate(target_tenors):
        rate = rates_out[i] if i < len(rates_out) else np.nan
        is_interpolated = ty >= min_t and ty <= max_t
        is_extrapolated = ty < min_t or ty > max_t
        data_quality = "ok"
        if is_extrapolated:
            if ty < min_t and (min_t - ty) > short_limit:
                data_quality = "missing_short_end"
                rate = np.nan
            elif ty > max_t and (ty - max_t) > long_limit:
                data_quality = "missing_long_end"
                rate = np.nan
        if rate is None or (isinstance(rate, float) and np.isnan(rate)):
            data_quality = data_quality if data_quality != "ok" else "sparse_curve"
        rows.append(
            build_row(
                country_code=country,
                country_name="",
                currency="",
                source_id="",
                source_name="",
                source_url="",
                observation_date=date_str,
                publication_date=date_str,
                tenor_label=target_labels[i] if i < len(target_labels) else "",
                tenor_years=float(ty),
                rate=float(rate) if not np.isnan(rate) else None,
                rate_unit="percent",
                rate_type=rate_type,
                curve_family=curve_family,
                compounding="source_native",
                day_count="source_native",
                source_native_tenor="",
                source_native_curve_name="",
                instrument_count_used=float(len(cleaned)),
                fit_method=fit_method,
                is_interpolated=bool(is_interpolated),
                is_extrapolated=bool(is_extrapolated),
                data_quality_flag=data_quality,
                raw_file_hash="",
                ingestion_timestamp=ts,
            )
        )
    return rows


def build_standard_grid(
    native_rows: list[dict[str, Any]],
    country_code: str,
    country_name: str,
    currency: str,
    source_id: str,
    source_name: str,
    source_url: str,
    rate_type: str,
    curve_family: str,
    compounding: str = "source_native",
    day_count: str = "source_native",
    raw_file_hash: str = "",
) -> list[dict[str, Any]]:
    """Generate standard-grid rows for standard tenors not present in native data.

    For each observation_date in native_rows:
      - Standard tenors with exact native matches are skipped (native row covers it).
      - Standard tenors inside [min_native, max_native] with >=4 native points use PCHIP.
      - Standard tenors below min_native get data_quality_flag = missing_short_end.
      - Standard tenors above max_native get data_quality_flag = missing_long_end.
      - Standard tenors inside range with <4 native points get data_quality_flag = sparse_curve.
    No NSS fitting, no linear interpolation, no extrapolation.
    """
    std_list = standard_tenors()
    ts = ingestion_timestamp()

    by_date: dict[str, list[dict]] = {}
    for r in native_rows:
        d = r.get("observation_date", "")
        if not d:
            continue
        by_date.setdefault(d, []).append(r)

    results: list[dict[str, Any]] = []

    for date_str in sorted(by_date.keys()):
        date_rows = by_date[date_str]
        native_points: list[tuple[float, float]] = []
        native_tenor_set: set[float] = set()
        for r in date_rows:
            ty = r.get("tenor_years", 0.0)
            rate = r.get("rate")
            if rate is None or (isinstance(rate, float) and np.isnan(rate)):
                continue
            if ty <= 0:
                continue
            native_points.append((ty, float(rate)))
            native_tenor_set.add(ty)

        if not native_points:
            continue

        native_points.sort(key=lambda x: x[0])
        min_t = native_points[0][0]
        max_t = native_points[-1][0]
        native_tenors_arr = np.array([p[0] for p in native_points])
        native_rates_arr = np.array([p[1] for p in native_points])

        for std in std_list:
            std_ty = std["years"]
            std_label = std["label"]

            if any(abs(nt - std_ty) < TENOR_MATCH_EPS for nt in native_tenor_set):
                continue

            if std_ty < min_t - TENOR_MATCH_EPS:
                data_quality = "missing_short_end"
                rate_val = None
                fit_method: str | None = None
                is_interp = False
            elif std_ty > max_t + TENOR_MATCH_EPS:
                data_quality = "missing_long_end"
                rate_val = None
                fit_method = None
                is_interp = False
            elif len(native_points) >= 4:
                try:
                    pchip = PchipInterpolator(native_tenors_arr, native_rates_arr, extrapolate=False)
                    rate_val = float(pchip(std_ty))
                    if np.isnan(rate_val):
                        raise ValueError
                    data_quality = "ok"
                    fit_method = "pchip_interpolation"
                    is_interp = True
                except (ValueError, RuntimeError):
                    rate_val = None
                    data_quality = "sparse_curve"
                    fit_method = None
                    is_interp = False
            else:
                rate_val = None
                data_quality = "sparse_curve"
                fit_method = None
                is_interp = False

            results.append(
                build_row(
                    country_code=country_code,
                    country_name=country_name,
                    currency=currency,
                    source_id=source_id,
                    source_name=source_name,
                    source_url=source_url,
                    observation_date=date_str,
                    publication_date=date_str,
                    tenor_label=std_label,
                    tenor_years=std_ty,
                    rate=rate_val,
                    rate_unit="percent",
                    rate_type=rate_type,
                    curve_family=curve_family,
                    compounding=compounding,
                    day_count=day_count,
                    source_native_tenor="",
                    source_native_curve_name="",
                    instrument_count_used=None,
                    fit_method=fit_method,
                    is_interpolated=is_interp,
                    is_extrapolated=False,
                    data_quality_flag=data_quality,
                    raw_file_hash=raw_file_hash,
                    ingestion_timestamp=ts,
                )
            )

    return results
