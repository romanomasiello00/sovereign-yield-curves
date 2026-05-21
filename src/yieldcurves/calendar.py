from datetime import date, timedelta

WEEKDAYS_BUSINESS = frozenset({0, 1, 2, 3, 4})


def is_business_day(d: date) -> bool:
    return d.weekday() in WEEKDAYS_BUSINESS


def next_business_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def previous_business_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def business_days_before(d: date, n: int) -> date:
    current = d
    count = 0
    while count < n:
        current = previous_business_day(current)
        count += 1
    return current
