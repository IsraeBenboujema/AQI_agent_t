from typing import Dict, Iterator, Optional
from dataclasses import dataclass
from pydantic import BaseModel, Field
from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.models.openai import OpenAIChat
from firecrawl import FirecrawlApp
import streamlit as st
import os
import time
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

from aqi_core.standards import (
    DEFAULT_ACTIVITY,
    DEFAULT_DURATION_MIN,
    WHO_PM25_24H,
    activity_choices,
    categorize_aqi,
    estimate_inhaled_dose,
    guideline_bars,
    has_usable_data,
)
from aqi_history import get_history, init_db, save_reading
from aqi_report import (
    build_dose_markdown,
    build_gauge_html,
    build_report_markdown,
    write_report,
)

load_dotenv()

# OpenRouter is OpenAI-compatible, so we reuse agno's OpenAIChat with a custom base_url
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
DEFAULT_FIRECRAWL_KEY = os.getenv("FIRECRAWL_API_KEY", "")
DEFAULT_OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")


class AQIResponse(BaseModel):
    success: bool
    data: Dict[str, float]
    status: str
    expiresAt: str

class ExtractSchema(BaseModel):
    aqi: float = Field(description="Air Quality Index")
    temperature: float = Field(description="Temperature in degrees Celsius")
    humidity: float = Field(description="Humidity percentage")
    wind_speed: float = Field(description="Wind speed in kilometers per hour")
    pm25: float = Field(description="Particulate Matter 2.5 micrometers")
    pm10: float = Field(description="Particulate Matter 10 micrometers")
    co: float = Field(description="Carbon Monoxide level")

@dataclass
class UserInput:
    city: str
    state: str
    country: str
    medical_conditions: Optional[str]
    planned_activity: str
    intensity_label: str = DEFAULT_ACTIVITY
    duration_minutes: int = DEFAULT_DURATION_MIN

class AQIAnalyzer:
    
    def __init__(self, firecrawl_key: str) -> None:
        self.firecrawl = FirecrawlApp(api_key=firecrawl_key)
    
    def _format_url(self, country: str, state: str, city: str) -> str:
        """Format URL based on location, handling cases with and without state"""
        country_clean = country.lower().replace(' ', '-')
        city_clean = city.lower().replace(' ', '-')
        
        if not state or state.lower() == 'none':
            return f"https://www.aqi.in/dashboard/{country_clean}/{city_clean}"
        
        state_clean = state.lower().replace(' ', '-')
        return f"https://www.aqi.in/dashboard/{country_clean}/{state_clean}/{city_clean}"
    
    def fetch_aqi_data(self, city: str, state: str, country: str) -> Dict[str, float]:
        """Fetch AQI data using Firecrawl"""
        try:
            url = self._format_url(country, state, city)
            st.caption(f"Accessing URL: {url}")
            
            response = self.firecrawl.extract(
                urls=[f"{url}/*"],
                params={
                    'prompt': 'Extract the current real-time AQI, temperature, humidity, wind speed, PM2.5, PM10, and CO levels from the page. Also extract the timestamp of the data.',
                    'schema': ExtractSchema.model_json_schema()
                }
            )
            
            aqi_response = AQIResponse(**response)
            if not aqi_response.success:
                raise ValueError(f"Failed to fetch AQI data: {aqi_response.status}")
            
            return aqi_response.data
            
        except Exception as e:
            st.error(f"Error fetching AQI data: {str(e)}")
            return {
                'aqi': 0,
                'temperature': 0,
                'humidity': 0,
                'wind_speed': 0,
                'pm25': 0,
                'pm10': 0,
                'co': 0
            }

