import json

from aqi_core.locator import candidate_urls, pick_dashboard_link, slugify


def test_slugify():
    assert slugify("  New Delhi ") == "new-delhi"
    assert slugify("NEW YORK") == "new-york"
    assert slugify("São Paulo") == "sao-paulo"
    assert slugify("Rabat-Salé-Kénitra") == "rabat-sale-kenitra"


def test_candidates_with_state():
    assert candidate_urls("Mumbai", "Maharashtra", "India") == [
        "https://www.aqi.in/dashboard/india/maharashtra/mumbai",
        "https://www.aqi.in/dashboard/india/mumbai",
    ]


def test_candidates_without_state():
    assert candidate_urls("Delhi", "", "India") == ["https://www.aqi.in/dashboard/india/delhi"]
    assert candidate_urls("Delhi", "None", "India") == ["https://www.aqi.in/dashboard/india/delhi"]


def test_candidates_deduplicated_when_city_equals_state():
    assert candidate_urls("Delhi", "Delhi", "India") == [
        "https://www.aqi.in/dashboard/india/delhi/delhi",
        "https://www.aqi.in/dashboard/india/delhi",
    ]


def test_pick_link_new_york(load_fixture):
    links = json.loads(load_fixture("map_new_york_city.json"))["links"]
    assert pick_dashboard_link(
        links, "New York", exclude={"https://www.aqi.in/dashboard/united-states/new-york"}
    ) == "https://www.aqi.in/dashboard/united-states/new-york/new-york-city"


def test_pick_link_prefers_exact_and_skips_pollutant_pages():
    links = [
        "https://www.aqi.in/dashboard/india/maharashtra/mumbai/pm",
        "https://www.aqi.in/dashboard/india/maharashtra/navi-mumbai",
        "https://www.aqi.in/dashboard/india/maharashtra/mumbai",
    ]
    assert pick_dashboard_link(links, "Mumbai", exclude=set()) == \
        "https://www.aqi.in/dashboard/india/maharashtra/mumbai"


def test_pick_link_none():
    assert pick_dashboard_link(["https://www.aqi.in/dashboard/india/goa/panaji"], "Mumbai", set()) is None


def test_slugify_letters_nfkd_cannot_split():
    assert slugify("Łódź") == "lodz"
    assert slugify("Thủ Đức") == "thu-duc"
    assert slugify("Wrocław") == "wroclaw"
    assert slugify("Ørsted") == "orsted"
    assert slugify("Straße") == "strasse"
