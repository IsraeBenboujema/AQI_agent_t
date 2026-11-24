import json

import pytest

from aqi_core.fetcher import AqiInClient, FetchFailed

NYC = "https://www.aqi.in/dashboard/united-states/new-york/new-york-city"


class FakeSite:
    def __init__(self, pages, links=None):
        self.pages = pages  # url -> (status, markdown) or Exception
        self.links = links or []
        self.scrapes = []
        self.maps = []

    def scrape(self, url):
        self.scrapes.append(url)
        page = self.pages.get(url, (404, "The Wind Blew This Page Away!"))
        if isinstance(page, Exception):
            raise page
        return page

    def map_links(self, base_url, query):
        self.maps.append((base_url, query))
        return self.links


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(site, clock=None):
    return AqiInClient(site.scrape, site.map_links, ttl_seconds=1800, clock=clock or Clock())


def test_first_candidate_wins(load_fixture):
    url = "https://www.aqi.in/dashboard/india/delhi/new-delhi"
    site = FakeSite({url: (200, load_fixture("new_delhi.md"))})
    result = make(site).fetch("New Delhi", "Delhi", "India")
    assert result.reading.aqi == 260
    assert result.reading.url == url
    assert result.from_cache is False
    assert site.maps == []


def test_falls_back_to_map(load_fixture):
    site = FakeSite(
        {
            "https://www.aqi.in/dashboard/united-states/new-york/new-york": (404, load_fixture("not_found.md")),
            "https://www.aqi.in/dashboard/united-states/new-york": (200, load_fixture("new_york_state.md")),
            NYC: (200, load_fixture("new_delhi.md").replace("# New Delhi Air Quality", "# New York City Air Quality")),
        },
        links=json.loads(load_fixture("map_new_york_city.json"))["links"],
    )
    result = make(site).fetch("New York", "New York", "United States")
    assert result.reading.url == NYC
    assert result.tried == [
        "https://www.aqi.in/dashboard/united-states/new-york/new-york",
        "https://www.aqi.in/dashboard/united-states/new-york",
        NYC,
    ]
    assert site.maps == [("https://www.aqi.in/dashboard/united-states", "New York")]


def test_wrong_city_rejected(load_fixture):
    site = FakeSite({"https://www.aqi.in/dashboard/india/maharashtra/mumbai": (200, load_fixture("rabat.md"))})
    with pytest.raises(FetchFailed):
        make(site).fetch("Mumbai", "Maharashtra", "India")


def test_cache(load_fixture):
    url = "https://www.aqi.in/dashboard/india/delhi"
    md = load_fixture("new_delhi.md").replace("# New Delhi Air Quality", "# Delhi Air Quality")
    site, clock = FakeSite({url: (200, md)}), Clock()
    client = make(site, clock)
    client.fetch("Delhi", "", "India")
    second = client.fetch(" delhi ", "", "INDIA")
    assert second.from_cache is True
    assert site.scrapes == [url]
    clock.now += 1801
    assert client.fetch("Delhi", "", "India").from_cache is False
    assert site.scrapes == [url, url]


def test_firecrawl_errors_raise_fetch_failed():
    urls = ["https://www.aqi.in/dashboard/india/maharashtra/mumbai", "https://www.aqi.in/dashboard/india/mumbai"]
    site = FakeSite({u: RuntimeError("402 Payment Required") for u in urls})
    with pytest.raises(FetchFailed) as err:
        make(site).fetch("Mumbai", "Maharashtra", "India")
    assert site.scrapes == [urls[0], urls[0], urls[1], urls[1]]
    for u in urls:
        assert u in str(err.value)
    assert "402" in str(err.value)
    assert err.value.tried == urls


def test_map_failure_still_raises_fetch_failed():
    site = FakeSite({})
    site.map_links = lambda base, q: (_ for _ in ()).throw(RuntimeError("map down"))
    with pytest.raises(FetchFailed):
        AqiInClient(site.scrape, site.map_links).fetch("Nowhere", "", "India")


def test_from_firecrawl_asks_for_fresh_pages(monkeypatch, load_fixture):
    import firecrawl

    calls = []
    page = load_fixture("new_delhi.md")

    class FakeApp:
        def __init__(self, api_key):
            self.api_key = api_key

        def scrape_url(self, url, params=None):
            calls.append(params)
            return {"markdown": page, "metadata": {"statusCode": 200}}

        def map_url(self, url, params=None):
            return {"links": []}

    monkeypatch.setattr(firecrawl, "FirecrawlApp", FakeApp)
    AqiInClient.from_firecrawl("fc-x").fetch("New Delhi", "Delhi", "India")
    assert calls and calls[0]["formats"] == ["markdown"]
    # Firecrawl serves hours-old cached copies by default; aqi.in updates every 30 min.
    assert 0 <= calls[0]["maxAge"] <= 600_000
    assert calls[0]["timeout"] <= 20_000


def test_timeouts_are_not_retried():
    urls = ["https://www.aqi.in/dashboard/india/maharashtra/mumbai", "https://www.aqi.in/dashboard/india/mumbai"]
    site = FakeSite({u: RuntimeError("Request Timeout: scrape timed out") for u in urls})
    with pytest.raises(FetchFailed):
        make(site).fetch("Mumbai", "Maharashtra", "India")
    assert site.scrapes == urls


def test_total_time_budget_stops_the_search():
    clock = Clock()
    site = FakeSite({})

    def slow_404(url):
        site.scrapes.append(url)
        clock.now += 40
        return 404, "not found"

    client = AqiInClient(slow_404, site.map_links, clock=clock, time_budget_seconds=60)
    with pytest.raises(FetchFailed, match="too long"):
        client.fetch("Mumbai", "Maharashtra", "India")
    assert site.maps == []


def test_empty_city_slug_fails_without_scraping():
    site = FakeSite({})
    with pytest.raises(FetchFailed):
        make(site).fetch("北京", "", "China")
    assert site.scrapes == [] and site.maps == []
