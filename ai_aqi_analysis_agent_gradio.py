"""AQI Analysis Agent: Gradio app (classic layout, same shared core as the Streamlit app).

Run with:  python ai_aqi_analysis_agent_gradio.py
Set GRADIO_SHARE=1 to also get a temporary public link.
"""

import os
import time
from typing import Dict

import gradio as gr
import pandas as pd
from dotenv import load_dotenv

from aqi_core.agent import DEFAULT_MODEL, HealthRecommendationAgent
from aqi_core.fetcher import AqiInClient, FetchFailed
from aqi_core.models import POLLUTANT_KEYS, POLLUTANT_NAMES, POLLUTANT_UNITS, UserInput
from aqi_core.report import (
    REPORTS_DIR,
    build_dose_markdown,
    build_gauge_html,
    build_report_link_html,
    build_report_markdown,
    write_report,
)
from aqi_core.standards import (
    DEFAULT_ACTIVITY,
    DEFAULT_DURATION_MIN,
    WHO_PM25_24H,
    activity_choices,
    estimate_inhaled_dose,
    share_of_who,
    us_aqi_band,
)
from aqi_core.timing import best_window, format_window

load_dotenv()

DATA_WARNING = f"""Data caveats
- Scraped from aqi.in via Firecrawl (pages at most ~10 minutes old).
- AQI is on the US scale with aqi.in's band names. WHO 24h PM2.5 guideline: {WHO_PM25_24H:g} µg/m³.
- Dose estimates are informational only, not medical advice."""

_clients: Dict[str, AqiInClient] = {}


def share_enabled() -> bool:
    return os.getenv("GRADIO_SHARE") == "1"


def get_client(api_key: str) -> AqiInClient:
    if api_key not in _clients:
        _clients[api_key] = AqiInClient.from_firecrawl(api_key)
    return _clients[api_key]


def _key(typed: str, env_name: str) -> str:
    """A key typed in the UI wins; otherwise fall back to the server's .env."""
    return (typed or "").strip() or os.getenv(env_name, "").strip()


def analyze_conditions_stream(city, state, country, medical_conditions, planned_activity,
                              intensity_label, duration_minutes, firecrawl_key, openrouter_key, model_id):
    """Fetch aqi.in, compute dose and best window, draw charts, then stream the LLM advice."""
    started = time.time()
    empty = ("", {}, None, None, "", "", "", DATA_WARNING, "")
    firecrawl_key = _key(firecrawl_key, "FIRECRAWL_API_KEY")
    openrouter_key = _key(openrouter_key, "OPENROUTER_API_KEY")
    model_id = (model_id or "").strip() or DEFAULT_MODEL

    if not (city or "").strip():
        yield empty[:6] + ("Enter a city to check.",) + empty[7:]
        return
    if not firecrawl_key:
        yield empty[:6] + ("Add a Firecrawl API key under API Configuration, or in .env.",) + empty[7:]
        return

    yield empty[:6] + (f"Reading aqi.in for {city}…",) + empty[7:]
    try:
        result = get_client(firecrawl_key).fetch(city, state or "", country or "")
    except FetchFailed as exc:
        yield empty[:6] + (str(exc),) + empty[7:]
        return

    reading = result.reading
    band = us_aqi_band(reading.aqi)
    duration = int(duration_minutes or 0)
    user = UserInput(city=city.strip(), state=(state or "").strip(), country=(country or "").strip(),
                     medical_conditions=(medical_conditions or "").strip(),
                     planned_activity=(planned_activity or "").strip() or "time outdoors",
                     intensity_label=intensity_label, duration_minutes=duration)
    dose = estimate_inhaled_dose(reading.pollutants.get("pm25", 0), intensity_label, duration)
    window = best_window(reading.history, duration)

    gauge = build_gauge_html(reading.aqi, band)
    data = {"Location": reading.place, "AQI (US)": reading.aqi, "Category": band.label}
    data.update({POLLUTANT_NAMES[k]: f"{reading.pollutants[k]:g} {POLLUTANT_UNITS[k]}"
                 for k in POLLUTANT_KEYS if k in reading.pollutants})
    if reading.updated_at:
        data["Updated (local)"] = reading.updated_at.strftime("%Y-%m-%d %H:%M")
    bars = pd.DataFrame([{"metric": f"{POLLUTANT_NAMES[k]} vs WHO", "share_of_limit": share_of_who(k, v)}
                         for k, v in ((k, reading.pollutants[k]) for k in POLLUTANT_KEYS if k in reading.pollutants)])
    trend = pd.DataFrame(reading.history, columns=["observed_at", "aqi"]) if reading.history else None
    dose_md = "### Estimated PM2.5 intake\n" + build_dose_markdown(reading, dose)
    timing = f"cleanest {format_window(window)}" if window else "no clear cleaner window"
    status = (f"Source: aqi.in ({reading.url}) | last 24 h {timing}"
              + (" | cached reading" if result.from_cache else "")
              + f" | fetched in {time.time() - started:.1f}s")

    if not openrouter_key:
        advice = "_Add an OpenRouter API key to get personal advice._"
        yield (gauge, data, bars, trend, dose_md, advice, status, DATA_WARNING, "")
        return

    yield (gauge, data, bars, trend, dose_md, "Writing advice…", status, DATA_WARNING, "")
    buffer = ""
    try:
        agent = HealthRecommendationAgent(openrouter_key, model_id)
        for delta in agent.stream_recommendations(reading, user, dose, window):
            buffer += delta
            yield (gauge, data, bars, trend, dose_md, buffer, status, DATA_WARNING, "")
    except Exception as exc:
        yield (gauge, data, bars, trend, dose_md, buffer or "_No advice was generated._",
               f"{status} | AI advice unavailable: {exc}", DATA_WARNING, "")
        return

    report_path = write_report(build_report_markdown(reading, user, dose, window, buffer, model_id), user.city)
    yield (gauge, data, bars, trend, dose_md, buffer or "_The model returned an empty response._",
           f"{status} | done in {time.time() - started:.1f}s", DATA_WARNING, build_report_link_html(report_path))


