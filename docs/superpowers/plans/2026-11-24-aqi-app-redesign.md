# AQI App Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AQI agent fetch aqi.in reliably with one Firecrawl scrape, and ship a dark "weather app" Streamlit UI with four new features (AQI hero + all pollutants, 24h chart + best time, neighbourhood ranking, year calendar), on a shared, tested core.

**Architecture:** A new `aqi_core/` package holds everything non-UI: locating the aqi.in page, scraping it, parsing the markdown into an `AqiReading`, AQI bands/WHO limits/dose maths, best-window timing, the LLM agent and the PDF report. A new `aqi_ui/` package holds pure HTML/CSS and Plotly figure builders. The Streamlit app is rebuilt on both; the Gradio app is rewired onto `aqi_core` with its current layout.

**Tech Stack:** Python 3.12 (venv), Streamlit, Plotly, Gradio, agno + OpenRouter, firecrawl-py 1.9.0, fpdf2, pytest.

**Spec:** `docs/superpowers/specs/2026-11-24-aqi-app-redesign-design.md`

## Global Constraints

- Data comes **only from aqi.in**, via Firecrawl. No other air-quality source.
- `firecrawl-py==1.9.0` (keep the pin). Use `FirecrawlApp.scrape_url(url, params={"formats": ["markdown"], "timeout": 45000})` → returns `data` dict with `data["markdown"]` and `data["metadata"]["statusCode"]`; and `FirecrawlApp.map_url(url, params={"search": q, "limit": 10})` → returns dict with `"links"`.
- AQI is aqi.in's **US AQI** with aqi.in's band labels: Good 0–50, Moderate 51–100, Poor 101–150, Unhealthy 151–200, Severe 201–300, Hazardous 301+. CPCB is no longer used for display.
- Never show zeros for missing data; show "n/a" or omit the tile.
- Gradio must not launch with `share=True` unless env `GRADIO_SHARE=1`; no UI field is ever pre-filled with a key from `.env`.
- The demo machine is Windows; the project runs from `.venv` created with `py -3.12 -m venv .venv`. All commands below use `.venv/Scripts/python`.
- Every string taken from the scraped page that is inserted into HTML must go through `html.escape`.
- The repo is not under git yet; Task 1 initializes it. `.env` must never be committed.

## Review Focus

1. Messy location input ("  new delhi ", "NEW YORK", "São Paulo", empty state): the user expects the right page; slugify must lower-case, trim, strip accents and hyphenate. Test in Task 4.
2. A page missing sections (Rabat has no temperature and no world rank; New York state has no live AQI): the user expects the present data shown and the absent parts omitted, never a crash. Tests in Tasks 3 and 7.
3. Firecrawl failing (network, quota, 5xx) on every attempt: the user expects a clear error message naming the URLs tried, not a stack trace or a hang. Test in Task 4.
4. Activity duration longer than the 6 AM–9 PM span, or a 24h table that is missing/short: the user expects "no suitable window" text rather than an error. Test in Task 5.
5. The LLM call failing (rate-limited free model): the user expects all data cards and charts still visible, with an error card where the advice would be. Test in Task 6 (`stream_recommendations` raising surfaces as one exception the UI can catch) and manual check in Task 8.

---

### Task 1: Environment, git, package skeleton, fixtures

**Files:**
- Create: `.venv/` (not committed), `pytest.ini`, `aqi_core/__init__.py`, `aqi_ui/__init__.py`, `tests/__init__.py`, `tests/conftest.py`
- Create: `tests/fixtures/new_delhi.md`, `tests/fixtures/rabat.md`, `tests/fixtures/new_york_state.md`, `tests/fixtures/not_found.md`, `tests/fixtures/map_new_york_city.json` (copied from `docs/superpowers/specs/assets/aqi-in-new-delhi-2026-11-24.md`, `…-rabat-…`, `…-new-york-state-…`, `…-not-found-…`, `firecrawl-map-new-york-city.json`)
- Modify: `requirements.txt`, `.gitignore`

**Interfaces:**
- Produces: `tests/conftest.py` fixture `load_fixture(name: str) -> str` (reads `tests/fixtures/<name>` as UTF-8).

- [ ] **Step 1: Create the venv and install**

