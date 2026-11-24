"""AQI Analysis Agent: Streamlit app (main UI).

Run with:  streamlit run ai_aqi_analysis_agent_streamlit.py
"""

import os
from datetime import datetime
from typing import Dict, Optional, Tuple

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from aqi_core.agent import DEFAULT_MODEL, HealthRecommendationAgent  # noqa: E402
from aqi_core.fetcher import AqiInClient, FetchFailed  # noqa: E402
from aqi_core.models import UserInput  # noqa: E402
from aqi_core.report import build_dose_markdown, build_report_markdown, write_report  # noqa: E402
from aqi_core.standards import (  # noqa: E402
    DEFAULT_ACTIVITY,
    DEFAULT_DURATION_MIN,
    activity_choices,
    estimate_inhaled_dose,
    us_aqi_band,
)
from aqi_core.timing import best_window, format_window  # noqa: E402
from aqi_ui.charts import calendar_figure, history_figure, stations_figure  # noqa: E402
from aqi_ui.theme import hero_html, landing_html, page_css, tiles_html  # noqa: E402

st.set_page_config(page_title="AQI Analysis Agent", page_icon="🌍", layout="wide")

CHART_CONFIG = {"displayModeBar": False}


@st.cache_resource(show_spinner=False)
def get_client(api_key: str) -> AqiInClient:
    """One client per key, kept across reruns so its 30-minute cache survives."""
    return AqiInClient.from_firecrawl(api_key)


def _key_field(label: str, env_name: str) -> str:
    from_env = os.getenv(env_name, "")
    if from_env:
        st.caption(f"✓ {label} loaded from .env")
        override = st.text_input(f"Use a different {label}", type="password", value="",
                                 placeholder="Leave empty to use the .env key")
        return override.strip() or from_env
    return st.text_input(label, type="password", value="").strip()


def sidebar() -> Tuple[UserInput, Dict[str, str], bool]:
    with st.sidebar:
        st.markdown("## Check the air")
        with st.form("analyze"):
            city = st.text_input("City", placeholder="e.g. Mumbai")
            state = st.text_input("State or region (optional)", placeholder="e.g. Maharashtra")
            country = st.text_input("Country", value="India")
            activity = st.text_input("What are you planning?", placeholder="e.g. evening run")
            conditions = st.text_input("Health conditions (optional)", placeholder="e.g. asthma")
            intensity = st.selectbox("How hard is it?", activity_choices(),
                                     index=activity_choices().index(DEFAULT_ACTIVITY))
            duration = st.slider("How long (minutes)?", 5, 240, DEFAULT_DURATION_MIN, step=5)
            submitted = st.form_submit_button("Check the air", type="primary", use_container_width=True)

        with st.expander("API keys and model"):
            keys = {
                "firecrawl": _key_field("Firecrawl API key", "FIRECRAWL_API_KEY"),
                "openrouter": _key_field("OpenRouter API key", "OPENROUTER_API_KEY"),
            }
            keys["model"] = st.text_input("OpenRouter model", value=DEFAULT_MODEL).strip() or DEFAULT_MODEL

    user = UserInput(
        city=city.strip(), state=state.strip(), country=country.strip(),
        medical_conditions=conditions.strip(), planned_activity=activity.strip() or "time outdoors",
        intensity_label=intensity, duration_minutes=int(duration),
    )
    return user, keys, submitted


def fetch(user: UserInput, keys: Dict[str, str]) -> Optional[Dict]:
    if not user.city:
        st.error("Enter a city to check.")
        return None
    if not keys["firecrawl"]:
        st.error("Add a Firecrawl API key under “API keys and model” in the sidebar.")
        return None
    with st.spinner(f"Reading aqi.in for {user.city}…"):
        try:
            result = get_client(keys["firecrawl"]).fetch(user.city, user.state, user.country)
        except FetchFailed as exc:
            st.error(str(exc))
            return None

    reading = result.reading
    return {
        "user": user,
        "reading": reading,
        "from_cache": result.from_cache,
        "window": best_window(reading.history, user.duration_minutes),
        "dose": estimate_inhaled_dose(reading.pollutants.get("pm25", 0), user.intensity_label,
                                      user.duration_minutes),
        "model": keys["model"],
        "advice": None,
        "report": None,
    }


