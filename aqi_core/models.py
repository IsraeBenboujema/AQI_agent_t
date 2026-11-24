"""Plain data shared by the scraper, the UI and the agent."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

POLLUTANT_KEYS = ("pm25", "pm10", "co", "no2", "so2", "o3")
POLLUTANT_NAMES = {"pm25": "PM2.5", "pm10": "PM10", "co": "CO", "no2": "NO2", "so2": "SO2", "o3": "O3"}
POLLUTANT_UNITS = {"pm25": "µg/m³", "pm10": "µg/m³", "co": "ppb", "no2": "ppb", "so2": "ppb", "o3": "ppb"}


class NoLiveReading(Exception):
    """The page has no current AQI (404 page, state-level overview, empty text)."""


@dataclass
class Station:
    name: str
    status: str
    aqi: int
    pm25: Optional[float]
    pm10: Optional[float]


@dataclass
class AqiReading:
    place: str
    url: str
    aqi: int
    updated_at: Optional[datetime] = None
    world_rank: Optional[int] = None
    pollutants: Dict[str, float] = field(default_factory=dict)  # PM in µg/m³, gases in ppb
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    wind_kmh: Optional[float] = None
    uv_index: Optional[float] = None
    history: List[Tuple[datetime, int]] = field(default_factory=list)  # oldest first, 30-min steps
    stations: List[Station] = field(default_factory=list)
    calendar: List[Tuple[date, int]] = field(default_factory=list)  # sorted by date


@dataclass
class UserInput:
    city: str
    state: str
    country: str
    medical_conditions: str
    planned_activity: str
    intensity_label: str
    duration_minutes: int
