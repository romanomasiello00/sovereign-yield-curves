from yieldcurves.config import standard_tenor_labels, standard_tenor_years

TENOR_LABEL_MAP: dict[str, float] = {
    "1M": 1.0 / 12,
    "2M": 2.0 / 12,
    "3M": 0.25,
    "4M": 4.0 / 12,
    "5M": 5.0 / 12,
    "6M": 0.5,
    "7M": 7.0 / 12,
    "8M": 8.0 / 12,
    "9M": 9.0 / 12,
    "10M": 10.0 / 12,
    "11M": 11.0 / 12,
    "1Y": 1.0,
    "2Y": 2.0,
    "3Y": 3.0,
    "4Y": 4.0,
    "5Y": 5.0,
    "6Y": 6.0,
    "7Y": 7.0,
    "8Y": 8.0,
    "9Y": 9.0,
    "10Y": 10.0,
    "12Y": 12.0,
    "15Y": 15.0,
    "20Y": 20.0,
    "25Y": 25.0,
    "30Y": 30.0,
    "35Y": 35.0,
    "40Y": 40.0,
    "45Y": 45.0,
    "50Y": 50.0,
}


def parse_tenor_label(label: str) -> float | None:
    cleaned = label.strip().upper().replace(" ", "")
    if cleaned in TENOR_LABEL_MAP:
        return TENOR_LABEL_MAP[cleaned]
    return None


def standard_tenor_grid() -> list[dict[str, float | str]]:
    years = standard_tenor_years()
    labels = standard_tenor_labels()
    return [{"label": labels[i], "years": years[i]} for i in range(len(years))]
