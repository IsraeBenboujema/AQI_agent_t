import importlib
import json


def _config(demo):
    return json.dumps(demo.get_config_file() if hasattr(demo, "get_config_file") else demo.config, default=str)


def test_demo_builds_without_prefilled_keys(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-secret-123")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secret-456")
    import ai_aqi_analysis_agent_gradio as app
    app = importlib.reload(app)
    config = _config(app.create_demo())
    assert "fc-secret-123" not in config
    assert "sk-or-secret-456" not in config


def test_share_is_opt_in(monkeypatch):
    import ai_aqi_analysis_agent_gradio as app
    monkeypatch.delenv("GRADIO_SHARE", raising=False)
    assert app.share_enabled() is False
    monkeypatch.setenv("GRADIO_SHARE", "1")
    assert app.share_enabled() is True


def test_analysis_stream_with_fake_client(monkeypatch, load_fixture):
    import ai_aqi_analysis_agent_gradio as app
    from aqi_core.fetcher import AqiInClient

    page = load_fixture("new_delhi.md")
    monkeypatch.setattr(app, "get_client", lambda key: AqiInClient(lambda u: (200, page), lambda b, q: []))
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    outputs = list(app.analyze_conditions_stream(
        "New Delhi", "Delhi", "India", "asthma", "evening run", "Vigorous (running, sports)", 60, "", "", ""))
    gauge, data, bars, trend, dose_md, advice, status, warning, report = outputs[-1]
    assert "Severe" in gauge
    assert data["AQI (US)"] == 260
    assert len(bars) == 6 and len(trend) == 49
    assert "OpenRouter" in advice
    assert "aqi.in" in status
