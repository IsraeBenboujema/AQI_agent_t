"""AQI bands, WHO guideline limits, activity profiles and inhalation-dose maths.

Free of UI/LLM dependencies so every app shares it, and so the numbers stay
deterministic instead of being guessed by a model.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

# --- AQI bands --------------------------------------------------------------
# aqi.in reports the US EPA AQI number but names the bands its own way.


@dataclass(frozen=True)
class Band:
    label: str
    colour: str
    low: int
    high: Optional[int]
    advice: str


US_AQI_BANDS: List[Band] = [
    Band("Good", "#22c55e", 0, 50, "Air quality is good. Enjoy outdoor activities."),
    Band("Moderate", "#eab308", 51, 100,
         "Acceptable. Unusually sensitive people should ease off long, hard exertion."),
    Band("Poor", "#f97316", 101, 150,
         "Sensitive groups (asthma, heart or lung conditions, children, elderly) should limit long outdoor exertion."),
    Band("Unhealthy", "#ef4444", 151, 200,
         "Everyone may feel effects. Cut back on long or intense outdoor activity."),
    Band("Severe", "#a855f7", 201, 300,
         "Health alert. Avoid outdoor exertion; wear an N95 mask if you must go out."),
    Band("Hazardous", "#9f1239", 301, None,
         "Emergency conditions. Stay indoors with windows closed and a purifier on."),
]


def us_aqi_band(aqi: float) -> Band:
    """Map an AQI number to its band; values above 300 are Hazardous."""
    try:
        value = round(float(aqi))
    except (TypeError, ValueError):
        value = 0
    for band in US_AQI_BANDS:
        if band.high is None or value <= band.high:
            return band
    return US_AQI_BANDS[-1]


# --- WHO 2021 guideline limits ---------------------------------------------
WHO_PM25_24H = 15.0
WHO_LIMITS_UG_M3: Dict[str, float] = {
    "pm25": 15, "pm10": 45, "no2": 25, "so2": 40, "o3": 100, "co": 4000,
}
# aqi.in reports gases in ppb; convert with the molar volume at 25 °C.
MOLECULAR_WEIGHT = {"co": 28.01, "no2": 46.01, "so2": 64.07, "o3": 48.00}
MOLAR_VOLUME_L = 24.45


def to_ug_m3(key: str, value: float) -> float:
    """Particles are already µg/m³; gases (ppb) are converted."""
    weight = MOLECULAR_WEIGHT.get(key)
    return float(value) * weight / MOLAR_VOLUME_L if weight else float(value)


def share_of_who(key: str, value: float) -> float:
    """Reading as a percentage of its WHO guideline limit."""
    return round(to_ug_m3(key, value) / WHO_LIMITS_UG_M3[key] * 100.0, 1)


# --- Inhaled dose -----------------------------------------------------------
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
