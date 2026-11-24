"""Plotly figures styled to sit on the dark glowing background."""

from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

import plotly.graph_objects as go

from aqi_core.models import Station
from aqi_core.standards import US_AQI_BANDS, us_aqi_band
from aqi_core.timing import Window, format_window

FONT = "Atkinson Hyperlegible, system-ui, sans-serif"
MUTED = "#9aa3b5"
GRID = "rgba(255,255,255,0.07)"


def _style(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color="#e8ecf4", size=13),
        margin=dict(l=8, r=8, t=12, b=8),
        height=height,
        showlegend=False,
        hoverlabel=dict(font_family=FONT),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, color=MUTED)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, color=MUTED)
    return fig


def history_figure(history: List[Tuple[datetime, int]], window: Optional[Window]) -> go.Figure:
    times = [t for t, _ in history]
    values = [v for _, v in history]
    fig = go.Figure(go.Scatter(
        x=times, y=values, mode="lines+markers",
        line=dict(color="#e8ecf4", width=2.5, shape="spline", smoothing=0.6),
        marker=dict(size=6, color=[us_aqi_band(v).colour for v in values], line=dict(width=0)),
        fill="tozeroy", fillcolor="rgba(232,236,244,0.06)",
        hovertemplate="%{x|%I:%M %p}<br>AQI %{y}<extra></extra>",
    ))
    if window:
        fig.add_vrect(
            x0=window.start, x1=window.end, fillcolor="#4ade80", opacity=0.18, line_width=0,
            annotation_text=f"Best: {format_window(window)}", annotation_position="top left",
            annotation_font=dict(color="#86efac", size=12),
        )
    fig.update_yaxes(title_text="AQI", rangemode="tozero")
    fig.update_xaxes(tickformat="%I %p")
    return _style(fig, 300)


def stations_figure(stations: List[Station], n: int = 5) -> Optional[go.Figure]:
    if not stations:
        return None
    ranked = sorted(stations, key=lambda s: s.aqi)
    chosen = ranked if len(ranked) <= 2 * n else ranked[:n] + ranked[-n:]
    fig = go.Figure(go.Bar(
        x=[s.aqi for s in chosen],
        y=[s.name for s in chosen],
        orientation="h",
        marker=dict(color=[us_aqi_band(s.aqi).colour for s in chosen]),
        text=[str(s.aqi) for s in chosen], textposition="outside", cliponaxis=False,
        hovertemplate="%{y}<br>AQI %{x}<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    fig.update_xaxes(showticklabels=False, showgrid=False)
    return _style(fig, max(160, 34 * len(chosen) + 30))


def _discrete_scale(zmax: int = 500):
    """Colour steps that switch exactly at the US AQI band boundaries."""
    edges = [b.low for b in US_AQI_BANDS] + [zmax]
    scale = []
    for band, low, high in zip(US_AQI_BANDS, edges, edges[1:]):
        scale.append([low / zmax, band.colour])
        scale.append([min(high, zmax) / zmax, band.colour])
    return scale


def calendar_figure(calendar: List[Tuple[date, int]]) -> Optional[go.Figure]:
    if not calendar:
        return None
    year = calendar[0][0].year
    jan1 = date(year, 1, 1)
    first_monday = jan1 - timedelta(days=jan1.weekday())
    weeks = (date(year, 12, 31) - first_monday).days // 7 + 1

    z = [[None] * weeks for _ in range(7)]
    text = [[""] * weeks for _ in range(7)]
    for day, value in calendar:
        col = (day - first_monday).days // 7
        z[day.weekday()][col] = value
        text[day.weekday()][col] = f"{day:%d %b %Y}<br>AQI {value}"

    month_ticks = [((date(year, m, 1) - first_monday).days // 7) for m in range(1, 13)]
    fig = go.Figure(go.Heatmap(
        z=z, text=text, hoverinfo="text", colorscale=_discrete_scale(), zmin=0, zmax=500,
        xgap=3, ygap=3, showscale=False,
    ))
    fig.update_xaxes(tickvals=month_ticks, ticktext=[date(year, m, 1).strftime("%b") for m in range(1, 13)],
                     showgrid=False, side="top")
    fig.update_yaxes(tickvals=[0, 2, 4, 6], ticktext=["Mon", "Wed", "Fri", "Sun"], autorange="reversed",
                     showgrid=False)
    return _style(fig, 220)