def create_demo() -> gr.Blocks:
    with gr.Blocks(title="AQI Analysis Agent") as demo:
        gr.Markdown("# 🌍 AQI Analysis Agent\nLive air quality from aqi.in, with personal health advice.")

        with gr.Accordion("API Configuration", open=False):
            firecrawl_key = gr.Textbox(label="Firecrawl API Key", type="password", value="",
                                       placeholder="Leave empty to use FIRECRAWL_API_KEY from .env")
            openrouter_key = gr.Textbox(label="OpenRouter API Key", type="password", value="",
                                        placeholder="Leave empty to use OPENROUTER_API_KEY from .env")
            model_id = gr.Textbox(label="Model (OpenRouter model ID)", value=DEFAULT_MODEL)

        with gr.Row():
            with gr.Column():
                city = gr.Textbox(label="City", placeholder="e.g., Mumbai")
                state = gr.Textbox(label="State or region (optional)", placeholder="e.g., Maharashtra", value="")
                country = gr.Textbox(label="Country", value="India")
            with gr.Column():
                medical_conditions = gr.Textbox(label="Medical Conditions (optional)",
                                                placeholder="e.g., asthma, allergies", lines=2)
                planned_activity = gr.Textbox(label="Planned Activity", placeholder="e.g., morning jog", lines=2)
            with gr.Column():
                intensity = gr.Dropdown(label="Activity intensity", choices=activity_choices(),
                                        value=DEFAULT_ACTIVITY, interactive=True)
                duration = gr.Slider(label="Duration (minutes)", minimum=5, maximum=240,
                                     value=DEFAULT_DURATION_MIN, step=5)

        analyze_btn = gr.Button("🔍 Analyze & Get Recommendations", variant="primary")
        info_box = gr.Textbox(label="Status", interactive=False)
        gauge = gr.HTML()
        with gr.Row():
            aqi_data_json = gr.JSON(label="Current readings")
            guideline_plot = gr.BarPlot(label="Readings as % of WHO guideline", x="metric", y="share_of_limit",
                                        y_title="% of WHO limit", x_title="", height=280)
        trend_plot = gr.LinePlot(label="AQI over the last 24 hours (aqi.in)", x="observed_at", y="aqi",
                                 x_title="Time", y_title="AQI", height=260)
        dose_output = gr.Markdown()
        recommendations = gr.Markdown(label="Health Recommendations")
        warning_box = gr.Textbox(label="Data caveats", interactive=False, lines=4)
        report_file = gr.HTML()

        analyze_btn.click(
            fn=analyze_conditions_stream,
            inputs=[city, state, country, medical_conditions, planned_activity, intensity, duration,
                    firecrawl_key, openrouter_key, model_id],
            outputs=[gauge, aqi_data_json, guideline_plot, trend_plot, dose_output, recommendations,
                     info_box, warning_box, report_file],
            show_progress="hidden",
        )

        gr.Examples(
            examples=[
                ["Mumbai", "Maharashtra", "India", "asthma", "morning walk", "Light (slow walk)", 30],
                ["Delhi", "", "India", "", "outdoor yoga session", "Moderate (brisk walk, cycling)", 45],
                ["New York", "", "United States", "allergies", "afternoon run", "Vigorous (running, sports)", 45],
                ["Rabat", "", "Morocco", "", "tennis match", "Vigorous (running, sports)", 90],
            ],
            inputs=[city, state, country, medical_conditions, planned_activity, intensity, duration],
        )
    return demo


if __name__ == "__main__":
    demo = create_demo()
    demo.queue()
    demo.launch(share=share_enabled(), allowed_paths=[REPORTS_DIR])