def stream_advice(res: Dict, openrouter_key: str) -> str:
    if not openrouter_key:
        st.info("Add an OpenRouter API key under “API keys and model” to get personal advice.")
        return ""
    placeholder = st.empty()
    text = ""
    try:
        agent = HealthRecommendationAgent(openrouter_key, res["model"])
        with st.spinner("Writing advice for your plans…"):
            for delta in agent.stream_recommendations(res["reading"], res["user"], res["dose"], res["window"]):
                text += delta
                placeholder.markdown(text)
    except Exception as exc:  # rate limits, bad key, network: keep the data on screen
        st.error(f"AI advice unavailable: {exc}")
        return text
    if not text.strip():
        st.warning("The model returned an empty answer. Try again or pick another model.")
    return text


def render(res: Dict, openrouter_key: Optional[str]) -> None:
    reading, window, user = res["reading"], res["window"], res["user"]
    band = us_aqi_band(reading.aqi)

    st.markdown(page_css(band, reading.aqi), unsafe_allow_html=True)
    st.markdown(hero_html(reading, band), unsafe_allow_html=True)
    if res["from_cache"]:
        st.caption("Showing a reading fetched in the last 30 minutes.")
    st.markdown(tiles_html(reading), unsafe_allow_html=True)

    left, right = st.columns([3, 2], gap="medium")
    with left, st.container(border=True):
        st.markdown("### Last 24 hours")
        if window:
            st.caption(f"Based on the last 24 hours the air was cleanest {format_window(window)} "
                       f"(average AQI {window.mean_aqi:.0f}). A pattern, not a forecast.")
        else:
            st.caption("No clear cleaner daytime window in the last 24 hours.")
        if reading.history:
            st.plotly_chart(history_figure(reading.history, window), use_container_width=True,
                            config=CHART_CONFIG)
        else:
            st.caption("aqi.in has no 24-hour history for this location.")
    with right, st.container(border=True):
        st.markdown("### Neighbourhoods right now")
        figure = stations_figure(reading.stations)
        if figure:
            count = len(reading.stations)
            if count == 1:
                st.caption("The only monitoring station listed here.")
            elif count > 10:
                st.caption(f"Cleanest and most polluted of {count} monitoring stations.")
            else:
                st.caption(f"All {count} monitoring stations.")
            st.plotly_chart(figure, use_container_width=True, config=CHART_CONFIG)
        else:
            st.caption("aqi.in lists no individual stations here.")

    exposure, advice = st.columns([2, 3], gap="medium")
    with exposure, st.container(border=True):
        st.markdown("### Your exposure")
        st.markdown(build_dose_markdown(reading, res["dose"]), unsafe_allow_html=True)
    with advice, st.container(border=True):
        st.markdown(f"### Advice for your {user.planned_activity}")
        if res["advice"] is None:
            res["advice"] = stream_advice(res, openrouter_key or "")
        elif res["advice"]:
            st.markdown(res["advice"])
        else:
            st.caption("No AI advice for this check.")

    calendar = calendar_figure(reading.calendar)
    if calendar:
        with st.container(border=True):
            st.markdown(f"### {reading.calendar[0][0].year} at a glance")
            st.caption("Daily AQI from aqi.in. Each square is a day, coloured by its band.")
            st.plotly_chart(calendar, use_container_width=True, config=CHART_CONFIG)

    if res["report"] is None:
        markdown = build_report_markdown(reading, user, res["dose"], window, res["advice"], res["model"])
        with open(write_report(markdown, user.city), "rb") as handle:
            res["report"] = handle.read()
    st.download_button(
        "Download PDF report", data=res["report"], mime="application/pdf",
        file_name=f"aqi-report-{user.city.lower().replace(' ', '-')}-{datetime.now():%Y%m%d-%H%M}.pdf",
    )
    st.caption("Data from aqi.in via Firecrawl. Estimates are informational, not medical advice.")


def main() -> None:
    st.markdown(page_css(None), unsafe_allow_html=True)
    user, keys, submitted = sidebar()

    if submitted:
        res = fetch(user, keys)
        if res:
            st.session_state.result = res
            render(res, keys["openrouter"])
        return

    stored = st.session_state.get("result")
    if stored:
        render(stored, None)
    else:
        st.markdown(landing_html(), unsafe_allow_html=True)


main()
