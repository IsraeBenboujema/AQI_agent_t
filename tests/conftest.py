from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    def _load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _load


@pytest.fixture
def delhi_reading(load_fixture):
    from aqi_core.parser import parse_page

    return parse_page(load_fixture("new_delhi.md"), "https://www.aqi.in/dashboard/india/delhi/new-delhi")


@pytest.fixture
def rabat_reading(load_fixture):
    from aqi_core.parser import parse_page

    return parse_page(load_fixture("rabat.md"), "https://www.aqi.in/dashboard/morocco/rabat-sale-kenitra/rabat")


@pytest.fixture
def user():
    from aqi_core.models import UserInput

    return UserInput(
        city="New Delhi", state="Delhi", country="India", medical_conditions="asthma",
        planned_activity="evening run", intensity_label="Vigorous (running, sports)", duration_minutes=60,
    )
