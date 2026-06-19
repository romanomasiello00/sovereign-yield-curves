from __future__ import annotations

import math

from yieldcurves.bds.catalog import compute_importance_score


def test_compute_importance_score_handles_missing_series_name():
    config = {
        "scoring": {
            "category_keywords": {
                "high": {"keywords": ["yield"], "score": 0.9},
                "default": 0.6,
            }
        }
    }

    assert compute_importance_score(math.nan, config) == 0.6
