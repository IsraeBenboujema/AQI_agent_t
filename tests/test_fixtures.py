def test_fixtures_load(load_fixture):
    assert "260AQI (US)" in load_fixture("new_delhi.md")
