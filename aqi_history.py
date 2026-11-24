"""SQLite-backed reading history so the trend chart survives restarts."""

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Optional

import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aqi_history.db")

SHARED_MINUTES = 45  # collapse repeated lookups for the same city
COLUMNS = ["observed_at", "aqi", "pm25", "pm10", "co", "temperature", "humidity", "wind_speed"]


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT NOT NULL,
                state TEXT,
                country TEXT,
                observed_at TEXT NOT NULL,
                aqi REAL, pm25 REAL, pm10 REAL, co REAL,
                temperature REAL, humidity REAL, wind_speed REAL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_readings_city_time "
            "ON readings (city, country, observed_at)"
        )


def save_reading(
    city: str,
    state: str,
    country: str,
    aqi_data: Dict[str, float],
    observed_at: Optional[datetime] = None,
) -> bool:
    """Store a reading; returns False when one was already saved recently."""
    if not city:
        return False

    init_db()
    observed_at = observed_at or datetime.now()
    cutoff = (observed_at - timedelta(minutes=SHARED_MINUTES)).isoformat(timespec="seconds")

    with _connect() as connection:
        recent = connection.execute(
            "SELECT 1 FROM readings WHERE city = ? AND country = ? AND observed_at >= ? LIMIT 1",
            (city.strip().lower(), (country or "").strip().lower(), cutoff),
        ).fetchone()
        if recent:
            return False

        connection.execute(
            """
            INSERT INTO readings (city, state, country, observed_at, aqi, pm25, pm10, co,
                                  temperature, humidity, wind_speed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                city.strip().lower(),
                (state or "").strip().lower(),
                (country or "").strip().lower(),
                observed_at.isoformat(timespec="seconds"),
                aqi_data.get("aqi"),
                aqi_data.get("pm25"),
                aqi_data.get("pm10"),
                aqi_data.get("co"),
                aqi_data.get("temperature"),
                aqi_data.get("humidity"),
                aqi_data.get("wind_speed"),
            ),
        )
    return True


def get_history(
    city: str,
    state: str = "",
    country: str = "",
    days: int = 7,
) -> pd.DataFrame:
    """Readings for a city over the last N days, oldest first, ready for a line chart."""
    init_db()
    if not city:
        return pd.DataFrame(columns=COLUMNS)

    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT observed_at, aqi, pm25, pm10, co, temperature, humidity, wind_speed
            FROM readings
            WHERE city = ? AND country = ? AND observed_at >= ?
            ORDER BY observed_at ASC
            """,
            (city.strip().lower(), (country or "").strip().lower(), cutoff),
        ).fetchall()

    if not rows:
        return pd.DataFrame(columns=COLUMNS)

    frame = pd.DataFrame([dict(row) for row in rows])
    frame["observed_at"] = pd.to_datetime(frame["observed_at"])
    return frame
