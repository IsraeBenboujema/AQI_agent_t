"""Presentation helpers shared by the apps: AQI gauge (Gradio), dose summary, PDF report."""

import os
import re
import tempfile
from datetime import datetime
from typing import Dict, Optional
from urllib.parse import quote

from aqi_core.models import POLLUTANT_KEYS, POLLUTANT_NAMES, POLLUTANT_UNITS, AqiReading, UserInput
from aqi_core.standards import ACTIVITY_PROFILES, US_AQI_BANDS, WHO_PM25_24H, Band, us_aqi_band
from aqi_core.timing import Window, format_window

REPORTS_DIR = os.path.join(tempfile.gettempdir(), "aqi-reports")


def _fmt_number(value: float, digits: int = 1) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_cigarettes(dose_ug: float) -> str:
    cigarettes = float(dose_ug or 0) / 10_000.0
    if cigarettes <= 0:
        return "0"
    if cigarettes < 0.01:
        return "<0.01"
    if cigarettes < 1:
        return f"{cigarettes:.2f}"
    return f"{cigarettes:.1f}"


def build_gauge_html(aqi: float, band: Band) -> str:
    """Self-contained AQI card for the Gradio app: value, band and a marker on a 0-500 scale."""
    try:
        value = float(aqi)
    except (TypeError, ValueError):
        value = 0.0
    percentage = max(0.0, min(value, 500.0)) / 500.0 * 100.0
    stops = ", ".join(
        f"{b.colour} {min((b.low / 500) * 100, 100):.0f}%" for b in US_AQI_BANDS
    )
    off_scale = " (>500, off scale)" if value > 500 else ""
    return f"""
    <div style="font-family: ui-sans-serif, system-ui, sans-serif; background:#ffffff; border:1px solid #e5e7eb;
                border-radius:14px; padding:18px 20px 16px;">
      <div style="display:flex; justify-content:space-between; align-items:flex-end; gap:12px;">
        <div>
          <div style="font-size:44px; line-height:1; font-weight:700; color:{band.colour};">{value:,.0f}{off_scale}</div>
          <div style="font-size:12px; color:#6b7280; margin-top:6px; text-transform:uppercase;">
            Air Quality Index &middot; US AQI (aqi.in)</div>
        </div>
        <div style="padding:5px 12px; border-radius:999px; background:{band.colour}1a; color:{band.colour};
                    font-size:14px; font-weight:600;">{band.label}</div>
      </div>
      <div style="position:relative; margin-top:16px; height:10px; border-radius:999px;
                  background:linear-gradient(90deg, {stops});">
        <div style="position:absolute; left:calc({percentage:.1f}% - 7px); top:-4px; width:14px; height:18px;
                    border-radius:4px; background:#111827; border:2px solid #ffffff; box-sizing:border-box;"></div>
      </div>
      <div style="display:flex; justify-content:space-between; font-size:11px; color:#9ca3af; margin-top:6px;">
        <span>0</span><span>50</span><span>100</span><span>150</span><span>200</span><span>300</span><span>500</span>
      </div>
      <div style="margin-top:12px; font-size:13px; line-height:1.5; color:#374151;">{band.advice}</div>
    </div>
    """


def build_dose_markdown(reading: AqiReading, dose: Dict) -> str:
    """Human-readable summary of the estimated PM2.5 intake for the chosen activity."""
    activity = ACTIVITY_PROFILES.get(dose.get("activity"))
    note = f" ({activity.note})" if activity else ""
    multiplier = dose.get("intensity_multiplier", 0) or 0
    return f"""
**{dose.get('activity', 'Activity')}** for **{int(dose.get('minutes', 0))} min** in {reading.place}{note}.

| Measure | Value |
|---|---|
| PM2.5 in the air | {_fmt_number(reading.pollutants.get('pm25'), 1)} µg/m³ |
| Breathing rate assumed | {dose.get('ventilation_l_min', 0):g} L/min |
| Air inhaled | {_fmt_number(dose.get('volume_m3', 0), 2)} m³ |
| **PM2.5 mass inhaled** | **{_fmt_number(dose.get('dose_ug', 0), 0)} µg** |
| Same time at rest | {_fmt_number(dose.get('resting_dose_ug', 0), 0)} µg |
| Extra due to exertion | ×{multiplier:g} |
| Cigarette-equivalent | ≈ {_fmt_cigarettes(dose.get('dose_ug', 0))} cigarette(s) |
| Share of a WHO guideline day | {_fmt_number(dose.get('who_day_fraction', 0), 0)}% |

<small>Cigarette comparison is a mass-equivalent estimate (≈10 mg PM2.5 per cigarette), not a medical
claim. Assumes a steady outdoor concentration.</small>
"""


