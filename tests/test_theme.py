from dataclasses import replace

from aqi_core.standards import us_aqi_band
from aqi_ui.theme import hero_html, landing_html, page_css, tiles_html


def test_hero_delhi(delhi_reading):
    html = hero_html(delhi_reading, us_aqi_band(260))
    assert "260" in html
    assert "Severe" in html
    assert "#41" in html
    assert "#a855f7" in html
    assert "04:31" in html
    assert 'href="https://www.aqi.in/dashboard/india/delhi/new-delhi"' in html


def test_hero_without_rank(rabat_reading):
    html = hero_html(rabat_reading, us_aqi_band(25))
    assert "worldwide" not in html and "Good" in html


def test_hero_escapes_page_text(delhi_reading):
    reading = replace(delhi_reading, place="<script>x</script>")
    assert "<script>" not in hero_html(reading, us_aqi_band(reading.aqi))


def test_tiles_delhi_all_pollutants(delhi_reading):
    html = tiles_html(delhi_reading)
    for name in ["PM2.5", "PM10", "CO", "NO₂", "SO₂", "O₃"]:
        assert name in html
    assert "1233% of WHO limit" in html
    assert "15°C" in html


def test_tiles_rabat_has_no_temperature(rabat_reading):
    html = tiles_html(rabat_reading)
    assert "°C" not in html and "PM2.5" in html and "80%" in html


def test_page_css_tints_with_band():
    assert "#a855f7" in page_css(us_aqi_band(260))
    assert "<style>" in page_css(None)


def test_haze_thicker_for_worse_air():
    import re
    def haze(aqi):
        return float(re.search(r"--haze:\s*([\d.]+)", page_css(us_aqi_band(aqi), aqi)).group(1))
    assert haze(25) < haze(260)


def test_landing_mentions_examples():
    assert "Delhi" in landing_html()


def test_layout_containers_keep_streamlit_positioning():
    """Overriding position on Streamlit's app or sidebar containers makes them grow past the window, so nothing scrolls."""
    import re
    css = page_css(None)
    for rule in re.findall(r"([^{}]*)\{([^{}]*)\}", css):
        selector, body = rule
        if ('stSidebar"]' in selector or 'stAppViewContainer"]' in selector) and "position" in body:
            raise AssertionError(f"sidebar rule sets position: {selector.strip()}")


def test_landing_examples_name_their_country():
    assert "New York (United States)" in landing_html()
