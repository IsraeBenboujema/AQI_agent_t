from typing import Dict, Iterator, Optional
from dataclasses import dataclass
from pydantic import BaseModel, Field
from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.models.openai import OpenAIChat
from firecrawl import FirecrawlApp
import gradio as gr
import json
import os
import time
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

from aqi_standards import (
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
    REPORTS_DIR,
    build_dose_markdown,
    build_gauge_html,
    build_report_link_html,
    build_report_markdown,
    write_report,
)

load_dotenv()

# OpenRouter is OpenAI-compatible, so we reuse agno's OpenAIChat with a custom base_url
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
DEFAULT_FIRECRAWL_KEY = os.getenv("FIRECRAWL_API_KEY", "")
DEFAULT_OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")

DATA_WARNING = f"""⚠️ Data caveats
- Scraped via Firecrawl from aqi.in; values may be cached or lag real time.
- WHO 24h PM2.5 guideline: {WHO_PM25_24H:g} µg/m³. AQI shown on the CPCB (India) scale.
- Dose estimates are informational only, not medical advice."""


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
    
    def fetch_aqi_data(self, city: str, state: str, country: str) -> tuple[Dict[str, float], str]:
        """Fetch AQI data using Firecrawl"""
        try:
            url = self._format_url(country, state, city)
            info_msg = f"Accessing URL: {url}"
            
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
            
            return aqi_response.data, info_msg
            
        except Exception as e:
            error_msg = f"Error fetching AQI data: {str(e)}"
            return {
                'aqi': 0,
                'temperature': 0,
                'humidity': 0,
                'wind_speed': 0,
                'pm25': 0,
                'pm10': 0,
                'co': 0
            }, error_msg

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
                # agno may emit deltas or the cumulative string depending on version
                delta = content[len(accumulated):] if content.startswith(accumulated) else content
                if delta:
                    accumulated += delta
                    yield delta
        except Exception:
            if accumulated.strip():
                raise
            # Streaming unsupported or failed before any text: do a normal call

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


def _aqi_display(aqi_data: Dict[str, float]) -> Dict[str, str]:
    return {
        "Air Quality Index (AQI)": aqi_data['aqi'],
        "PM2.5": f"{aqi_data['pm25']} µg/m³",
        "PM10": f"{aqi_data['pm10']} µg/m³",
        "Carbon Monoxide (CO)": f"{aqi_data['co']} ppb",
        "Temperature": f"{aqi_data['temperature']}°C",
        "Humidity": f"{aqi_data['humidity']}%",
        "Wind Speed": f"{aqi_data['wind_speed']} km/h"
    }


def analyze_conditions_stream(
    city: str,
    state: str,
    country: str,
    medical_conditions: str,
    planned_activity: str,
    intensity_label: str,
    duration_minutes: int,
    firecrawl_key: str,
    openrouter_key: str,
    model_id: str = DEFAULT_OPENROUTER_MODEL
):
    """Fetch data, estimate dose, draw charts, then stream the LLM advice."""
    started = time.time()
    location = _location_label(city, state, country)
    model_id = (model_id or DEFAULT_OPENROUTER_MODEL).strip()

    yield ("", {}, None, None, "", "", f"🔎 Fetching air quality data for {location}...", DATA_WARNING, "")

    if not (firecrawl_key or "").strip():
        yield ("", {}, None, None, "", "Analysis stopped: Firecrawl API key is missing.",
               "❌ Add your Firecrawl API key under API Configuration.", DATA_WARNING, "")
        return
    if not (openrouter_key or "").strip():
        yield ("", {}, None, None, "", "Analysis stopped: OpenRouter API key is missing.",
               "❌ Add your OpenRouter API key under API Configuration.", DATA_WARNING, "")
        return

    try:
        aqi_analyzer = AQIAnalyzer(firecrawl_key=firecrawl_key.strip())
        aqi_data, info_msg = aqi_analyzer.fetch_aqi_data(city=city, state=state, country=country)
    except Exception as exc:
        yield ("", {}, None, None, "", f"Analysis failed: {exc}", str(exc), DATA_WARNING, "")
        return

    if not has_usable_data(aqi_data):
        message = (
            "No usable air quality data was returned for this location. "
            "Check the spelling of the city/state/country, or try another city."
        )
        yield ("", {}, None, None, "", message, f"{info_msg} | {message}", DATA_WARNING, "")
        return

    category = categorize_aqi(aqi_data['aqi'])
    user_input = UserInput(
        city=city,
        state=state,
        country=country,
        medical_conditions=medical_conditions,
        planned_activity=planned_activity,
        intensity_label=intensity_label,
        duration_minutes=int(duration_minutes or 0),
    )
    dose = estimate_inhaled_dose(
        pm25_ug_m3=aqi_data['pm25'],
        activity_label=intensity_label,
        minutes=int(duration_minutes or 0),
    )

    stored = save_reading(city, state, country, aqi_data)
    history = get_history(city, state, country, days=7)

    gauge = build_gauge_html(aqi_data['aqi'], category)
    bars = pd.DataFrame(guideline_bars(aqi_data))
    trend = history if len(history) else None
    dose_md = build_dose_markdown(aqi_data, dose, location)
    aqi_json = _aqi_display(aqi_data)

    history_note = f"{len(history)} reading(s) on file" + (" (trend needs more visits)" if len(history) < 2 else "")
    fetched = time.time() - started
    status = f"{info_msg} | fetched in {fetched:.1f}s | {history_note}"
    if not stored:
        status += " | reused a recent reading (saved once per 45 min)"

    yield (gauge, aqi_json, bars, trend, dose_md, "⏳ Generating recommendations...", status, DATA_WARNING, "")

    buffer = ""
    try:
        health_agent = HealthRecommendationAgent(openrouter_key=openrouter_key.strip(), model_id=model_id)
        for delta in health_agent.stream_recommendations(aqi_data, user_input, dose):
            buffer += delta
            yield (gauge, aqi_json, bars, trend, dose_md, buffer, status, DATA_WARNING, "")
    except Exception as exc:
        partial = buffer or "_No text was generated._"
        yield (gauge, aqi_json, bars, trend, dose_md, partial,
               f"❌ LLM error: {exc}", DATA_WARNING, "")
        return

    if not buffer.strip():
        yield (gauge, aqi_json, bars, trend, dose_md, "_The model returned an empty response._",
               status, DATA_WARNING, "")
        return

    report = build_report_markdown(
        location=location,
        aqi_data=aqi_data,
        category=category,
        dose=dose,
        recommendations=buffer,
        observed_at=datetime.now(),
        model_name=model_id,
    )
    report_path = write_report(report, city)
    elapsed = time.time() - started

    yield (gauge, aqi_json, bars, trend, dose_md, buffer,
           f"{info_msg} | done in {elapsed:.1f}s | {history_note}",
           DATA_WARNING, build_report_link_html(report_path))


