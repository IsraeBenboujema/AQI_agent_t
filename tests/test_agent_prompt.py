import pytest

from aqi_core.agent import HealthRecommendationAgent, build_prompt
from aqi_core.standards import estimate_inhaled_dose
from aqi_core.timing import best_window


def test_prompt_contents(delhi_reading, user):
    dose = estimate_inhaled_dose(185, user.intensity_label, 60)
    prompt = build_prompt(delhi_reading, user, dose, best_window(delhi_reading.history, 60))
    for expected in [
        "New Delhi", "260", "Severe", "US AQI", "NO2: 18 ppb", "PM2.5: 185 µg/m³", "4:01 PM–5:01 PM",
        "https://www.aqi.in/dashboard/india/delhi/new-delhi", "asthma", "evening run",
        "Based on the last 24 hours the air was cleanest",
        "1. **Impact of Current Air Quality on Health:**",
        "4. **Best Time to Conduct the Activity:**",
    ]:
        assert expected in prompt, expected


def test_prompt_rabat_without_temperature_or_window(rabat_reading, user):
    prompt = build_prompt(rabat_reading, user, {}, None)
    assert "Temperature" not in prompt
    assert "No clear cleaner window in the last 24 hours" in prompt
    assert "Humidity: 80%" in prompt


def test_stream_error_propagates(monkeypatch, delhi_reading, user):
    agent = HealthRecommendationAgent("k", "m", "http://localhost:9")

    def boom(*args, **kwargs):
        raise RuntimeError("429 rate limited")

    monkeypatch.setattr(agent.agent, "run", boom)
    with pytest.raises(RuntimeError, match="429"):
        list(agent.stream_recommendations(delhi_reading, user, {}, None))


def test_real_agno_error_raises_instead_of_becoming_advice(delhi_reading, user):
    """agno swallows model errors and yields them as content; they must surface as exceptions."""
    agent = HealthRecommendationAgent("sk-bogus", "some/model", "http://127.0.0.1:9")  # closed port
    agent.agent.model.max_retries = 0
    with pytest.raises(RuntimeError):
        list(agent.stream_recommendations(delhi_reading, user, {}, None))
