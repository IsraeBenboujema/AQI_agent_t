from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "ai_aqi_analysis_agent_streamlit.py")


def test_landing_renders():
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert any("What are you breathing today?" in m.value for m in at.markdown)


def test_full_flow_keeps_data_when_ai_fails(monkeypatch, load_fixture):
    from aqi_core import agent as agent_module
    from aqi_core.fetcher import AqiInClient

    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    page = load_fixture("new_delhi.md")
    fake = AqiInClient(lambda url: (200, page), lambda base, q: [])
    monkeypatch.setattr(AqiInClient, "from_firecrawl", classmethod(lambda cls, key: fake))

    def failing_stream(self, *args, **kwargs):
        raise RuntimeError("429 rate limited")
        yield  # pragma: no cover

    monkeypatch.setattr(agent_module.HealthRecommendationAgent, "stream_recommendations", failing_stream)

    at = AppTest.from_file(APP).run(timeout=30)
    at.sidebar.text_input[0].input("New Delhi")
    at.sidebar.text_input[1].input("Delhi")
    at.sidebar.button[0].click()
    at.run(timeout=60)

    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "The air in New Delhi is severe right now." in html
    assert "1233% of WHO limit" in html
    assert any("AI advice unavailable: 429 rate limited" in e.value for e in at.error)
    assert any("4:01 PM–5:01 PM" in c.value for c in at.caption)