def create_demo() -> gr.Blocks:
    """Create and configure the Gradio interface"""
    init_db()

    with gr.Blocks(title="AQI Analysis Agent") as demo:
        gr.Markdown(
            """
            # 🌍 AQI Analysis Agent
            Get personalized health recommendations based on air quality conditions.
            """
        )
        
        # API Configuration
        with gr.Accordion("API Configuration", open=True):
            firecrawl_key = gr.Textbox(
                label="Firecrawl API Key",
                type="password",
                value=DEFAULT_FIRECRAWL_KEY,
                placeholder="Enter your Firecrawl API key"
            )
            openrouter_key = gr.Textbox(
                label="OpenRouter API Key",
                type="password",
                value=DEFAULT_OPENROUTER_KEY,
                placeholder="Enter your OpenRouter API key (sk-or-v1-...)"
            )
            model_id = gr.Textbox(
                label="Model (OpenRouter model ID)",
                value=DEFAULT_OPENROUTER_MODEL,
                placeholder="e.g., openai/gpt-4o-mini, anthropic/claude-3.5-sonnet, google/gemini-2.0-flash"
            )
        
        # Location Details
        with gr.Row():
            with gr.Column():
                city = gr.Textbox(label="City", placeholder="e.g., Mumbai")
                state = gr.Textbox(
                    label="State",
                    placeholder="Leave blank for Union Territories or US cities",
                    value=""
                )
                country = gr.Textbox(label="Country", value="India")
        
        # Personal Details
        with gr.Row():
            with gr.Column():
                medical_conditions = gr.Textbox(
                    label="Medical Conditions (optional)",
                    placeholder="e.g., asthma, allergies",
                    lines=2
                )
                planned_activity = gr.Textbox(
                    label="Planned Activity",
                    placeholder="e.g., morning jog",
                    lines=2
                )
            with gr.Column():
                intensity = gr.Dropdown(
                    label="Activity intensity (for exposure estimate)",
                    choices=activity_choices(),
                    value=DEFAULT_ACTIVITY,
                    interactive=True
                )
                duration = gr.Slider(
                    label="Duration (minutes)",
                    minimum=5,
                    maximum=240,
                    value=DEFAULT_DURATION_MIN,
                    step=5
                )
        
        # Status Messages
        info_box = gr.Textbox(label="ℹ️ Status", interactive=False)
        
        # Output Areas
        gauge = gr.HTML(label="Current AQI")
        with gr.Row():
            aqi_data_json = gr.JSON(label="📊 Current Air Quality Data")
            guideline_plot = gr.BarPlot(
                label="📈 Reading vs guideline",
                x="metric",
                y="share_of_limit",
                y_title="% of guideline",
                x_title="",
                height=280,
            )
        dose_output = gr.Markdown(label="🫁 Exposure estimate")
        recommendations = gr.Markdown(label="🏥 Health Recommendations")
        trend_plot = gr.LinePlot(
            label="📉 AQI trend (last 7 days)",
            x="observed_at",
            y="aqi",
            x_title="Time",
            y_title="AQI",
            height=260,
        )
        warning_box = gr.Textbox(label="⚠️ Data caveats", interactive=False, lines=4)
        report_file = gr.HTML(label="⬇️ Report")
        
        # Analyze Button
        analyze_btn = gr.Button("🔍 Analyze & Get Recommendations", variant="primary")
        analyze_btn.click(
            fn=analyze_conditions_stream,
            inputs=[
                city,
                state,
                country,
                medical_conditions,
                planned_activity,
                intensity,
                duration,
                firecrawl_key,
                openrouter_key,
                model_id
            ],
            outputs=[
                gauge,
                aqi_data_json,
                guideline_plot,
                trend_plot,
                dose_output,
                recommendations,
                info_box,
                warning_box,
                report_file
            ],
            show_progress="hidden"
        )
        
        # Examples
        gr.Examples(
            examples=[
                ["Mumbai", "Maharashtra", "India", "asthma", "morning walk",
                 "Light (slow walk)", 30],
                ["Delhi", "", "India", "", "outdoor yoga session",
                 "Moderate (brisk walk, cycling)", 45],
                ["New York", "", "United States", "allergies", "afternoon run",
                 "Vigorous (running, sports)", 45],
                ["Kakinada", "Andhra Pradesh", "India", "none", "tennis match",
                 "Vigorous (running, sports)", 120]
            ],
            inputs=[city, state, country, medical_conditions, planned_activity, intensity, duration]
        )
    
    return demo

if __name__ == "__main__":
    demo = create_demo()
    demo.queue()
    demo.launch(share=True, allowed_paths=[REPORTS_DIR])