def build_report_markdown(
    reading: AqiReading,
    user: UserInput,
    dose: Dict,
    window: Optional[Window],
    recommendations: str,
    model_name: str,
) -> str:
    band = us_aqi_band(reading.aqi)
    updated = reading.updated_at.strftime("%Y-%m-%d %H:%M") if reading.updated_at else "unknown"
    rows = [f"| AQI (US) | {reading.aqi} ({band.label}) |"]
    rows += [
        f"| {POLLUTANT_NAMES[k]} | {_fmt_number(reading.pollutants[k], 1)} {POLLUTANT_UNITS[k].replace('µg/m³', 'ug/m3')} |"
        for k in POLLUTANT_KEYS if k in reading.pollutants
    ]
    if reading.temperature_c is not None:
        rows.append(f"| Temperature | {_fmt_number(reading.temperature_c, 1)} C |")
    if reading.humidity_pct is not None:
        rows.append(f"| Humidity | {_fmt_number(reading.humidity_pct, 0)} % |")
    if reading.wind_kmh is not None:
        rows.append(f"| Wind speed | {_fmt_number(reading.wind_kmh, 1)} km/h |")
    if reading.world_rank is not None:
        rows.append(f"| World pollution rank | #{reading.world_rank} |")
    timing = (f"Cleanest daytime window in the last 24 hours: {format_window(window)} "
              f"(average AQI {window.mean_aqi:.0f})." if window
              else "No clear cleaner daytime window in the last 24 hours.")
    model_line = f"**Model:** {model_name}" if model_name else ""
    readings_table = "\n".join(rows)

    return f"""# AQI Analysis Report

**Location:** {reading.place}
**Data updated:** {updated} (local time)
**Source:** {reading.url}
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
{model_line}

## Air quality readings

| Metric | Value |
|---|---|
{readings_table}

WHO 24h PM2.5 guideline: {WHO_PM25_24H:g} ug/m3.

## Best time to go out

{timing}

## Estimated PM2.5 intake

- Activity: {user.planned_activity} - {dose.get('activity', user.intensity_label)} for {int(dose.get('minutes', user.duration_minutes))} minutes
- Inhaled PM2.5: **{_fmt_number(dose.get('dose_ug', 0), 0)} ug**
- Cigarette-equivalent: ~ {_fmt_cigarettes(dose.get('dose_ug', 0))}
- Share of a WHO guideline day: {_fmt_number(dose.get('who_day_fraction', 0), 0)}%

## Health recommendations

{recommendations or 'AI advice was not available for this report.'}

---
Data scraped from aqi.in via Firecrawl. Estimates are informational only and are not medical advice.
"""


_CHAR_MAP = {
    "—": "-", "–": "-", "−": "-", "≈": "~", "‘": "'", "’": "'",
    "“": '"', "”": '"', "•": "-", "…": "...", "→": "->",
    "≤": "<=", "≥": ">=", " ": " ",
}


def _pdf_text(text: str) -> str:
    """Make text safe for the built-in Helvetica font (latin-1 only) and fpdf2 inline markup."""
    text = re.sub(r"\[([^\]]+)\]\((?:[^)]+)\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)  # drop stray HTML tags such as <small>
    text = text.replace("`", "")
    for src, dst in _CHAR_MAP.items():
        text = text.replace(src, dst)
    text = text.encode("latin-1", "ignore").decode("latin-1")  # drops emoji / unsupported glyphs
    text = text.replace("--", "-").replace("__", "_")  # fpdf2 treats these as markup
    if text.count("**") % 2:
        text = text.replace("**", "")
    return re.sub(r"(?<!\*)\*(?!\*)", "", text).strip()  # single * (italics/bullets) -> removed


def _table_cells(line: str):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def markdown_to_pdf(markdown: str, path: str) -> None:
    """Render the report markdown (headings, paragraphs, bullets, tables) to a PDF file."""
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()

    def para(text, size=10.5, style="", gap=1.5, indent=0):
        pdf.set_font("Helvetica", style, size)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(0, size * 0.5 + 1.2, text, markdown=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(gap)

    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i].rstrip()
        stripped = raw.strip()

        if not stripped:
            i += 1
        elif stripped.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = _table_cells(lines[i])
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append([_pdf_text(c).replace("**", "") for c in cells])
                i += 1
            if rows:
                pdf.set_font("Helvetica", "", 10)
                with pdf.table(first_row_as_headings=True, text_align="LEFT", line_height=6.5) as table:
                    for cells in rows:
                        row = table.row()
                        for cell in cells:
                            row.cell(cell)
                pdf.ln(4)
            continue
        elif stripped == "---":
            pdf.ln(2)
            pdf.set_draw_color(200, 200, 200)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(4)
            i += 1
        elif stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            text = _pdf_text(stripped.lstrip("#"))
            size = {1: 20, 2: 14, 3: 12}.get(level, 11)
            pdf.ln(3 if level > 1 else 0)
            para(text.replace("**", ""), size=size, style="B", gap=2)
            i += 1
        elif re.match(r"^[-*+] ", stripped) or re.match(r"^\d+[.)] ", stripped):
            marker = "-" if stripped[0] in "-*+" else re.match(r"^\d+[.)]", stripped).group(0)
            body = re.sub(r"^([-*+]|\d+[.)])\s+", "", stripped)
            para(f"{marker} {_pdf_text(body)}", indent=4, gap=0.8)
            i += 1
        else:
            para(_pdf_text(stripped))
            i += 1

    pdf.output(path)


def write_report(markdown: str, city: str) -> str:
    """Render the report to a PDF in the temp reports dir and return its path for download."""
    slug = re.sub(r"[^a-z0-9]+", "-", (city or "location").lower()).strip("-") or "location"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f"aqi-report-{slug}-{stamp}.pdf")
    markdown_to_pdf(markdown, path)
    return path


def build_report_link_html(path: Optional[str]) -> str:
    """Download link served by Gradio's /file= route (works without a File component)."""
    if not path:
        return ""

    url = "/gradio_api/file=" + quote(path.replace("\\", "/"), safe="/:")
    filename = os.path.basename(path)
    return f"""
    <a href="{url}" download="{filename}" target="_blank" rel="noopener"
       style="display:inline-flex; align-items:center; gap:8px; padding:9px 16px;
              border-radius:10px; background:#111827; color:#ffffff; font-size:14px;
              font-weight:600; text-decoration:none;">
      ⬇️ Download report (PDF)
    </a>
    <span style="margin-left:10px; font-size:12px; color:#6b7280;">{filename}</span>
    """
