"""HTML/CSS builders for the dark "weather app" look.

The page background glows in the colour of the current AQI band, and a haze layer
thickens as the air gets worse: a clean day looks crisp, a severe day looks smoggy.
"""

from html import escape
from typing import Optional

from aqi_core.models import POLLUTANT_KEYS, POLLUTANT_UNITS, AqiReading
from aqi_core.standards import Band, share_of_who

NIGHT = "#0e1220"
INK = "#e8ecf4"
MUTED = "#9aa3b5"
NEUTRAL_GLOW = "#3b4a6b"

DISPLAY_NAMES = {"pm25": "PM2.5", "pm10": "PM10", "co": "CO", "no2": "NO₂", "so2": "SO₂", "o3": "O₃"}
METER_GREEN, METER_AMBER, METER_RED = "#4ade80", "#fbbf24", "#f87171"


def _num(value: float) -> str:
    return f"{value:g}"


def haze_level(aqi: Optional[float]) -> float:
    if aqi is None:
        return 0.0
    return round(0.06 + 0.5 * min(max(float(aqi), 0.0), 400.0) / 400.0, 3)


def page_css(band: Optional[Band], aqi: Optional[float] = None) -> str:
    glow = band.colour if band else NEUTRAL_GLOW
    return f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,600;12..96,800&family=Atkinson+Hyperlegible:wght@400;700&display=swap');
:root {{ --glow: {glow}; --haze: {haze_level(aqi)}; --ink: {INK}; --muted: {MUTED}; }}
.stApp {{
  background: radial-gradient(ellipse 90% 60% at 25% -10%, {glow}73 0%, {glow}1f 45%, transparent 75%), {NIGHT};
  color: var(--ink);
  font-family: 'Atkinson Hyperlegible', system-ui, sans-serif;
}}
.stApp::before {{
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  opacity: var(--haze);
  background:
    radial-gradient(ellipse 60% 30% at 70% 20%, {glow}55, transparent 70%),
    radial-gradient(ellipse 80% 40% at 20% 70%, #c9b89a40, transparent 70%),
    repeating-radial-gradient(circle at 50% 50%, #ffffff08 0 1px, transparent 1px 3px);
  filter: blur(2px);
}}
[data-testid="stAppViewContainer"] {{ z-index: 1; }}  /* already positioned by Streamlit; don't override */
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] > div:first-child {{ background: #0b0f1bcc; backdrop-filter: blur(10px); }}
.stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea, .stApp td, .stApp th,
.stApp button, .stApp [data-testid="stMarkdownContainer"], .stApp [data-testid="stCaptionContainer"] {{
  font-family: 'Atkinson Hyperlegible', system-ui, sans-serif !important;
}}
.stApp h1, .stApp h2, .stApp h3, .stApp h1 *, .stApp h2 *, .stApp h3 *, .hero-num, .tile-value {{
  font-family: 'Bricolage Grotesque', system-ui, sans-serif !important;
}}
h2, h3 {{ font-weight: 600; letter-spacing: -0.01em; }}
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{
  background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.10) !important;
  border-radius: 18px; backdrop-filter: blur(8px);
}}
.hero {{ padding: 8px 0 18px; max-width: 920px; }}
.hero-line {{ font-size: 1.25rem; color: var(--ink); margin: 0 0 4px; }}
.hero-row {{ display: flex; align-items: flex-end; gap: 18px; flex-wrap: wrap; }}
.hero-num {{ font-size: clamp(5rem, 14vw, 9rem); font-weight: 800; line-height: .9; letter-spacing: -0.04em; }}
.hero-band {{ font-size: 1.6rem; font-weight: 700; padding-bottom: 14px; }}
.hero-band small {{ display: block; font-size: .85rem; font-weight: 400; color: var(--muted); }}
.hero-rank {{ display: inline-block; margin: 10px 0 6px; padding: 4px 12px; border-radius: 999px;
  background: rgba(255,255,255,.08); font-size: .95rem; }}
.hero-meta {{ color: var(--muted); font-size: .9rem; margin: 6px 0 0; }}
.hero-meta a {{ color: var(--muted); }}
.hero-advice {{ margin: 12px 0 0; max-width: 62ch; line-height: 1.55; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin: 6px 0 10px; }}
.tile {{ background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.09); border-radius: 14px; padding: 12px 14px; }}
.tile-name {{ color: var(--muted); font-size: .9rem; }}
.tile-value {{ font-size: 1.7rem; font-weight: 600; line-height: 1.2; }}
.tile-value small {{ font-family: 'Atkinson Hyperlegible', sans-serif; font-size: .8rem; font-weight: 400; color: var(--muted); margin-left: 3px; }}
.meter {{ height: 5px; border-radius: 99px; background: rgba(255,255,255,.08); margin: 8px 0 5px; overflow: hidden; }}
.meter span {{ display: block; height: 100%; border-radius: 99px; }}
.tile-note {{ font-size: .8rem; color: var(--muted); }}
.weather {{ display: flex; gap: 22px; flex-wrap: wrap; color: var(--muted); font-size: .95rem; margin: 4px 0 18px; }}
.weather b {{ color: var(--ink); font-weight: 700; }}
.landing {{ max-width: 640px; padding: 12vh 0 0; }}
.landing h1 {{ font-size: clamp(2.6rem, 6vw, 4.2rem); font-weight: 800; line-height: 1; letter-spacing: -0.03em; margin: 0 0 14px; }}
.landing p {{ font-size: 1.15rem; line-height: 1.6; color: var(--muted); }}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; animation: none !important; }} }}
</style>"""


def hero_html(reading: AqiReading, band: Band) -> str:
    place = escape(reading.place or "this location")
    rank = (f'<div class="hero-rank">#{reading.world_rank} most polluted city worldwide right now</div>'
            if reading.world_rank else "")
    updated = (f"Updated {reading.updated_at:%H:%M} local time, from "
               if reading.updated_at else "From ")
    url = escape(reading.url, quote=True)
    return f"""
