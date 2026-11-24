"""Find the cleanest daytime stretch in the last 24 hours of half-hourly AQI."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

STEP = timedelta(minutes=30)


@dataclass
class Window:
    start: datetime
    end: datetime
    mean_aqi: float


def best_window(
    history: List[Tuple[datetime, int]],
    minutes: int,
    day_start: int = 6,
    day_end: int = 21,
) -> Optional[Window]:
    """Lowest-average run of points long enough for the activity, within waking hours."""
    k = max(1, math.ceil((minutes or 0) / 30))
    best: Optional[Window] = None
    for i in range(len(history) - k + 1):
        chunk = history[i:i + k]
        if not all(day_start <= t.hour < day_end for t, _ in chunk):
            continue
        mean = sum(v for _, v in chunk) / k
        if best is None or mean < best.mean_aqi:
            best = Window(chunk[0][0], chunk[-1][0] + STEP, mean)
    return best


def _clock(moment: datetime) -> str:
    return moment.strftime("%I:%M %p").lstrip("0")


def format_window(window: Window) -> str:
    return f"{_clock(window.start)}–{_clock(window.end)}"