class HealthRecommendationAgent:
    
    def __init__(self, openrouter_key: str, model_id: str = DEFAULT_OPENROUTER_MODEL) -> None:
        self.model_id = model_id
        self.agent = Agent(
            model=OpenAIChat(
                id=model_id,
                name="Health Recommendation Agent",
                api_key=openrouter_key,
                base_url=OPENROUTER_BASE_URL
            )
        )

    def get_recommendations(
        self,
        aqi_data: Dict[str, float],
        user_input: UserInput,
        dose: Optional[Dict[str, float]] = None
    ) -> str:
        prompt = self._create_prompt(aqi_data, user_input, dose)
        response: RunOutput = self.agent.run(prompt)
        return response.content

    def stream_recommendations(
        self,
        aqi_data: Dict[str, float],
        user_input: UserInput,
        dose: Optional[Dict[str, float]] = None
    ) -> Iterator[str]:
        """Yield text chunks as the model writes; falls back to one shot if streaming is empty."""
        prompt = self._create_prompt(aqi_data, user_input, dose)
        accumulated = ""

        try:
            for event in self.agent.run(prompt, stream=True):
                content = getattr(event, "content", None)
                if not content:
                    continue
                delta = content[len(accumulated):] if content.startswith(accumulated) else content
                if delta:
                    accumulated += delta
                    yield delta
        except Exception:
            if accumulated.strip():
                raise

        if not accumulated.strip():
            fallback: RunOutput = self.agent.run(prompt)
            text = getattr(fallback, "content", "") or ""
            if text:
                yield text

    def _create_prompt(
        self,
        aqi_data: Dict[str, float],
        user_input: UserInput,
        dose: Optional[Dict[str, float]] = None
    ) -> str:
        dose_lines = ""
        if dose:
            dose_lines = f"""
        Exposure estimate for the planned activity:
        - Activity intensity: {dose.get('activity')}
        - Duration: {int(dose.get('minutes', 0))} minutes
        - Breathing rate: {dose.get('ventilation_l_min', 0):g} L/min
        - PM2.5 inhaled: {dose.get('dose_ug', 0):g} µg (about {dose.get('cigarettes', 0):g} cigarette-equivalents)
        - Share of a WHO 24h guideline day: {dose.get('who_day_fraction', 0):g}%
        """

        return f"""
        Based on the following air quality conditions in {user_input.city}, {user_input.state}, {user_input.country}:
        - Overall AQI: {aqi_data['aqi']} (CPCB India scale)
        - PM2.5 Level: {aqi_data['pm25']} µg/m³
        - PM10 Level: {aqi_data['pm10']} µg/m³
        - CO Level: {aqi_data['co']} ppb
        
        Weather conditions:
        - Temperature: {aqi_data['temperature']}°C
        - Humidity: {aqi_data['humidity']}%
        - Wind Speed: {aqi_data['wind_speed']} km/h
        {dose_lines}
        User's Context:
        - Medical Conditions: {user_input.medical_conditions or 'None'}
        - Planned Activity: {user_input.planned_activity}
        (planned duration: {user_input.duration_minutes} minutes at "{user_input.intensity_label}" intensity)
        
        Be concise and concrete. Use the exposure estimate above rather than inventing numbers.
        **Comprehensive Health Recommendations:**
        1. **Impact of Current Air Quality on Health:**
        2. **Necessary Safety Precautions for Planned Activity:**
        3. **Advisability of Planned Activity:**
        4. **Best Time to Conduct the Activity:**
        """


def _location_label(city: str, state: str, country: str) -> str:
    return ", ".join(part.strip() for part in (city, state, country) if part and part.strip())


def initialize_session_state():
    if 'api_keys' not in st.session_state:
        st.session_state.api_keys = {
            'firecrawl': DEFAULT_FIRECRAWL_KEY,
            'openrouter': DEFAULT_OPENROUTER_KEY,
            'model': DEFAULT_OPENROUTER_MODEL
        }
    if 'result' not in st.session_state:
        st.session_state.result = None

def setup_page():
    st.set_page_config(
        page_title="AQI Analysis Agent",
        page_icon="🌍",
        layout="wide"
    )
    
    st.title("🌍 AQI Analysis Agent")
    st.info("Get personalized health recommendations based on air quality conditions.")

