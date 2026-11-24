"""Health-recommendation agent (agno + OpenRouter) fed with the parsed aqi.in reading."""

import os
from typing import Dict, Iterator, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from aqi_core.models import POLLUTANT_KEYS, POLLUTANT_NAMES, POLLUTANT_UNITS, AqiReading, UserInput
from aqi_core.standards import us_aqi_band
from aqi_core.timing import Window, format_window

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")


def _fmt(value: float) -> str:
    return f"{value:g}"


def build_prompt(reading: AqiReading, user: UserInput, dose: Dict, window: Optional[Window]) -> str:
    band = us_aqi_band(reading.aqi)
    pollutant_lines = "\n".join(
        f"- {POLLUTANT_NAMES[k]}: {_fmt(reading.pollutants[k])} {POLLUTANT_UNITS[k]}"
        for k in POLLUTANT_KEYS if k in reading.pollutants
    )

    weather = []
    if reading.temperature_c is not None:
        weather.append(f"- Temperature: {_fmt(reading.temperature_c)}°C")
    if reading.humidity_pct is not None:
        weather.append(f"- Humidity: {_fmt(reading.humidity_pct)}%")
    if reading.wind_kmh is not None:
        weather.append(f"- Wind speed: {_fmt(reading.wind_kmh)} km/h")
    if reading.uv_index is not None:
        weather.append(f"- UV index: {_fmt(reading.uv_index)}")
    weather_block = "Weather:\n" + "\n".join(weather) if weather else ""

    dose_block = ""
    if dose:
        dose_block = (
            "Exposure estimate for the planned activity:\n"
            f"- Breathing rate: {_fmt(dose.get('ventilation_l_min', 0))} L/min\n"
            f"- PM2.5 inhaled: {_fmt(dose.get('dose_ug', 0))} µg "
            f"(about {_fmt(dose.get('cigarettes', 0))} cigarette-equivalents)\n"
            f"- Share of a WHO 24h guideline day: {_fmt(dose.get('who_day_fraction', 0))}%"
        )

    if window:
        timing = (f"Based on the last 24 hours the air was cleanest {format_window(window)} "
                  f"(average AQI {window.mean_aqi:.0f}). This is a pattern, not a forecast.")
    else:
        timing = "No clear cleaner window in the last 24 hours."

    updated = reading.updated_at.strftime("%Y-%m-%d %H:%M") if reading.updated_at else "unknown"

    return f"""Air quality right now in {reading.place} (source: {reading.url}, updated {updated} local time):
- AQI: {reading.aqi} on the US AQI scale, category "{band.label}"
{pollutant_lines}

{weather_block}

{dose_block}

Daily pattern: {timing}

User's context:
- Location typed: {user.city}, {user.state}, {user.country}
- Medical conditions: {user.medical_conditions or 'None'}
- Planned activity: {user.planned_activity} ({user.duration_minutes} minutes at "{user.intensity_label}" intensity)

Be concise and concrete. Use the numbers above rather than inventing any.
**Comprehensive Health Recommendations:**
1. **Impact of Current Air Quality on Health:**
2. **Necessary Safety Precautions for Planned Activity:**
3. **Advisability of Planned Activity:**
4. **Best Time to Conduct the Activity:**
"""


class ModelError(RuntimeError):
    """The LLM provider reported an error (rate limit, bad key, unknown model)."""


class HealthRecommendationAgent:
    def __init__(self, openrouter_key: str, model_id: str = DEFAULT_MODEL,
                 base_url: str = OPENROUTER_BASE_URL) -> None:
        self.model_id = model_id
        self.agent = Agent(
            model=OpenAIChat(id=model_id, name="Health Recommendation Agent",
                             api_key=openrouter_key, base_url=base_url)
        )

    def stream_recommendations(self, reading: AqiReading, user: UserInput, dose: Dict,
                               window: Optional[Window]) -> Iterator[str]:
        """Yield text as the model writes; falls back to one shot if streaming yields nothing."""
        prompt = build_prompt(reading, user, dose, window)
        accumulated = ""
        try:
            for event in self.agent.run(prompt, stream=True):
                kind = getattr(event, "event", None)
                content = getattr(event, "content", None)
                if kind == "RunError":
                    # agno catches model errors (rate limit, bad key) and yields them as events
                    raise ModelError(content or "The model returned an error.")
                if kind not in (None, "RunContent") or not content or not isinstance(content, str):
                    continue
                # agno may emit deltas or the cumulative string depending on version
                delta = content[len(accumulated):] if content.startswith(accumulated) else content
                if delta:
                    accumulated += delta
                    yield delta
        except Exception as exc:
            if isinstance(exc, ModelError) or accumulated.strip():
                raise
        if not accumulated.strip():
            fallback = self.agent.run(prompt)
            text = getattr(fallback, "content", "") or ""
            if str(getattr(fallback, "status", "")).upper().endswith("ERROR"):
                raise ModelError(text or "The model returned an error.")
            if text:
                yield text
