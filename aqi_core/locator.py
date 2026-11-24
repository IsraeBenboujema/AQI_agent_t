"""Build aqi.in dashboard URLs from free-text locations and pick the right search result."""

import re
import unicodedata
from typing import Iterable, List, Optional, Set

BASE = "https://www.aqi.in/dashboard"
_SUBPAGES = {"pm", "pm10", "co", "so2", "no2", "o3", "historical-analysis"}


# Letters NFKD cannot split into base + accent.
_EXTRA = str.maketrans({"ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O", "ß": "ss",
                        "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ı": "i", "þ": "th", "ð": "d"})


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", (text or "").translate(_EXTRA)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def candidate_urls(city: str, state: str, country: str) -> List[str]:
    city_slug, state_slug, country_slug = slugify(city), slugify(state), slugify(country)
    urls = []
    if state_slug and state_slug != "none":
        urls.append(f"{BASE}/{country_slug}/{state_slug}/{city_slug}")
    urls.append(f"{BASE}/{country_slug}/{city_slug}")
    return list(dict.fromkeys(urls))


def _last_segment(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def pick_dashboard_link(links: Iterable[str], city: str, exclude: Set[str]) -> Optional[str]:
    target = slugify(city)
    usable = [
        link for link in links
        if link.startswith(BASE + "/") and link not in exclude and _last_segment(link) not in _SUBPAGES
    ]
    for link in usable:
        if _last_segment(link) == target:
            return link
    for link in usable:
        if _last_segment(link).startswith(target):
            return link
    return None
