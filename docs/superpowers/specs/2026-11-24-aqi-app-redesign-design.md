# AQI Analysis Agent: redesign and new features

Date: 2026-11-24
Status: approved 2026-11-24

## Intent and why

This is a course assignment: "improve this project" (the AQI Analysis Agent from
awesome-llm-apps). The grade rewards **visible new features and a better look** most;
**code cleanup is a plus**. The app must keep getting its data from **aqi.in**.

So the work is: make the aqi.in fetch dependable enough to demo without failures,
put a striking dark UI on top, add four data-rich features, and leave the code
noticeably cleaner than it started.

## Goals

1. The analysis works reliably for common cities (Indian metros, big world cities)
   in a live demo, and fails with a clear message, never silently with zeros.
2. A dark, "weather app" look (the user picked this from mockups, option B): background
   glows in the colour of the current AQI category, frosted translucent cards.
3. Four new features, all fed by aqi.in (user picked 1–4 from mockups):
   1. **AQI hero + all pollutants**: big AQI number on aqi.in's own scale, category,
      "last updated" time, global rank badge ("#41 most polluted worldwide"), tiles for
      PM2.5, PM10, CO, NO₂, SO₂, O₃ plus temperature, humidity, wind, UV.
   2. **Last-24-hours chart + best time to go out**: chart aqi.in's half-hourly 24h
      AQI table; highlight the cleanest window long enough for the planned activity
      duration; pass that window to the AI so its "best time" advice uses real data.
   3. **Cleanest and dirtiest neighbourhoods**: ranked horizontal bars of the city's
      monitoring stations (from aqi.in's locations table), coloured by category.
   4. **Year calendar heatmap**: daily AQI for the current year as a coloured calendar
      grid (GitHub-contribution style).
4. Code cleanup: shared logic lives in one place instead of being duplicated in the
   Gradio and Streamlit files; unit tests for parsing and calculations.

## Non-goals

- No other data source (Open-Meteo, OpenAQ, etc.). aqi.in only.
- No restyling of the Gradio app beyond making it run on the shared code.
- No user accounts, deployment, or hosting work.
- Not building city comparison, follow-up chat, or health cards (features 5–7 from the
  mockup were not picked).

## Anti-goals (would make this a failure even if it "works")

- The demo stalls for a minute or shows all-zero readings.
- Numbers on screen disagree with aqi.in (e.g. wrong scale/category).
- API keys exposed to anyone with a public link.
- The redesign looks like a default Streamlit page with a dark theme toggled on.

## Constraints and facts found

- **The grader sees the app as a live demo on the user's own Windows machine.** No
  hosting or public link is needed; the job is to make it solid on that machine
  (set up a working Python environment there and document how to run it).
- **Firecrawl credits are not a constraint during development**: use the key in `.env`
  for as many live scrapes as building and testing need.

- **aqi.in blocks plain HTTP fetches** (HTTP 403 to a normal fetcher). Firecrawl gets
  through, so Firecrawl stays.
- **One Firecrawl `scrape` (markdown) of a city dashboard page returns everything
  needed** (~119 KB markdown, ~1 credit, a few seconds). Verified on
  `https://www.aqi.in/dashboard/india/delhi/new-delhi`. The current code uses
  Firecrawl `extract` with a `/*` wildcard, which is slow, costs far more credits,
  and is what makes it flaky.
- **aqi.in reports AQI on the US EPA scale ("AQI (US)")**, with its own band labels:
  Good 0–50, Moderate 51–100, Poor 101–150, Unhealthy 151–200, Severe 201–300,
  Hazardous 301+. The current app categorises that number on India's CPCB scale,
  so Delhi's 260 shows as "Poor" where aqi.in says "Severe". This is a bug to fix:
  use aqi.in's bands and labels.
- Sections present in the scraped markdown (New Delhi sample):
  - `Last Updated: **2026-11-24 04:31** (Local Time)`
  - `260AQI (US)` then `Air Quality is` / `Severe`
  - weather block: `15 °C`, `Clear`, `Humidity58 %`, `Wind Speed7.9 km/h`, `UV Index0`
  - `Rank41st` / "New Delhi ranks 41st among the most polluted cities globally."
  - `## Major Air Pollutants` with PM2.5 185 µg/m³, PM10 259 µg/m³, CO 908 ppb,
    SO₂ 4 ppb, NO₂ 18 ppb, O₃ 5 ppb (each followed by a link to `/pm`, `/pm10`,
    `/co`, `/so2`, `/no2`, `/o3`)
  - `## Historical Air Quality Data`: a `| Time | New Delhi |` table of 49 half-hourly
    AQI values covering the last 24 h, then `Min. AQI (US)` / `Max. AQI (US)` with times
  - `## <City>'s Locations`: `| locations | Status | AQI (US) | PM₂.₅ | PM₁₀ | Temp. | Humi. |`
    table, station names are links to their own dashboard pages
  - `## Air Quality Calendar 2026`: one markdown table per month, cells like
    `4 Jan.<br>225` (`--` for no data)
  - `## Health Advice For People Living In` (cigarettes/day etc., not used in this scope)
  - The full sample markdown is saved at
    `docs/superpowers/specs/assets/aqi-in-new-delhi-2026-11-24.md` (no keys in it);
    copy it into the tests as the parser fixture (see Testing).
- **URL shape**: `https://www.aqi.in/dashboard/<country>/<state>/<city>`; some places
  have no state level (e.g. the app's history DB has successful readings for
  `india/delhi` and `morocco/rabat`). The current code guesses a single URL from
  free-text input and breaks on mismatches.
- Python on this machine: 3.12 is on PATH but the app's dependencies are not installed
  there; the app was run from some other environment. `firecrawl-py` is pinned to
  1.9.0, `agno>=2.2.10`, `gradio>=6.32.0`.
- LLM is via OpenRouter (OpenAI-compatible) using agno's `OpenAIChat`, default model
  a free Nemotron model. Free models can rate-limit; the error path must be clean.
- `.env` holds real keys. The Gradio app launches with `share=True` and pre-fills
  keys from `.env` into the UI, so anyone with the public link can use them.

## Approaches considered

- **A. Shared core + one polished Streamlit app; Gradio slimmed onto the shared core.**
  Chosen. Streamlit makes a fully custom dark layout, HTML cards and interactive charts
  easiest, and already has a working PDF download. Trade-off: Gradio's public share
  link shows the plain version.
- **B. Same, but Gradio is the polished one.** Gradio is what the README says to run and
  has a public link for demos, but deep custom layout/styling is more awkward and
  tends to look less finished.
- **C. Fully redesign both.** Most to show, but double the UI work for every feature,
  risking two half-finished apps.

## Design

### Code layout

Move all non-UI logic into a package (name is the builder's call, e.g. `aqi_core/`):

- **scraper**: given city/state/country, find the right aqi.in dashboard URL, scrape
  it once with Firecrawl (markdown), return the markdown and the URL used.
- **parser**: pure functions turning the markdown into a structured reading:
  current AQI + label, last-updated time, global rank, pollutants (6), weather
  (temp, condition, humidity, wind, UV), 24h series, stations list, year calendar.
  Each section is optional; a missing section must not break the others.
- **standards**: aqi.in's US-AQI bands/colours (replacing CPCB as the displayed scale),
  WHO guideline values, activity profiles and the inhaled-dose maths (existing code,
  kept). Best-window calculation lives here: the lowest-average contiguous window in
  the 24h series at least as long as the planned activity, **restricted to waking
  hours (6 AM–9 PM local)** and presented as a pattern, e.g. "Based on the last 24 h,
  the air was cleanest 3–5 PM", not as a forecast. *(Designer's call: an unrestricted
  window often lands at 3 AM, which looks wrong in a demo.)*
- **agent**: the OpenRouter/agno health-recommendation agent (existing prompt, extended
  with the extra pollutants, the aqi.in category, and the best window).
- **history** and **report**: existing SQLite history and PDF report modules, moved in.
  The PDF report gains the extra pollutants and best window.

Both `ai_aqi_analysis_agent_streamlit.py` and `ai_aqi_analysis_agent_gradio.py` become
thin UIs on top of this. Gradio keeps its current layout/outputs, only rewired.

### Data fetching behaviour

- **Finding the page**: try candidate URLs built from the input (with state, without
  state, slugified), and if none yields a page with an AQI reading, discover the right
  URL on aqi.in via Firecrawl (e.g. its map/search capability limited to aqi.in), so a
  user typing "Delhi" or "New York" lands on a real page. Show the URL actually used.
- **Validation**: a page "works" only if the parser finds a current AQI **and the page's
  heading names the requested city** (guards against aqi.in redirecting a bad URL to
  some other page that also shows an AQI; *designer's call*, probe live to confirm how
  aqi.in handles bad URLs). Otherwise
  try the next candidate; after all fail, show a clear message naming what was tried.
- **Retry** transient Firecrawl errors once; keep a short timeout so the UI never hangs
  for a minute.
- **Cache**: reuse a scrape of the same URL for ~30 minutes (aqi.in updates roughly
  half-hourly), so repeat demos are instant and don't spend credits.
- Never substitute zeros for missing data; show "n/a" for absent fields.

### Streamlit UI (dark "weather app" look)

```
┌──────────────────────────────────────────────────────────────┐
│ 🌍 AQI Analysis   [City][State][Country]  [activity][min] ▶ │  ← inputs (top bar or sidebar)
├──────────────────────────────────────────────────────────────┤
│            260   SEVERE · US AQI     🌐 #41 worldwide         │  ← hero; page glow = category colour
│         updated 04:31 local · source: aqi.in/…/new-delhi      │
│  [PM2.5 185][PM10 259][CO 908][NO₂ 18][SO₂ 4][O₃ 5]           │  ← frosted tiles, coloured vs WHO
│  [15°C Clear][Humidity 58%][Wind 7.9 km/h][UV 0]              │
├───────────────────────────────┬──────────────────────────────┤
│ Last 24 hours (AQI)           │ Neighbourhoods right now      │
│ line chart, best window       │ ranked bars, cleanest first   │
│ shaded green: "best 3–5 PM"   │ coloured by category          │
├───────────────────────────────┴──────────────────────────────┤
│ Your exposure (existing dose estimate, restyled)             │
│ Health recommendations (streamed AI text, in a card)         │
├──────────────────────────────────────────────────────────────┤
│ 2026 calendar heatmap (12 months, daily cells, colour scale) │
│ [Download PDF report]                                        │
└──────────────────────────────────────────────────────────────┘
```

- Dark base; the page background is a radial gradient tinted by the current category's
  colour (green on a clean day, orange/red/maroon on bad days). Cards are translucent
  with a soft border/blur. Large, bold AQI number in the category colour.
- Interactive charts with a dark theme consistent with the cards (Plotly is the
  natural fit in Streamlit; the builder may choose otherwise).
- Before any analysis, show a short landing state (title, one-line pitch, example
  cities), not an empty page.
- Results persist across reruns (e.g. clicking download), as today.
- Existing 7-day personal history chart: keep only if it fits; the aqi.in 24h series
  is now the main trend chart.

### Keys and security

- Gradio: launch without `share=True` by default (opt-in flag/env var), and never
  pre-fill key fields with `.env` values in a shared UI; read keys from env server-side
  when the fields are empty.
- Streamlit: keys from `.env`/sidebar as today, but the sidebar must not echo `.env`
  values back into the page when a public deployment is used (keep simple: read from
  env if present, show only "key loaded from .env").
- `.env.example` stays; README tells the reader not to share `.env`.

### Testing

- Save the New Delhi scrape markdown as a fixture (keys scrubbed; it contains none).
  Unit tests for the parser (each section, plus missing-section cases), the AQI band
  mapping (e.g. 260 → Severe, 25 → Good), the best-window calculation, the dose maths,
  and URL candidate building.
- Manual check: run the Streamlit app for Delhi, Mumbai and one non-Indian city and
  confirm the numbers match aqi.in.

### README

Update features list, screenshots placeholder, run instructions (Streamlit as the main
app), and a short "what changed" section the grader can read.

## Left to the builder

- Package/module names, exact file split, chart library details.
- Exact parsing technique (regex vs table parsing) as long as it is tested against the
  fixture and degrades gracefully.
- Exact URL-discovery mechanism within Firecrawl's 1.9.0 SDK (upgrade the pin only if
  needed and say so).
- Precise colours, spacing and fonts within the chosen look.
- Whether the 7-day local history chart survives.
