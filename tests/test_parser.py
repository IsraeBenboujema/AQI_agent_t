from datetime import date, datetime

import pytest

from aqi_core.models import NoLiveReading, Station
from aqi_core.parser import parse_page

DELHI_URL = "https://www.aqi.in/dashboard/india/delhi/new-delhi"
RABAT_URL = "https://www.aqi.in/dashboard/morocco/rabat-sale-kenitra/rabat"


def test_new_delhi_headline(load_fixture):
    r = parse_page(load_fixture("new_delhi.md"), DELHI_URL)
    assert r.place == "New Delhi"
    assert r.url == DELHI_URL
    assert r.aqi == 260
    assert r.world_rank == 41
    assert r.updated_at == datetime(2026, 11, 24, 4, 31)


def test_new_delhi_pollutants_and_weather(load_fixture):
    r = parse_page(load_fixture("new_delhi.md"), DELHI_URL)
    assert r.pollutants == {"pm25": 185, "pm10": 259, "co": 908, "so2": 4, "no2": 18, "o3": 5}
    assert (r.temperature_c, r.humidity_pct, r.wind_kmh, r.uv_index) == (15, 58, 7.9, 0)


def test_new_delhi_history(load_fixture):
    r = parse_page(load_fixture("new_delhi.md"), DELHI_URL)
    assert len(r.history) == 49
    assert r.history[0] == (datetime(2026, 11, 23, 4, 31), 453)
    assert r.history[-1] == (datetime(2026, 11, 24, 4, 31), 260)


def test_new_delhi_stations(load_fixture):
    r = parse_page(load_fixture("new_delhi.md"), DELHI_URL)
    assert len(r.stations) == 451
    assert r.stations[0] == Station("Abul Fazal Enclave", "Severe", 264, 190, 265)


def test_new_delhi_calendar(load_fixture):
    r = parse_page(load_fixture("new_delhi.md"), DELHI_URL)
    assert len(r.calendar) == 327
    assert r.calendar[0] == (date(2026, 1, 1), 300)
    assert (date(2026, 1, 17), 545) in r.calendar
    assert (date(2026, 5, 1), 114) in r.calendar
    assert r.calendar == sorted(r.calendar)


def test_rabat_missing_sections(load_fixture):
    r = parse_page(load_fixture("rabat.md"), RABAT_URL)
    assert r.place == "Rabat" and r.aqi == 25
    assert r.temperature_c is None and r.world_rank is None
    assert (r.humidity_pct, r.wind_kmh) == (80, 3.6)
    assert r.pollutants["pm25"] == 5 and r.pollutants["pm10"] == 15
    assert len(r.history) == 49 and r.history[-1][1] == 25
    assert r.stations == [Station("Agdal", "Good", 25, 5, 15)]
    assert r.calendar[0] == (date(2026, 1, 1), 31)


def test_missing_updated_time_gives_empty_history(load_fixture):
    md = load_fixture("new_delhi.md").replace("Last Updated:", "Updated:")
    r = parse_page(md, DELHI_URL)
    assert r.updated_at is None and r.history == []
    assert r.aqi == 260


@pytest.mark.parametrize("name", ["new_york_state.md", "not_found.md", ""])
def test_no_live_reading(load_fixture, name):
    md = load_fixture(name) if name else ""
    with pytest.raises(NoLiveReading):
        parse_page(md, "https://www.aqi.in/x")


def test_new_york_city_seconds_and_own_clock_times(load_fixture):
    r = parse_page(load_fixture("new_york_city.md"),
                   "https://www.aqi.in/dashboard/united-states/new-york/new-york-city")
    assert r.place == "New York City"
    assert r.updated_at == datetime(2026, 11, 23, 20, 51, 2)
    assert len(r.history) == 48
    assert r.history[-1] == (datetime(2026, 11, 23, 20, 31), 26)
    assert r.history[0] == (datetime(2026, 11, 22, 21, 1), 46)