Add `plotly` and `pytest` to `requirements.txt`. Run:
`py -3.12 -m venv .venv` then `.venv/Scripts/python -m pip install -r requirements.txt`
Expected: installs without errors; `.venv/Scripts/python -c "import agno, firecrawl, gradio, streamlit, plotly, fpdf"` prints nothing.

- [ ] **Step 2: Ignore files and init git**

Append to `.gitignore`: `.venv/`, `.gradio/`, `*.zip`, `.superpowers/`. Then `git init`, `git add -A`, verify `git status` does **not** list `.env`, then `git commit -m "chore: baseline before redesign"`.

- [ ] **Step 3: Skeleton, fixtures, pytest config**

Create the empty packages, copy fixtures, `pytest.ini` with `testpaths = tests`. Add a smoke test `tests/test_fixtures.py::test_fixtures_load` asserting `"260AQI (US)" in load_fixture("new_delhi.md")`.

- [ ] **Step 4: Run**

Run: `.venv/Scripts/python -m pytest -q` — Expected: 1 passed.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "chore: venv deps, package skeleton, aqi.in fixtures"`

---

### Task 2: Standards — US AQI bands, WHO limits, dose maths

**Files:**
- Create: `aqi_core/standards.py` (moved from `aqi_standards.py`, then changed)
- Delete: `aqi_standards.py` (update imports in both apps so they still import; full rewire comes later)
- Test: `tests/test_standards.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Band: label: str; colour: str; low: int; high: int | None; advice: str`
  - `US_AQI_BANDS: list[Band]` — exactly: Good 0–50 `#22c55e`; Moderate 51–100 `#eab308`; Poor 101–150 `#f97316`; Unhealthy 151–200 `#ef4444`; Severe 201–300 `#a855f7`; Hazardous 301+ `#9f1239`.
  - `us_aqi_band(aqi: float) -> Band`
  - `WHO_LIMITS_UG_M3 = {"pm25": 15, "pm10": 45, "no2": 25, "so2": 40, "o3": 100, "co": 4000}`
  - `to_ug_m3(key: str, value: float) -> float` — PM passthrough; gases (ppb) `value * MW / 24.45` with MW `{"co": 28.01, "no2": 46.01, "so2": 64.07, "o3": 48.00}`
  - `share_of_who(key: str, value: float) -> float` — percent of WHO limit, 1 decimal
  - Kept unchanged: `ACTIVITY_PROFILES`, `DEFAULT_ACTIVITY`, `DEFAULT_DURATION_MIN`, `activity_choices()`, `estimate_inhaled_dose(...)`, `WHO_PM25_24H`.
  - Removed: `CPCB_BANDS`, `categorize_aqi`, `has_usable_data`, `guideline_bars` (Task 9 re-adds a reading-based version in the Gradio app if needed).

- [ ] **Step 1: Write failing tests**

