"""Fetch a city's aqi.in dashboard through Firecrawl: find the page, validate it, cache it."""

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from aqi_core.locator import BASE, candidate_urls, pick_dashboard_link, slugify
from aqi_core.models import AqiReading, NoLiveReading
from aqi_core.parser import parse_page

ScrapeFn = Callable[[str], Tuple[int, str]]
MapFn = Callable[[str, str], List[str]]

# Firecrawl serves cached copies (hours old) unless told otherwise; aqi.in updates half-hourly.
FRESH_MS = 10 * 60 * 1000
SCRAPE_TIMEOUT_MS = 20_000
TIME_BUDGET_S = 75  # never keep the user waiting longer than this


@dataclass
class FetchResult:
    reading: AqiReading
    tried: List[str]
    from_cache: bool


class FetchFailed(Exception):
    def __init__(self, city: str, tried: List[str], last_error: Optional[str] = None):
        self.tried = tried
        lines = [f"Could not find live air-quality data for '{city}' on aqi.in."]
        if tried:
            lines.append("Pages tried: " + ", ".join(tried))
        if last_error:
            lines.append(f"Last error: {last_error}")
        lines.append("Check the spelling, or try adding/removing the state.")
        super().__init__(" ".join(lines))


class AqiInClient:
    def __init__(
        self,
        scrape: ScrapeFn,
        map_links: MapFn,
        ttl_seconds: int = 1800,
        clock: Callable[[], float] = time.time,
        time_budget_seconds: float = TIME_BUDGET_S,
    ) -> None:
        self._scrape = scrape
        self._map_links = map_links
        self._ttl = ttl_seconds
        self._clock = clock
        self._budget = time_budget_seconds
        self._cache: Dict[Tuple[str, str, str], Tuple[float, AqiReading]] = {}

    @classmethod
    def from_firecrawl(cls, api_key: str) -> "AqiInClient":
        from firecrawl import FirecrawlApp

        app = FirecrawlApp(api_key=api_key)

        def scrape(url: str) -> Tuple[int, str]:
            data = app.scrape_url(url, params={"formats": ["markdown"], "timeout": SCRAPE_TIMEOUT_MS, "maxAge": FRESH_MS})
            status = int((data.get("metadata") or {}).get("statusCode") or 0)
            return status, data.get("markdown") or ""

        def map_links(base_url: str, query: str) -> List[str]:
            return list(app.map_url(base_url, params={"search": query, "limit": 10}).get("links") or [])

        return cls(scrape, map_links)

    def fetch(self, city: str, state: str, country: str) -> FetchResult:
        key = (slugify(city), slugify(state), slugify(country))
        cached = self._cache.get(key)
        if cached and self._clock() - cached[0] < self._ttl:
            return FetchResult(cached[1], [cached[1].url], from_cache=True)

        if not key[0] or not key[2]:
            raise FetchFailed(city, [], "Type the city and country in Latin letters (for example Beijing, China).")

        tried: List[str] = []
        errors: List[str] = []
        started = self._clock()

        def out_of_time() -> bool:
            if self._clock() - started > self._budget:
                errors.append(f"The search took too long (over {self._budget:.0f} s); aqi.in or Firecrawl may be slow.")
                return True
            return False

        for url in candidate_urls(city, state, country):
            if out_of_time():
                raise FetchFailed(city, tried, errors[-1])
            reading = self._try(url, city, tried, errors)
            if reading:
                return self._remember(key, reading, tried)

        if out_of_time():
            raise FetchFailed(city, tried, errors[-1])
        try:
            links = self._map_links(f"{BASE}/{slugify(country)}", city)
        except Exception as exc:  # network/quota: report it, don't crash
            errors.append(str(exc))
            links = []
        found = pick_dashboard_link(links, city, exclude=set(tried))
        if found and not out_of_time():
            reading = self._try(found, city, tried, errors)
            if reading:
                return self._remember(key, reading, tried)

        raise FetchFailed(city, tried, errors[-1] if errors else None)

    def _try(self, url: str, city: str, tried: List[str], errors: List[str]) -> Optional[AqiReading]:
        tried.append(url)
        page = None
        for _ in range(2):  # one retry on transient errors
            try:
                page = self._scrape(url)
                break
            except Exception as exc:
                errors.append(str(exc))
                if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                    break  # a slow page will be slow again; don't double the wait
        if page is None:
            return None
        status, markdown = page
        if status != 200:
            return None
        try:
            reading = parse_page(markdown, url)
        except NoLiveReading:
            return None
        return reading if slugify(city) in slugify(reading.place) else None

    def _remember(self, key, reading: AqiReading, tried: List[str]) -> FetchResult:
        self._cache[key] = (self._clock(), reading)
        return FetchResult(reading, tried, from_cache=False)
