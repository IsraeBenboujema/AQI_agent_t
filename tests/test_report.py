from aqi_core.report import build_dose_markdown, build_gauge_html, build_report_markdown, markdown_to_pdf
from aqi_core.standards import estimate_inhaled_dose, us_aqi_band
from aqi_core.timing import best_window


def test_report_markdown_and_pdf(tmp_path, delhi_reading, user):
    dose = estimate_inhaled_dose(185, user.intensity_label, user.duration_minutes)
    md = build_report_markdown(delhi_reading, user, dose, best_window(delhi_reading.history, 60),
                               "Advice text", "model-x")
    for expected in ["NO2", "SO2", "O3", "2026-11-24 04:31", "Severe", "4:01 PM", "model-x",
                     "https://www.aqi.in/dashboard/india/delhi/new-delhi", "Advice text"]:
        assert expected in md, expected
    out = tmp_path / "r.pdf"
    markdown_to_pdf(md, str(out))
    assert out.stat().st_size > 1000


def test_report_rabat_omits_missing_temperature(rabat_reading, user):
    md = build_report_markdown(rabat_reading, user, estimate_inhaled_dose(5, user.intensity_label, 60),
                               None, "", "m")
    assert "Temperature" not in md


def test_dose_markdown(delhi_reading):
    md = build_dose_markdown(delhi_reading, estimate_inhaled_dose(185, "Vigorous (running, sports)", 60))
    assert "New Delhi" in md and "666" in md


def test_gauge_uses_band():
    html = build_gauge_html(260, us_aqi_band(260))
    assert "Severe" in html and "#a855f7" in html and "US AQI" in html