def render_sidebar():
    """Render sidebar with API configuration"""
    with st.sidebar:
        st.header("🔑 API Configuration")
        
        new_firecrawl_key = st.text_input(
            "Firecrawl API Key",
            type="password",
            value=st.session_state.api_keys['firecrawl'],
            help="Enter your Firecrawl API key"
        )
        new_openrouter_key = st.text_input(
            "OpenRouter API Key",
            type="password",
            value=st.session_state.api_keys['openrouter'],
            help="Enter your OpenRouter API key (sk-or-v1-...)"
        )
        new_model = st.text_input(
            "Model (OpenRouter model ID)",
            value=st.session_state.api_keys['model'],
            help="e.g., openai/gpt-4o-mini, anthropic/claude-3.5-sonnet, google/gemini-2.0-flash"
        )
        
        if (new_firecrawl_key and new_openrouter_key and
            (new_firecrawl_key != st.session_state.api_keys['firecrawl'] or 
             new_openrouter_key != st.session_state.api_keys['openrouter'] or
             new_model != st.session_state.api_keys['model'])):
            st.session_state.api_keys.update({
                'firecrawl': new_firecrawl_key,
                'openrouter': new_openrouter_key,
                'model': new_model or DEFAULT_OPENROUTER_MODEL
            })
            st.success("✅ API configuration updated!")

def render_main_content():
    st.header("📍 Location Details")
    col1, col2 = st.columns(2)
    
    with col1:
        city = st.text_input("City", placeholder="e.g., Mumbai")
        state = st.text_input("State", placeholder="If it's a Union Territory or a city in the US, leave it blank")
        country = st.text_input("Country", value="India", placeholder="United States")
    
    with col2:
        st.header("👤 Personal Details")
        medical_conditions = st.text_area(
            "Medical Conditions (optional)",
            placeholder="e.g., asthma, allergies"
        )
        planned_activity = st.text_area(
            "Planned Activity",
            placeholder="e.g., morning jog"
        )
        intensity_label = st.selectbox(
            "Activity intensity (for exposure estimate)",
            options=activity_choices(),
            index=activity_choices().index(DEFAULT_ACTIVITY)
        )
        duration_minutes = st.slider(
            "Duration (minutes)",
            min_value=5,
            max_value=240,
            value=DEFAULT_DURATION_MIN,
            step=5
        )
    
    return (
        UserInput(
            city=city,
            state=state,
            country=country,
            medical_conditions=medical_conditions,
            planned_activity=planned_activity,
            intensity_label=intensity_label,
            duration_minutes=duration_minutes
        ),
        intensity_label,
        duration_minutes
    )


