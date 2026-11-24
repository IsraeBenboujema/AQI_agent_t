import pytest

from aqi_core.standards import (
    US_AQI_BANDS,
    estimate_inhaled_dose,
    share_of_who,
    to_ug_m3,
    us_aqi_band,
)


@pytest.mark.parametrize(
    "aqi,label",
    [(0, "Good"), (50, "Good"), (51, "Moderate"), (100, "Moderate"), (101, "Poor"),
     (150, "Poor"), (151, "Unhealthy"), (200, "Unhealthy"), (260, "Severe"),
     (300, "Severe"), (301, "Hazardous"), (999, "Hazardous")],
)
def test_band_boundaries(aqi, label):
    assert us_aqi_band(aqi).label == label


def test_band_colours_match_spec():
    assert [(b.label, b.colour) for b in US_AQI_BANDS] == [
        ("Good", "#22c55e"), ("Moderate", "#eab308"), ("Poor", "#f97316"),
        ("Unhealthy", "#ef4444"), ("Severe", "#a855f7"), ("Hazardous", "#9f1239"),
    ]


def test_fractional_aqi_between_bands_rounds_into_lower_band():
    assert us_aqi_band(50.4).label == "Good"


def test_share_of_who():
    assert share_of_who("pm25", 185) == 1233.3
    assert share_of_who("no2", 18) == round(18 * 46.01 / 24.45 / 25 * 100, 1)


def test_to_ug_m3_passthrough_for_particles():
    assert to_ug_m3("pm10", 259) == 259


def test_dose_unchanged():
    dose = estimate_inhaled_dose(185, "Moderate (brisk walk, cycling)", 60)
    assert dose["dose_ug"] == 333.0