```python
def test_band_boundaries():
    assert us_aqi_band(0).label == "Good"
    assert us_aqi_band(50).label == "Good"
    assert us_aqi_band(51).label == "Moderate"
    assert us_aqi_band(150).label == "Poor"
    assert us_aqi_band(200).label == "Unhealthy"
    assert us_aqi_band(260).label == "Severe"      # Delhi: was mislabelled "Poor"
    assert us_aqi_band(301).label == "Hazardous"
    assert us_aqi_band(999).label == "Hazardous"

def test_share_of_who():
    assert share_of_who("pm25", 185) == 1233.3
    assert share_of_who("no2", 18) == round(18 * 46.01 / 24.45 / 25 * 100, 1)

def test_dose_unchanged():
    dose = estimate_inhaled_dose(185, "Moderate (brisk walk, cycling)", 60)
    assert dose["dose_ug"] == 333.0
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_standards.py -q` — Expected: FAIL (module not found).
- [ ] **Step 3: Implement** per the Interfaces block; band advice strings are short, plain sentences (builder's wording).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: US AQI bands and WHO limits in aqi_core.standards`

---

### Task 3: Models and aqi.in markdown parser

**Files:**
- Create: `aqi_core/models.py`, `aqi_core/parser.py`
- Test: `tests/test_parser.py`

**Interfaces:**
- Produces (`aqi_core/models.py`):
  - `@dataclass class Station: name: str; status: str; aqi: int; pm25: float | None; pm10: float | None`
  - `@dataclass class AqiReading: place: str; url: str; aqi: int; updated_at: datetime | None; world_rank: int | None; pollutants: dict[str, float]; temperature_c: float | None; humidity_pct: float | None; wind_kmh: float | None; uv_index: float | None; history: list[tuple[datetime, int]]; stations: list[Station]; calendar: list[tuple[date, int]]`
    - `pollutants` keys ⊆ `{"pm25", "pm10", "co", "so2", "no2", "o3"}`; PM in µg/m³, gases in ppb (as aqi.in shows).
    - `history` oldest first, one point per 30 min; `calendar` sorted by date.
  - `@dataclass class UserInput: city: str; state: str; country: str; medical_conditions: str; planned_activity: str; intensity_label: str; duration_minutes: int` (moved from the apps)
  - `class NoLiveReading(Exception)`
- Produces (`aqi_core/parser.py`): `parse_page(markdown: str, url: str) -> AqiReading` — raises `NoLiveReading` when no `<n>AQI (US)` value exists (404 page, state-level page).

Parsing rules (each section independent; a missing section yields `None`/empty, never an exception):
- place: `^# (.+?) Air Quality Index` (strip markdown escapes)
- aqi: first `(\d+)\s*AQI \(US\)`
- updated_at: `Last Updated: \*\*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\*\*`
- world_rank: `Rank(\d+)(st|nd|rd|th)`
- temperature: first `(-?\d+(?:\.\d+)?)\s*°C` that appears **before** `## Major Air Pollutants` (the sky condition word, e.g. "Clear", is not parsed: it is decoration and its position varies); humidity `Humidity\s*(\d+(?:\.\d+)?)\s*%`; wind `Wind Speed\s*(\d+(?:\.\d+)?)\s*km/h`; UV `UV Index\s*(\d+(?:\.\d+)?)` (note Rabat writes `Humidity80%`, Delhi `Humidity58 %`)
- pollutants: within `## Major Air Pollutants`, label `(PM₂.₅)`→pm25, `(PM₁₀)`→pm10, `(CO)`, `(SO₂)`, `(NO₂)`, `(O₃)`, each followed (after `\\` line breaks) by `<number>(µg/m³|ppb)`
- history: rows `| h:mmam |  n |` inside `## Historical Air Quality Data` up to the next `## `; timestamps assigned **backwards from `updated_at`** in 30-minute steps (last row = `updated_at`). Empty if `updated_at` is None.
- stations: table after a heading matching `^## .+'s (Locations|Cities)`; rows `| [name](url) | status | aqi | pm25 | pm10 | … |`
- calendar: inside `## Air Quality Calendar (\d{4})`; each month name line starts a table; cells `(\d{1,2}) ([A-Z][a-z]{2})\.?<br>(\d+|--)` (May has no dot); keep only cells whose month equals the table's month and whose value is not `--`.

- [ ] **Step 1: Write failing tests**

```python
def test_new_delhi_full_page(load_fixture):
    r = parse_page(load_fixture("new_delhi.md"), "https://www.aqi.in/dashboard/india/delhi/new-delhi")
    assert r.place == "New Delhi" and r.aqi == 260 and r.world_rank == 41
    assert r.updated_at == datetime(2026, 11, 24, 4, 31)
    assert r.pollutants == {"pm25": 185, "pm10": 259, "co": 908, "so2": 4, "no2": 18, "o3": 5}
    assert (r.temperature_c, r.humidity_pct, r.wind_kmh, r.uv_index) == (15, 58, 7.9, 0)
    assert len(r.history) == 49
    assert r.history[0] == (datetime(2026, 11, 23, 4, 31), 453)
    assert r.history[-1] == (datetime(2026, 11, 24, 4, 31), 260)
    assert len(r.stations) == 451
    assert r.stations[0] == Station("Abul Fazal Enclave", "Severe", 264, 190, 265)
    assert len(r.calendar) == 327
    assert r.calendar[0] == (date(2026, 1, 1), 300)
    assert (date(2026, 1, 17), 545) in r.calendar
    assert (date(2026, 5, 1), 114) in r.calendar

def test_rabat_missing_sections(load_fixture):
    r = parse_page(load_fixture("rabat.md"), "https://www.aqi.in/dashboard/morocco/rabat-sale-kenitra/rabat")
    assert r.place == "Rabat" and r.aqi == 25
    assert r.temperature_c is None and r.world_rank is None
    assert (r.humidity_pct, r.wind_kmh) == (80, 3.6)
    assert r.pollutants["pm25"] == 5 and r.pollutants["pm10"] == 15
    assert len(r.history) == 49 and r.history[-1][1] == 25
    assert r.stations == [Station("Agdal", "Good", 25, 5, 15)]
    assert r.calendar[0] == (date(2026, 1, 1), 31)

@pytest.mark.parametrize("name", ["new_york_state.md", "not_found.md", ""])
def test_no_live_reading(load_fixture, name):
    md = load_fixture(name) if name else ""
    with pytest.raises(NoLiveReading):
        parse_page(md, "https://www.aqi.in/x")
```

- [ ] **Step 2: Run** `pytest tests/test_parser.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `models.py` and `parse_page` per the rules above.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: parse aqi.in dashboard markdown into AqiReading`

---

### Task 4: Locating the page and fetching via Firecrawl

**Files:**
- Create: `aqi_core/locator.py`, `aqi_core/fetcher.py`
- Test: `tests/test_locator.py`, `tests/test_fetcher.py`

**Interfaces:**
- Consumes: `parse_page`, `NoLiveReading`, `AqiReading` (Task 3).
- Produces (`locator.py`):
  - `slugify(text: str) -> str` — NFKD-strip accents, lower, trim, non-alphanumerics → `-`, collapse/strip dashes.
  - `candidate_urls(city: str, state: str, country: str) -> list[str]` — `https://www.aqi.in/dashboard/{country}/{state}/{city}` (only if state non-empty and not "none"), then `https://www.aqi.in/dashboard/{country}/{city}`; deduplicated, order kept.
  - `pick_dashboard_link(links: list[str], city: str, exclude: set[str]) -> str | None` — ignore links whose last segment is in `{"pm", "pm10", "co", "so2", "no2", "o3", "historical-analysis"}` or that are in `exclude`; prefer last segment `== slugify(city)`, else first whose last segment starts with `slugify(city)`; else None.
- Produces (`fetcher.py`):
  - `@dataclass class FetchResult: reading: AqiReading; tried: list[str]; from_cache: bool`
  - `class FetchFailed(Exception)` with attribute `tried: list[str]`; message names the city and lists the URLs tried.
  - `class AqiInClient:`
    - `__init__(self, scrape: Callable[[str], tuple[int, str]], map_links: Callable[[str, str], list[str]], ttl_seconds: int = 1800, clock: Callable[[], float] = time.time)` — `scrape(url)` returns `(status_code, markdown)`; `map_links(base_url, query)` returns links.
    - `@classmethod from_firecrawl(cls, api_key: str) -> "AqiInClient"` — wraps `FirecrawlApp.scrape_url` / `map_url` per Global Constraints.
    - `fetch(self, city: str, state: str, country: str) -> FetchResult`

Fetch algorithm:
1. Location key `(slug city, slug state, slug country)`; if a cached URL+reading for it is younger than `ttl_seconds`, return it with `from_cache=True`.
2. For each candidate URL: scrape (retry **once** on exception); accept iff status 200, `parse_page` succeeds, and `slugify(city) in slugify(reading.place)`.
3. If none accepted: `map_links(f"https://www.aqi.in/dashboard/{slug country}", city)`, `pick_dashboard_link(links, city, exclude=tried)`, and try that URL with the same acceptance test.
4. Otherwise raise `FetchFailed`. Cache accepted results by location key.

- [ ] **Step 1: Write failing tests**

```python
def test_slugify():
    assert slugify("  New Delhi ") == "new-delhi"
    assert slugify("NEW YORK") == "new-york"
    assert slugify("São Paulo") == "sao-paulo"

def test_candidates():
    assert candidate_urls("Mumbai", "Maharashtra", "India") == [
        "https://www.aqi.in/dashboard/india/maharashtra/mumbai",
        "https://www.aqi.in/dashboard/india/mumbai"]
    assert candidate_urls("Delhi", "", "India") == ["https://www.aqi.in/dashboard/india/delhi"]

def test_pick_link_new_york(load_fixture):
    links = json.loads(load_fixture("map_new_york_city.json"))["links"]
    assert pick_dashboard_link(links, "New York", exclude={"https://www.aqi.in/dashboard/united-states/new-york"}) \
        == "https://www.aqi.in/dashboard/united-states/new-york/new-york-city"
```

`tests/test_fetcher.py` uses fake `scrape`/`map_links` built from fixtures:
- `test_first_candidate_wins` — Delhi fixture served at the first candidate; `fetch("New Delhi", "Delhi", "India").reading.aqi == 260`; `map_links` never called.
- `test_falls_back_to_map` — `fetch("New York", "New York", "United States")`: the candidates `…/united-states/new-york/new-york` and `…/united-states/new-york` return `(404, not_found)` and `(200, new_york_state)`; map returns the NYC fixture links; the NYC URL serves a page whose place is "New York City" (Delhi fixture with H1 replaced) → result URL is the NYC link; `tried` has 3 entries.
- `test_wrong_city_rejected` — candidate serves the Rabat page for city "Mumbai" → not accepted.
- `test_cache` — second `fetch` within ttl → `from_cache is True` and scrape called once; after advancing the fake clock past 1800 s → scraped again.
- `test_firecrawl_errors_raise_fetch_failed` — scrape always raises → `FetchFailed`, each URL attempted exactly twice, message contains every tried URL.

- [ ] **Step 2: Run** `pytest tests/test_locator.py tests/test_fetcher.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces and algorithm.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Live check** (credits are fine): `.venv/Scripts/python -c "from dotenv import load_dotenv; load_dotenv(); import os; from aqi_core.fetcher import AqiInClient; c=AqiInClient.from_firecrawl(os.environ['FIRECRAWL_API_KEY']); [print(c.fetch(*l).reading.url) for l in [('Delhi','','India'),('Mumbai','Maharashtra','India'),('New York','','United States'),('Rabat','','Morocco')]]"` — Expected: four aqi.in dashboard URLs, the last two found via map.
- [ ] **Step 6: Commit** — `feat: locate and fetch aqi.in pages with retry, validation and cache`

---

### Task 5: Best time window

**Files:**
- Create: `aqi_core/timing.py`
- Test: `tests/test_timing.py`

**Interfaces:**
- Consumes: `AqiReading.history` (Task 3).
- Produces: `@dataclass class Window: start: datetime; end: datetime; mean_aqi: float` and `best_window(history: list[tuple[datetime, int]], minutes: int, day_start: int = 6, day_end: int = 21) -> Window | None`, plus `format_window(w: Window) -> str` returning e.g. `"4:01 PM–5:01 PM"`.

Algorithm: `k = max(1, ceil(minutes / 30))` consecutive points, all with `day_start <= t.hour < day_end`; lowest mean wins, ties → earliest; `end = last point + 30 min`; None if no slice fits.

- [ ] **Step 1: Write failing tests**

```python
def test_delhi_one_hour(load_fixture):
    r = parse_page(load_fixture("new_delhi.md"), "u")
    w = best_window(r.history, 60)
    assert (w.start, w.end, w.mean_aqi) == (datetime(2026,11,23,16,1), datetime(2026,11,23,17,1), 178.5)
    assert format_window(w) == "4:01 PM–5:01 PM"

def test_delhi_two_hours(load_fixture):
    w = best_window(parse_page(load_fixture("new_delhi.md"), "u").history, 120)
    assert (w.start, w.mean_aqi) == (datetime(2026,11,23,15,31), 179.75)

def test_night_minimum_ignored():
    base = datetime(2026,1,1,0,0)
    hist = [(base + timedelta(minutes=30*i), 10 if i == 6 else 100) for i in range(48)]  # 03:00 is cleanest
    assert 6 <= best_window(hist, 30).start.hour < 21

def test_no_window():
    assert best_window([], 60) is None
    assert best_window([(datetime(2026,1,1,12,0), 50)], 16*60) is None
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `feat: best daytime window from 24h history`

---

### Task 6: Agent prompt and PDF report on AqiReading

**Files:**
- Create: `aqi_core/agent.py` (moved from the apps' `HealthRecommendationAgent`), `aqi_core/report.py` (moved from `aqi_report.py`)
- Delete: `aqi_report.py`, `aqi_history.py` (the local 7-day history is dropped: aqi.in's 24h table and calendar replace it; leave `aqi_history.db` on disk untouched)
- Test: `tests/test_agent_prompt.py`, `tests/test_report.py`

**Interfaces:**
- Consumes: `AqiReading`, `UserInput` (Task 3); `Band`, `us_aqi_band`, `estimate_inhaled_dose` (Task 2); `Window`, `format_window` (Task 5).
- Produces (`agent.py`):
  - `build_prompt(reading: AqiReading, user: UserInput, dose: dict, window: Window | None) -> str`
  - `class HealthRecommendationAgent: __init__(self, openrouter_key: str, model_id: str, base_url: str)`; `stream_recommendations(self, reading, user, dose, window) -> Iterator[str]` (keep the existing delta/fallback streaming logic; if no text was produced and the fallback also fails, the exception propagates).
  - `DEFAULT_MODEL` / `OPENROUTER_BASE_URL` read from env as today.
- Produces (`report.py`):
  - `build_report_markdown(reading: AqiReading, user: UserInput, dose: dict, window: Window | None, recommendations: str, model_name: str) -> str`
  - `write_report(markdown: str, city: str) -> str` and `markdown_to_pdf` (unchanged), `REPORTS_DIR` (unchanged).
  - `build_dose_markdown(reading: AqiReading, dose: dict) -> str` (the existing dose table, now reading PM2.5 from `reading.pollutants["pm25"]` and the location from `reading.place`).
  - `build_gauge_html(aqi: float, band: Band) -> str` (Gradio only; uses band colour/label, scale text "US AQI (aqi.in)", markers at 0/50/100/150/200/300/500).

Prompt must contain: place and the aqi.in URL; AQI with band label and "US AQI"; every pollutant present with units; weather fields present; dose numbers; the best window text "Based on the last 24 hours the air was cleanest {format_window(w)}" or "No clear cleaner window in the last 24 hours"; the same 4 numbered headings as today.
Report uses ASCII pollutant names (`PM2.5, PM10, CO, SO2, NO2, O3`) because the PDF font is latin-1, and includes "Data updated" time, source URL and best window.

- [ ] **Step 1: Write failing tests**

```python
def test_prompt_contents(delhi_reading, user):
    p = build_prompt(delhi_reading, user, estimate_inhaled_dose(185, user.intensity_label, 60), best_window(delhi_reading.history, 60))
    for s in ["New Delhi", "260", "Severe", "US AQI", "NO2: 18 ppb", "PM2.5: 185 µg/m³", "4:01 PM–5:01 PM",
              "https://www.aqi.in/dashboard/india/delhi/new-delhi"]:
        assert s in p

def test_prompt_rabat_without_temperature(rabat_reading, user):
    assert "Temperature" not in build_prompt(rabat_reading, user, {}, None)

def test_stream_error_propagates(monkeypatch, delhi_reading, user):
    agent = HealthRecommendationAgent("k", "m", "http://x")
    monkeypatch.setattr(agent.agent, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429")))
    with pytest.raises(RuntimeError):
        list(agent.stream_recommendations(delhi_reading, user, {}, None))

def test_report_pdf(tmp_path, delhi_reading, user):
    dose = estimate_inhaled_dose(185, user.intensity_label, user.duration_minutes)
    md = build_report_markdown(delhi_reading, user, dose, None, "Advice text", "model-x")
    assert "NO2" in md and "2026-11-24 04:31" in md
    out = tmp_path / "r.pdf"; markdown_to_pdf(md, str(out)); assert out.stat().st_size > 1000
```
(`delhi_reading`, `rabat_reading`, `user` go in `tests/conftest.py` as fixtures; the prompt's pollutant line format is `NAME: value unit`.)

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `refactor: shared agent and report on AqiReading`

---

### Task 7: UI builders — theme HTML and Plotly charts

**Files:**
- Create: `aqi_ui/theme.py`, `aqi_ui/charts.py`
- Test: `tests/test_theme.py`, `tests/test_charts.py`

**Interfaces:**
- Consumes: `AqiReading`, `Station` (Task 3); `Band`, `us_aqi_band`, `US_AQI_BANDS`, `share_of_who` (Task 2); `Window` (Task 5).
- Produces (`theme.py`, all return HTML/CSS strings):
  - `page_css(band: Band | None) -> str` — `<style>` block: dark base `#0d0b10`; `.stApp` background `radial-gradient(circle at 30% 0%, <band colour at ~45% opacity> 0%, #1a1015 55%, #0d0b10 100%)` (neutral slate tint when None); `.glass` card class: `rgba(255,255,255,.06)` fill, `1px solid rgba(255,255,255,.10)` border, `backdrop-filter: blur(8px)`, 16px radius.
  - `hero_html(reading: AqiReading, band: Band) -> str` — AQI number (≥64px, band colour), `"{band.label.upper()} · US AQI"`, `"🌐 #{rank} most polluted worldwide"` only if rank, `"updated {HH:MM} local · source: aqi.in"` with the URL linked.
  - `tiles_html(reading: AqiReading) -> str` — one `.glass` tile per pollutant present (ordered pm25, pm10, co, no2, so2, o3; display names `PM2.5, PM10, CO, NO₂, SO₂, O₃`), value + unit + `"{share}% of WHO"`; tile accent green ≤100 %, amber ≤200 %, red >200 %; then weather tiles only for fields that are not None.
  - `landing_html() -> str` — title, one-line pitch, hint "Try Delhi, Mumbai, New York or Rabat".
- Produces (`charts.py`, all return `plotly.graph_objects.Figure` with `template="plotly_dark"`, transparent `paper_bgcolor`/`plot_bgcolor`):
  - `history_figure(history: list[tuple[datetime, int]], window: Window | None) -> Figure` — line of AQI; one `add_vrect` (green, ~0.18 opacity, annotation `"best {format_window}"`) when window.
  - `stations_figure(stations: list[Station], n: int = 5) -> Figure | None` — None if no stations; else horizontal bars of the `n` cleanest then the `n` dirtiest (deduplicated when fewer than `2n`), sorted cleanest at top, each bar coloured by `us_aqi_band(aqi).colour`.
  - `calendar_figure(calendar: list[tuple[date, int]]) -> Figure | None` — None if empty; heatmap 7 rows (Mon=0 … Sun=6) × weeks (column = `(d - monday_on_or_before_jan1).days // 7`); discrete colourscale with stops at the US AQI band boundaries; hover shows date and AQI.

- [ ] **Step 1: Write failing tests**

```python
def test_hero_delhi(delhi_reading):
    h = hero_html(delhi_reading, us_aqi_band(260))
    assert "260" in h and "SEVERE" in h and "#41" in h and "#a855f7" in h

def test_hero_escapes():
    r = replace(delhi_reading, place="<script>x</script>")
    assert "<script>" not in hero_html(r, us_aqi_band(r.aqi))

def test_tiles_rabat_has_no_temperature(rabat_reading):
    t = tiles_html(rabat_reading)
    assert "°C" not in t and "PM2.5" in t and "80%" in t

def test_history_vrect(delhi_reading):
    fig = history_figure(delhi_reading.history, best_window(delhi_reading.history, 60))
    assert len(fig.layout.shapes) == 1

def test_stations_order(delhi_reading):
    fig = stations_figure(delhi_reading.stations)
    names = list(fig.data[0].y)
    assert len(names) == 10
    assert stations_figure([]) is None

def test_calendar_grid(delhi_reading):
    fig = calendar_figure(delhi_reading.calendar)
    z = fig.data[0].z
    assert len(z) == 7 and z[3][0] == 300    # 1 Jan 2026 is a Thursday
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `feat: dark theme HTML builders and Plotly charts`

---

### Task 8: Streamlit app rebuilt on the shared core

**Files:**
- Modify (rewrite): `ai_aqi_analysis_agent_streamlit.py`
- Create: `.streamlit/config.toml` (`[theme] base="dark"`, `primaryColor="#a855f7"`)
- Test: `tests/test_streamlit_app.py`

**Interfaces:**
- Consumes: everything from Tasks 2–7.
- Produces: `get_client(api_key: str) -> AqiInClient` decorated with `@st.cache_resource` (so the 30-min cache survives reruns).

Layout (top to bottom, per spec sketch): `page_css(band)` injected first via `st.markdown(..., unsafe_allow_html=True)`; sidebar holds API settings and the inputs (city, state, country, medical conditions, planned activity, intensity, duration, Analyze button); main area shows `landing_html()` until a result exists; then hero, tiles, two columns (24h `history_figure` | `stations_figure`, each in a `.glass` container with a heading), the dose card (`build_dose_markdown(reading, dose)` from Task 6, inside a `.glass` container), the streamed recommendations card, `calendar_figure`, and the PDF download button. A missing figure (None) shows a short caption instead.
Keys: if `FIRECRAWL_API_KEY`/`OPENROUTER_API_KEY` exist in env, the sidebar shows "✓ loaded from .env" and an **empty** optional override field; otherwise an empty required field. Model id field defaults to `DEFAULT_MODEL`.
Errors: `FetchFailed` → `st.error` with its message, no cards; LLM exception → all data cards remain, advice card shows `st.error(f"AI advice unavailable: {exc}")` and the PDF is still offered without advice.
Result persistence: store the reading, window, dose, advice and report path in `st.session_state.result`; re-render from it on reruns (download click).

- [ ] **Step 1: Write failing test**

```python
from streamlit.testing.v1 import AppTest
def test_landing_renders():
    at = AppTest.from_file("ai_aqi_analysis_agent_streamlit.py").run(timeout=30)
    assert not at.exception
    assert any("Delhi" in m.value for m in at.markdown)
```
- [ ] **Step 2: Run** — FAIL (old app has no landing). **Step 3: Implement.** **Step 4: Run** — PASS, and `pytest -q` all green.
- [ ] **Step 5: Manual check:** `.venv/Scripts/python -m streamlit run ai_aqi_analysis_agent_streamlit.py`; analyse Delhi, Mumbai (Maharashtra), New York (United States), Rabat (Morocco). Expected: page glow matches band colour; AQI and PM2.5 match aqi.in in a browser; Rabat shows no temperature tile; 24h chart shows a daytime green window; stations and calendar render; PDF downloads. Then set a bogus OpenRouter key: data still shows, advice card shows the error. Take a screenshot of the Delhi result to `docs/screenshot-delhi.png` for the README.
- [ ] **Step 6: Commit** — `feat: dark weather-app Streamlit UI with 24h, neighbourhood and calendar views`

---

### Task 9: Gradio app rewired, keys safe

**Files:**
- Modify (rewrite internals, keep layout): `ai_aqi_analysis_agent_gradio.py`
- Test: `tests/test_gradio_app.py`

**Interfaces:**
- Consumes: Tasks 2–6 (`AqiInClient`, `us_aqi_band`, `share_of_who`, `best_window`, `HealthRecommendationAgent`, `build_gauge_html`, report functions).

Changes: delete the in-file `AQIAnalyzer`, `ExtractSchema`, `AQIResponse`, agent and `UserInput`; `analyze_conditions_stream` uses `AqiInClient` (one module-level client per Firecrawl key) and yields the same 9 outputs. The "Reading vs guideline" bar plot uses rows `{"metric": "<NAME> vs WHO", "share_of_limit": share_of_who(k, v)}` for each pollutant present; the trend plot uses `reading.history` as a DataFrame (`observed_at`, `aqi`). Key textboxes start empty (placeholder says "leave empty to use .env"); empty → env value. `demo.launch(share=os.getenv("GRADIO_SHARE") == "1", allowed_paths=[REPORTS_DIR])`.

- [ ] **Step 1: Write failing test**

```python
def test_demo_builds_without_prefilled_keys(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-secret")
    import importlib, ai_aqi_analysis_agent_gradio as g; importlib.reload(g)
    demo = g.create_demo()
    assert "fc-secret" not in str(demo.config)
```
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS; full `pytest -q` green.
- [ ] **Step 5: Manual check:** `.venv/Scripts/python ai_aqi_analysis_agent_gradio.py`; analyse Delhi; no public URL printed.
- [ ] **Step 6: Commit** — `refactor: Gradio app on aqi_core; no public share or prefilled keys by default`

---

### Task 10: README and final verification

**Files:**
- Modify: `README.md`, `.env.example` (add `GRADIO_SHARE=0` with a comment)

- [ ] **Step 1: README** — Streamlit as the main app (`streamlit run ai_aqi_analysis_agent_streamlit.py`), venv setup commands from Task 1, `pytest` command, screenshot `docs/screenshot-delhi.png`, feature list updated, a **"What changed in this version"** section for the grader (reliability: one scrape + page finder + validation + cache; correctness: US AQI scale fix; new features 1–4; cleanup: `aqi_core`/`aqi_ui` packages, tests; security: no public link/prefilled keys), and a note never to share `.env`.
- [ ] **Step 2: Verify** — `.venv/Scripts/python -m pytest -q` → all pass; launch Streamlit once more for Delhi to confirm nothing regressed.
- [ ] **Step 3: Commit** — `docs: README for the redesigned app`
