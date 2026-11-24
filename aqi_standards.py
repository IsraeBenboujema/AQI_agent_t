"""AQI categories, guideline thresholds, activity profiles and inhalation-dose math.

Kept free of UI/LLM dependencies so both the Gradio and Streamlit apps can share it,
and so the numbers stay deterministic instead of being guessed by a model.
"""

from dataclasses import dataclass
from typing import Dict, List

# --- AQI categories ---------------------------------------------------------
# CPCB (India) bands - aqi.in reports on this scale.
CPCB_BANDS = [
    (50, "Good", "#00a651", "Minimal impact on health."),
    (100, "Satisfactory", "#7ac143", "Minor breathing discomfort for sensitive people."),
    (200, "Moderate", "#f2c200", "Breathing discomfort for people with asthma or heart conditions."),
    (300, "Poor", "#f37021", "Breathing discomfort on prolonged exposure; avoid strenuous activity."),
    (400, "Very Poor", "#e2231a", "Respiratory illness on prolonged exposure. Stay indoors if you can."),
    (500, "Severe", "#8b1a1a", "Health impact even for healthy people. Avoid outdoor exertion."),
]

# --- Guideline limits (24h averages) ---------------------------------------
WHO_PM25_24H = 15.0      # WHO 2021 guideline
WHO_PM10_24H = 45.0      # WHO 2021 guideline
CPCB_PM25_24H = 60.0     # CPCB national standard
CPCB_PM10_24H = 100.0    # CPCB national standard
CPCB_MODERATE_AQI = 100  # top of the "Satisfactory" band

# Mass-equivalent estimate: one cigarette delivers roughly 10 mg of PM2.5.
CIGARETTE_PM25_UG = 10_000.0
RESTING_VENTILATION_L_MIN = 6.0
MINUTES_PER_DAY = 1440.0


@dataclass(frozen=True)
class ActivityIntensity:
    label: str
    ventilation_l_min: float
    note: str


# Minute ventilation by activity level (litres/min), typical adult values.
ACTIVITY_PROFILES: Dict[str, ActivityIntensity] = {
    "Resting / sitting": ActivityIntensity(
        "Resting / sitting", 6.0, "sitting indoors or outdoors, minimal movement"
    ),
    "Light (slow walk)": ActivityIntensity(
        "Light (slow walk)", 12.0, "easy walking, shopping, light chores"
    ),
    "Moderate (brisk walk, cycling)": ActivityIntensity(
        "Moderate (brisk walk, cycling)", 30.0, "brisk walk, casual cycling, gentle sport"
    ),
    "Vigorous (running, sports)": ActivityIntensity(
        "Vigorous (running, sports)", 60.0, "jogging, running, football, tennis, gym cardio"
    ),
    "Max effort (competitive)": ActivityIntensity(
        "Max effort (competitive)", 85.0, "racing, competitive matches, HIIT"
    ),
}

DEFAULT_ACTIVITY = "Moderate (brisk walk, cycling)"
DEFAULT_DURATION_MIN = 60


def activity_choices() -> List[str]:
    return list(ACTIVITY_PROFILES.keys())


def get_activity(label: str) -> ActivityIntensity:
    return ACTIVITY_PROFILES.get(label) or ACTIVITY_PROFILES[DEFAULT_ACTIVITY]


def categorize_aqi(aqi: float) -> Dict[str, object]:
    """Map an AQI value to a CPCB band (label, colour, advice, band index)."""
    try:
        value = float(aqi)
    except (TypeError, ValueError):
        value = 0.0

    for index, (upper, label, colour, advice) in enumerate(CPCB_BANDS):
        if value <= upper:
            return {
                "label": label,
                "colour": colour,
                "advice": advice,
                "band": index,
                "scale": "CPCB (India)",
            }

    # Above 500: still "Severe", but flag that the number is off-scale.
    upper, label, colour, advice = CPCB_BANDS[-1]
    return {
        "label": label,
        "colour": colour,
        "advice": advice,
        "band": len(CPCB_BANDS) - 1,
        "scale": "CPCB (India)",
    }


def estimate_inhaled_dose(
    pm25_ug_m3: float,
    activity_label: str = DEFAULT_ACTIVITY,
    minutes: int = DEFAULT_DURATION_MIN,
) -> Dict[str, float]:
    """Estimate PM2.5 mass inhaled during an activity.

    dose (µg) = concentration (µg/m³) x ventilation (L/min) x minutes / 1000
    """
    activity = get_activity(activity_label)
    try:
        concentration = max(float(pm25_ug_m3 or 0.0), 0.0)
    except (TypeError, ValueError):
        concentration = 0.0
    try:
        duration = max(int(minutes or 0), 0)
    except (TypeError, ValueError):
        duration = 0

    volume_m3 = activity.ventilation_l_min * duration / 1000.0
    dose_ug = concentration * volume_m3

    resting_volume_m3 = RESTING_VENTILATION_L_MIN * duration / 1000.0
    resting_dose_ug = concentration * resting_volume_m3

    who_day_ug = WHO_PM25_24H * RESTING_VENTILATION_L_MIN * MINUTES_PER_DAY / 1000.0

    return {
        "activity": activity.label,
        "ventilation_l_min": activity.ventilation_l_min,
        "minutes": duration,
        "concentration_ug_m3": concentration,
        "volume_m3": round(volume_m3, 2),
        "dose_ug": round(dose_ug, 1),
        "resting_dose_ug": round(resting_dose_ug, 1),
        "cigarettes": round(dose_ug / CIGARETTE_PM25_UG, 3),
        "who_day_fraction": round(dose_ug / who_day_ug * 100.0, 1) if who_day_ug else 0.0,
        "intensity_multiplier": (
            round(dose_ug / resting_dose_ug, 1) if resting_dose_ug > 0 else 0.0
        ),
    }


def guideline_bars(aqi_data: Dict[str, float]) -> List[Dict[str, object]]:
    """Current readings expressed as a share of a health guideline (chart data)."""
    pm25 = float(aqi_data.get("pm25") or 0)
    pm10 = float(aqi_data.get("pm10") or 0)
    aqi = float(aqi_data.get("aqi") or 0)

    def pct(value: float, limit: float) -> float:
        return round(value / limit * 100.0, 1) if limit else 0.0

    return [
        {
            "metric": "PM2.5 vs WHO",
            "share_of_limit": pct(pm25, WHO_PM25_24H),
            "reading": f"{pm25:g} µg/m³",
            "limit": f"{WHO_PM25_24H:g} µg/m³",
        },
        {
            "metric": "PM10 vs WHO",
            "share_of_limit": pct(pm10, WHO_PM10_24H),
            "reading": f"{pm10:g} µg/m³",
            "limit": f"{WHO_PM10_24H:g} µg/m³",
        },
        {
            "metric": "AQI vs Moderate",
            "share_of_limit": pct(aqi, CPCB_MODERATE_AQI),
            "reading": f"{aqi:g}",
            "limit": f"{CPCB_MODERATE_AQI}",
        },
    ]


def has_usable_data(aqi_data: Dict[str, float]) -> bool:
    """Reject the all-zeros payload produced when scraping fails."""
    if not aqi_data:
        return False
    numeric = [aqi_data.get(key) for key in ("aqi", "pm25", "pm10", "temperature")]
    return any(float(value or 0) > 0 for value in numeric)
