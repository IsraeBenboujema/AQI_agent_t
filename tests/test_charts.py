from aqi_core.timing import best_window
from aqi_ui.charts import calendar_figure, history_figure, stations_figure


def test_history_vrect(delhi_reading):
    fig = history_figure(delhi_reading.history, best_window(delhi_reading.history, 60))
    assert len(fig.layout.shapes) == 1
    assert len(fig.data[0].x) == 49


def test_history_without_window(delhi_reading):
    assert len(history_figure(delhi_reading.history, None).layout.shapes) == 0


def test_stations_order(delhi_reading):
    fig = stations_figure(delhi_reading.stations)
    names = list(fig.data[0].y)
    values = list(fig.data[0].x)
    assert len(names) == 10
    assert names[0] == "Ajay Enclave"
    assert values == sorted(values)


def test_stations_few_and_none(rabat_reading):
    assert list(stations_figure(rabat_reading.stations).data[0].y) == ["Agdal"]
    assert stations_figure([]) is None


def test_calendar_grid(delhi_reading):
    fig = calendar_figure(delhi_reading.calendar)
    z = fig.data[0].z
    assert len(z) == 7
    assert z[3][0] == 300  # 1 Jan 2026 is a Thursday
    assert calendar_figure([]) is None
