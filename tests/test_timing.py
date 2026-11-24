from datetime import datetime, timedelta

from aqi_core.parser import parse_page
from aqi_core.timing import best_window, format_window


def _delhi(load_fixture):
    return parse_page(load_fixture("new_delhi.md"), "u")


def test_delhi_one_hour(load_fixture):
    w = best_window(_delhi(load_fixture).history, 60)
    assert (w.start, w.end, w.mean_aqi) == (datetime(2026, 11, 23, 16, 1), datetime(2026, 11, 23, 17, 1), 178.5)
    assert format_window(w) == "4:01 PM–5:01 PM"


def test_delhi_two_hours(load_fixture):
    w = best_window(_delhi(load_fixture).history, 120)
    assert (w.start, w.mean_aqi) == (datetime(2026, 11, 23, 15, 31), 179.75)


def test_night_minimum_ignored():
    base = datetime(2026, 1, 1, 0, 0)
    hist = [(base + timedelta(minutes=30 * i), 10 if i == 6 else 100) for i in range(48)]  # 03:00 cleanest
    w = best_window(hist, 30)
    assert 6 <= w.start.hour < 21


def test_tie_goes_to_earliest():
    base = datetime(2026, 1, 1, 6, 0)
    hist = [(base + timedelta(minutes=30 * i), 50) for i in range(10)]
    assert best_window(hist, 30).start == base


def test_no_window():
    assert best_window([], 60) is None
    assert best_window([(datetime(2026, 1, 1, 12, 0), 50)], 16 * 60) is None


def test_format_window_single_digit_morning():
    from aqi_core.timing import Window
    assert format_window(Window(datetime(2026, 1, 1, 6, 0), datetime(2026, 1, 1, 7, 30), 40)) == "6:00 AM–7:30 AM"