<div class="hero">
  <p class="hero-line">The air in {place} is {escape(band.label.lower())} right now.</p>
  <div class="hero-row">
    <div class="hero-num" style="color:{band.colour}">{reading.aqi}</div>
    <div class="hero-band" style="color:{band.colour}">{escape(band.label)}<small>US AQI</small></div>
  </div>
  {rank}
  <p class="hero-meta">{updated}<a href="{url}" target="_blank" rel="noopener">aqi.in</a></p>
  <p class="hero-advice">{escape(band.advice)}</p>
</div>"""


def _meter_colour(share: float) -> str:
    if share <= 100:
        return METER_GREEN
    return METER_AMBER if share <= 200 else METER_RED


def tiles_html(reading: AqiReading) -> str:
    tiles = []
    for key in POLLUTANT_KEYS:
        if key not in reading.pollutants:
            continue
        value = reading.pollutants[key]
        share = share_of_who(key, value)
        width = min(share, 400.0) / 400.0 * 100.0
        tiles.append(
            f'<div class="tile"><div class="tile-name">{DISPLAY_NAMES[key]}</div>'
            f'<div class="tile-value">{_num(value)}<small>{POLLUTANT_UNITS[key]}</small></div>'
            f'<div class="meter"><span style="width:{width:.0f}%;background:{_meter_colour(share)}"></span></div>'
            f'<div class="tile-note">{share:.0f}% of WHO limit</div></div>'
        )

    weather = []
    if reading.temperature_c is not None:
        weather.append(f"<span><b>{_num(reading.temperature_c)}°C</b></span>")
    if reading.humidity_pct is not None:
        weather.append(f"<span>Humidity <b>{_num(reading.humidity_pct)}%</b></span>")
    if reading.wind_kmh is not None:
        weather.append(f"<span>Wind <b>{_num(reading.wind_kmh)} km/h</b></span>")
    if reading.uv_index is not None:
        weather.append(f"<span>UV index <b>{_num(reading.uv_index)}</b></span>")

    weather_row = f'<div class="weather">{"".join(weather)}</div>' if weather else ""
    return f'<div class="tiles">{"".join(tiles)}</div>{weather_row}'


def landing_html() -> str:
    return """
<div class="landing">
  <h1>What are you breathing today?</h1>
  <p>Enter a city and what you plan to do outside. You'll get live readings from aqi.in,
  the cleanest hours of the day, the cleanest neighbourhoods nearby, and advice for your plans.</p>
  <p>Try Delhi, Mumbai, New York or Rabat.</p>
</div>"""
