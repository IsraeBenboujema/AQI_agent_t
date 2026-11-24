"""Turn the markdown of an aqi.in dashboard page (as scraped by Firecrawl) into an AqiReading.

Every section is parsed independently: a section aqi.in leaves out for a city
(temperature, world rank, stations...) comes back empty instead of failing.
"""

import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from aqi_core.models import AqiReading, NoLiveReading, Station

_AQI_RE = re.compile(r"(\d+)\s*AQI \(US\)")
_PLACE_RE = re.compile(r"^# (.+?) Air Quality Index", re.M)
_UPDATED_RE = re.compile(r"Last Updated: \*\*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\*\*")
_RANK_RE = re.compile(r"Rank(\d+)(?:st|nd|rd|th)")
_NUMBER = r"(-?\d+(?:\.\d+)?)"

_POLLUTANT_LABELS = {"PM₂.₅": "pm25", "PM₁₀": "pm10", "CO": "co", "SO₂": "so2", "NO₂": "no2", "O₃": "o3"}
_POLLUTANT_RE = re.compile(r"\((PM₂\.₅|PM₁₀|CO|SO₂|NO₂|O₃)\)[\\\s]*" + _NUMBER + r"\s*(?:µg/m³|ppb)")

_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
_MONTH_HEADER_RE = re.compile(r"^(" + "|".join(_MONTHS) + r")\s*$", re.M)
_CAL_CELL_RE = re.compile(r"(\d{1,2}) ([A-Z][a-z]{2})\.?<br>(\d+|--)")
_HISTORY_ROW_RE = re.compile(r"^\| (\d{1,2}:\d{2}[ap]m) \| (\d+) \|", re.M)
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def _number(text: str) -> Optional[float]:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


def _section(markdown: str, heading_pattern: str) -> Tuple[Optional[re.Match], str]:
    """Return the heading match and the text up to the next level-2 heading."""
    match = re.search(heading_pattern, markdown, re.M)
    if not match:
        return None, ""
    rest = markdown[match.end():]
    end = rest.find("\n## ")
    return match, rest if end == -1 else rest[:end]


def _first(pattern: str, text: str) -> Optional[float]:
    match = re.search(pattern, text)
    return _number(match.group(1)) if match else None


def _readings_block(markdown: str, aqi_match: re.Match) -> str:
    """The live-reading area: from the AQI number to the pollutant section."""
    start = aqi_match.start()
    end = markdown.find("## Major Air Pollutants", start)
    return markdown[start:end if end != -1 else None]


def _pollutants(markdown: str) -> Dict[str, float]:
    _, body = _section(markdown, r"^## Major Air Pollutants.*$")
    found: Dict[str, float] = {}
    for label, value in _POLLUTANT_RE.findall(body):
        key = _POLLUTANT_LABELS[label]
        if key not in found and _number(value) is not None:
            found[key] = _number(value)
    return found


def _history(markdown: str, updated_at: Optional[datetime]) -> List[Tuple[datetime, int]]:
    if updated_at is None:
        return []
    _, body = _section(markdown, r"^## Historical Air Quality Data.*$")
    values = [int(v) for _, v in _HISTORY_ROW_RE.findall(body)]
    count = len(values)
    return [(updated_at - timedelta(minutes=30 * (count - 1 - i)), v) for i, v in enumerate(values)]


def _stations(markdown: str) -> List[Station]:
    _, body = _section(markdown, r"^## .+'s (?:Locations|Cities)\b.*$")
    stations = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("| ["):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        name = _LINK_RE.match(cells[0])
        aqi = _number(cells[2]) if len(cells) > 2 else None
        if not name or aqi is None:
            continue
        stations.append(Station(
            name=name.group(1).strip(),
            status=cells[1],
            aqi=int(aqi),
            pm25=_number(cells[3]) if len(cells) > 3 else None,
            pm10=_number(cells[4]) if len(cells) > 4 else None,
        ))
    return stations


def _calendar(markdown: str) -> List[Tuple[date, int]]:
    heading, body = _section(markdown, r"^## Air Quality Calendar (\d{4}).*$")
    if not heading:
        return []
    year = int(heading.group(1))
    parts = _MONTH_HEADER_RE.split(body)
    days: Dict[date, int] = {}
    for i in range(1, len(parts) - 1, 2):
        month_name, table = parts[i], parts[i + 1]
        month = _MONTHS.index(month_name) + 1
        for day, abbrev, value in _CAL_CELL_RE.findall(table):
            if abbrev != month_name[:3] or value == "--":
                continue
            try:
                days[date(year, month, int(day))] = int(value)
            except ValueError:
                continue
    return sorted(days.items())


def parse_page(markdown: str, url: str) -> AqiReading:
    aqi_match = _AQI_RE.search(markdown or "")
    if not aqi_match:
        raise NoLiveReading(f"No live AQI reading on {url}")

    place_match = _PLACE_RE.search(markdown)
    place = place_match.group(1).replace("\\", "").strip() if place_match else ""

    updated_match = _UPDATED_RE.search(markdown)
    updated_at = datetime.strptime(updated_match.group(1), "%Y-%m-%d %H:%M") if updated_match else None

    rank_match = _RANK_RE.search(markdown)
    block = _readings_block(markdown, aqi_match)

    return AqiReading(
        place=place,
        url=url,
        aqi=int(aqi_match.group(1)),
        updated_at=updated_at,
        world_rank=int(rank_match.group(1)) if rank_match else None,
        pollutants=_pollutants(markdown),
        temperature_c=_first(_NUMBER + r"\s*°C", block),
        humidity_pct=_first(r"Humidity\s*" + _NUMBER + r"\s*%", block),
        wind_kmh=_first(r"Wind Speed\s*" + _NUMBER + r"\s*km/h", block),
        uv_index=_first(r"UV Index\s*" + _NUMBER, block),
        history=_history(markdown, updated_at),
        stations=_stations(markdown),
        calendar=_calendar(markdown),
    )