def run_analysis(
    user_input: UserInput,
    intensity_label: str,
    duration_minutes: int,
    api_keys: Dict[str, str]
) -> None:
    """Fetch data, estimate dose, draw charts and stream the recommendations."""
    started = time.time()
    location = _location_label(user_input.city, user_input.state, user_input.country)

    with st.spinner("🔄 Fetching air quality data..."):
        aqi_analyzer = AQIAnalyzer(firecrawl_key=api_keys['firecrawl'])
        aqi_data = aqi_analyzer.fetch_aqi_data(
            city=user_input.city,
            state=user_input.state,
            country=user_input.country
        )

    if not has_usable_data(aqi_data):
        st.error(
            "No usable air quality data was returned for this location. "
            "Check the city/state/country spelling or try another city."
        )
        st.session_state.result = None
        return

    category = categorize_aqi(aqi_data['aqi'])
    dose = estimate_inhaled_dose(
        pm25_ug_m3=aqi_data['pm25'],
        activity_label=intensity_label,
        minutes=duration_minutes
    )

    stored = save_reading(user_input.city, user_input.state, user_input.country, aqi_data)
    history = get_history(user_input.city, user_input.state, user_input.country, days=7)
    bars = pd.DataFrame(guideline_bars(aqi_data))

    st.markdown(build_gauge_html(aqi_data['aqi'], category), unsafe_allow_html=True)

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.subheader("📈 Reading vs guideline")
        st.bar_chart(bars.set_index("metric")["share_of_limit"], height=260)
        st.caption("100% = WHO 24h guideline for PM2.5/PM10, or the top of the CPCB 'Satisfactory' AQI band.")
    with chart_col2:
        st.subheader("📉 AQI trend (last 7 days)")
        if len(history) >= 2:
            st.line_chart(history.set_index("observed_at")["aqi"], height=260)
            st.caption(f"{len(history)} readings on file.")
        else:
            st.caption("Not enough history yet — this chart fills in as you check the same city over time.")

    st.markdown(build_dose_markdown(aqi_data, dose, location))

    with st.expander("📦 Raw AQI data", expanded=False):
        st.json({
            "location": location,
            "data": aqi_data,
            "dq_category": category,
            "dose_estimate": dose,
        })
        if not stored and history is not None:
            st.caption("Reused a reading saved in the last 45 minutes.")

    st.subheader("🏥 Health Recommendations")
    buffer = ""
    try:
        health_agent = HealthRecommendationAgent(
            openrouter_key=api_keys['openrouter'],
            model_id=api_keys.get('model') or DEFAULT_OPENROUTER_MODEL
        )
        placeholder = st.empty()
        for delta in health_agent.stream_recommendations(aqi_data, user_input, dose):
            buffer += delta
            placeholder.markdown(buffer)
    except Exception as exc:
        st.error(f"❌ LLM error: {str(exc)}")
        if buffer:
            st.markdown(buffer)
        st.session_state.result = None
        return

    report = build_report_markdown(
        location=location,
        aqi_data=aqi_data,
        category=category,
        dose=dose,
        recommendations=buffer,
        observed_at=datetime.now(),
        model_name=api_keys.get('model') or DEFAULT_OPENROUTER_MODEL,
    )
    report_path = write_report(report, user_input.city)

    st.session_state.result = {
        "location": location,
        "gauge_html": build_gauge_html(aqi_data['aqi'], category),
        "aqi_data": aqi_data,
        "category": category,
        "dose": dose,
        "dose_md": build_dose_markdown(aqi_data, dose, location),
        "bars": bars,
        "history": history,
        "recommendations": buffer,
        "report": report,
        "report_path": report_path,
        "elapsed": time.time() - started,
    }


def render_stored_results() -> None:
    """Re-render the last analysis after a rerun (e.g. clicking download)."""
    result = st.session_state.get("result")
    if not result:
        return

    st.markdown(result["gauge_html"], unsafe_allow_html=True)

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.subheader("📈 Reading vs guideline")
        st.bar_chart(result["bars"].set_index("metric")["share_of_limit"], height=260)
    with chart_col2:
        st.subheader("📉 AQI trend (last 7 days)")
        history = result["history"]
        if len(history) >= 2:
            st.line_chart(history.set_index("observed_at")["aqi"], height=260)
        else:
            st.caption("Not enough history yet for a trend.")

    st.markdown(result["dose_md"])
    st.subheader("🏥 Health Recommendations")
    st.markdown(result["recommendations"])
    st.caption(f"Completed in {result['elapsed']:.1f}s")


def main():
    """Main application entry point"""
    setup_page()
    init_db()
    initialize_session_state()
    render_sidebar()
    user_input, intensity_label, duration_minutes = render_main_content()

    just_analyzed = False
    if st.button("🔍 Analyze & Get Recommendations"):
        if not all([user_input.city, user_input.planned_activity]):
            st.error("Please fill in all required fields (state and medical conditions are optional)")
        elif not (st.session_state.api_keys.get('firecrawl') and st.session_state.api_keys.get('openrouter')):
            st.error("Please provide both the Firecrawl and OpenRouter API keys in the sidebar")
        else:
            run_analysis(user_input, intensity_label, duration_minutes, st.session_state.api_keys)
            just_analyzed = True

    if not just_analyzed:
        render_stored_results()

    result = st.session_state.get("result")
    if result:
        st.download_button(
            "💾 Download report",
            data=open(result["report_path"], "rb").read(),
            file_name=f"aqi_report_{user_input.city or 'location'}_{datetime.now():%Y%m%d-%H%M}.pdf",
            mime="application/pdf"
        )

if __name__ == "__main__":
    main()
