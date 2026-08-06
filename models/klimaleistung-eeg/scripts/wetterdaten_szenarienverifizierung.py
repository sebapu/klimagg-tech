#!/usr/bin/env python3
# Copyright (c) 2026 Sebastian Putzke
# SPDX-License-Identifier: Apache-2.0
"""Wetterdaten, literaturnormierte 1-MW-Szenarien und Verifikationsgrafiken.

Dieses Skript ist bewusst von der EEG-/Artikelgrafik getrennt. Es

1. liest vollständige Kalenderjahre aus einer vorhandenen SMARD-SQLite,
2. lädt fehlende Wetterstunden über Meteostat,
3. speichert Wetter, Modellannahmen und Szenario-Zeitreihen in genau einer
   SQLite-Datei,
4. berechnet rohe PV- und Windprofile je 1 MW installierter Leistung,
5. kalibriert jedes Kalenderjahr transparent auf dokumentierte Literaturwerte,
6. berechnet die rechnerische THG-Verdrängung mit dem stündlichen fossilen
   SMARD-Restmix und
7. erzeugt sofort separate Verifikationsgrafiken und Prüftabellen.

Die Rohprofile bleiben vollständig erhalten. Datenbank, CSV, Bericht und
Grafiken weisen Rohwert, Zielwert, Kalibrierungsmodus, Faktor und Quelle aus.
PV wird auf 1 MWp DC, Wind auf 1 MW Nennleistung bezogen. Bei PV wird die
Leistung mit physischer AC-Grenze skaliert; bei Wind wird die zugrunde liegende
Windgeschwindigkeit kalibriert. Beides sichert nur die Jahressumme und ersetzt
keine Verifikation der zeitlichen Profilform.

Es gibt keine Batterieoptimierung, keine EEG-Auswertung und keinen bleibenden
Meteostat-Zweitcache. Der interne Download-Cache von Meteostat liegt nur in
einem temporären Verzeichnis und wird nach dem Abruf entfernt.

Installation in einer virtuellen Umgebung:

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install numpy pandas matplotlib pvlib meteostat

Beispiel:

    python wetterdaten_szenarienverifizierung.py \
      --smard-db smard_stundendaten_2021_2025.sqlite \
      --years 2025
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

try:
    import numpy as np
    import pandas as pd
except ImportError as exc:  # pragma: no cover - nur für verständliche CLI-Fehler
    raise SystemExit(
        "Abhängigkeit fehlt. Aktiviere die Projekt-.venv und installiere: "
        "python -m pip install numpy pandas matplotlib pvlib meteostat"
    ) from exc


SCRIPT_DIR = Path(__file__).resolve().parent
MODEL_VERSION = "2.2.1"
LOCAL_TIMEZONE = "Europe/Berlin"


@dataclass(frozen=True)
class Site:
    name: str
    latitude: float
    longitude: float
    elevation_m: float

    @property
    def site_id(self) -> str:
        clean = re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_")
        return (
            f"{clean or 'standort'}_"
            f"{self.latitude:.4f}_{self.longitude:.4f}_{self.elevation_m:.0f}"
        )


@dataclass
class SmardData:
    timestamp_ms: np.ndarray
    timestamp_berlin: list[str]
    year: np.ndarray
    pv_mwh: np.ndarray
    wind_onshore_mwh: np.ndarray
    fossil_restmix_t_co2e_per_mwh: np.ndarray
    pv_capacity_mw: np.ndarray | None = None
    wind_onshore_capacity_mw: np.ndarray | None = None


@dataclass
class WeatherData:
    temp_c: np.ndarray
    wind_10m_ms: np.ndarray
    pressure_hpa_msl: np.ndarray
    sunshine_min: np.ndarray
    cloud_okta: np.ndarray
    imputed_temp: np.ndarray
    imputed_wind: np.ndarray
    imputed_pressure: np.ndarray
    imputed_cloud: np.ndarray


# PV-Bezugsleistung ist 1 MWp DC. Bei einem DC/AC-Verhältnis von 1,15 beträgt
# die Wechselrichterleistung 0,8696 MW AC je MWp.
PV_DC_MWP = 1.0
PV_DC_AC_RATIO = 1.15
PV_AC_MW_PER_MWP = PV_DC_MWP / PV_DC_AC_RATIO
PV_SYSTEM_LOSS = 0.14
PV_GAMMA_PDC = -0.0035
PV_INVERTER_EFFICIENCY = 0.965

WIND_MEASUREMENT_HEIGHT_M = 10.0
WIND_SHEAR_EXPONENT = 0.18
WIND_CUT_IN_MS = 3.0
WIND_CUT_OUT_MS = 25.0
WIND_AVAILABILITY_AND_WAKE = 0.88

# Primärenergiebezogene THG-Faktoren der fossilen Stromerzeugung. Braunkohle,
# Steinkohle und Erdgas: UBA Emissionsbilanz 2024, Tabelle 6, geteilt durch
# die dortigen mittleren Brutto-Nutzungsgrade. "Sonstige Konventionelle" ist
# in SMARD nicht hinreichend aufgeschlüsselt; als transparenter Proxy wird
# der UBA-Faktor für leichtes Heizöl verwendet (312,70 g/kWh Primärenergie,
# 38,3 % mittlerer Brutto-Nutzungsgrad).
FOSSIL_EMISSIONS_T_CO2E_MWH = {
    "lignite": 0.40903 / 0.397,
    "hard_coal": 0.38251 / 0.436,
    "gas": 0.24773 / 0.566,
    "other_conventional": 0.31270 / 0.383,
}

# Konservative Bestandsfaktoren aus der UBA-Emissionsbilanz 2024. Sie werden
# als eigener Abzug ausgewiesen. Für eine Veröffentlichung über Neuanlagen
# sollte zusätzlich eine Sensitivität mit modernen Anlagen-LCA geführt werden.
LIFECYCLE_G_CO2E_KWH = {"pv": 56.49, "wind": 17.58}

PVGIS_REFERENCE_URL = (
    "https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-"
    "information-system-pvgis/using-pvgis-5/api-non-interactive-service_en"
)
WINDGUARD_REFERENCE_URL = (
    "https://www.windguard.de/veroeffentlichungen.html?file=files%2Fcto_layout%"
    "2Fimg%2Funternehmen%2Fveroeffentlichungen%2F2026%2FVolllaststunden+von+"
    "Windenergieanlagen+an+Land.pdf"
)
UBA_REFERENCE_URL = (
    "https://www.umweltbundesamt.de/system/files/medien/11850/publikationen/"
    "2026-01/11_2026_CC.pdf"
)
SMARD_REFERENCE_URL = "https://www.bundesnetzagentur.de/1087156"

SCENARIOS = {
    "pv_sued_30": {
        "label": "PV Süd 30°",
        "technology": "pv",
        "tilt_deg": 30.0,
        "east_west": False,
        "capacity_basis": "MWp DC",
        "target_mwh_per_mw": 1009.52,
        "target_source": "PVGIS 5.3 SARAH3, Kassel, 2005–2023, 14 % Verluste",
        "target_definition": (
            "PVGIS PVcalc: peakpower=1 kWp, loss=14 %, angle=30°, "
            "aspect=0° (Süd), raddatabase=PVGIS-SARAH3"
        ),
        "target_url": PVGIS_REFERENCE_URL,
    },
    "pv_sued_60": {
        "label": "PV Süd 60°",
        "technology": "pv",
        "tilt_deg": 60.0,
        "east_west": False,
        "capacity_basis": "MWp DC",
        "target_mwh_per_mw": 963.43,
        "target_source": "PVGIS 5.3 SARAH3, Kassel, 2005–2023, 14 % Verluste",
        "target_definition": (
            "PVGIS PVcalc: peakpower=1 kWp, loss=14 %, angle=60°, "
            "aspect=0° (Süd), raddatabase=PVGIS-SARAH3"
        ),
        "target_url": PVGIS_REFERENCE_URL,
    },
    "pv_ost_west_15": {
        "label": "PV Ost–West 15°",
        "technology": "pv",
        "tilt_deg": 15.0,
        "east_west": True,
        "capacity_basis": "MWp DC",
        "target_mwh_per_mw": 847.16,
        "target_source": (
            "PVGIS 5.3 SARAH3, Mittel Ost/West, Kassel, 2005–2023, 14 % Verluste"
        ),
        "target_definition": (
            "Gleich große DC-Anteile; arithmetisches Mittel zweier PVGIS-PVcalc-"
            "Läufe mit peakpower=1 kWp, loss=14 %, angle=15°, "
            "aspect=-90°/+90°, raddatabase=PVGIS-SARAH3"
        ),
        "target_url": PVGIS_REFERENCE_URL,
    },
    "pv_ost_west_30": {
        "label": "PV Ost–West 30°",
        "technology": "pv",
        "tilt_deg": 30.0,
        "east_west": True,
        "capacity_basis": "MWp DC",
        "target_mwh_per_mw": 821.66,
        "target_source": (
            "PVGIS 5.3 SARAH3, Mittel Ost/West, Kassel, 2005–2023, 14 % Verluste"
        ),
        "target_definition": (
            "Gleich große DC-Anteile; arithmetisches Mittel zweier PVGIS-PVcalc-"
            "Läufe mit peakpower=1 kWp, loss=14 %, angle=30°, "
            "aspect=-90°/+90°, raddatabase=PVGIS-SARAH3"
        ),
        "target_url": PVGIS_REFERENCE_URL,
    },
    "wind_standard": {
        "label": "Wind Standardanlage",
        "technology": "wind",
        "hub_height_m": 140.0,
        "rated_ms": 11.5,
        "capacity_basis": "MW Nennleistung",
        "target_mwh_per_mw": 2050.0,
        "target_source": (
            "Deutsche WindGuard 2026, Region Mitte: rund 2.090 langzeit- und "
            "netzkorrigierte Volllaststunden; rund 2 % Netzausfallkorrektur "
            "für den marktseitig zugänglichen Ertrag wieder abgezogen"
        ),
        "target_definition": (
            "2.090 h / 1,02 = rund 2.050 h. Damit wird nicht die rechnerisch "
            "zurückgerechnete Erzeugung ohne Netzengpässe, sondern der tatsächlich "
            "einspeisbare und am Markt bewertbare Jahresertrag verwendet."
        ),
        "target_url": WINDGUARD_REFERENCE_URL,
    },
    "wind_schwachwind": {
        "label": "Wind Schwachwindanlage",
        "technology": "wind",
        "hub_height_m": 160.0,
        "rated_ms": 9.5,
        "capacity_basis": "MW Nennleistung",
        "target_mwh_per_mw": 2300.0,
        "target_source": (
            "Deutsche WindGuard 2026: Senkung der spezifischen Flächenleistung "
            "von 300 auf 250 W/m² erhöht Volllaststunden um rund 12 %"
        ),
        "target_definition": (
            "2.050 h × 1,12 = 2.296 h, auf 2.300 MWh/MW gerundet. Die "
            "Schwachwindanlage ist eine Literatur-Sensitivität zur geringeren "
            "spezifischen Flächenleistung, kein Ertragsversprechen für ein Einzelprojekt."
        ),
        "target_url": WINDGUARD_REFERENCE_URL,
    },
}

REFERENCE_TOLERANCE_PCT = 10.0

COLORS = {
    "pv_sued_30": "#D5A800",
    "pv_sued_60": "#E07B24",
    "pv_ost_west_15": "#8A7D00",
    "pv_ost_west_30": "#B5671F",
    "wind_standard": "#6B91B7",
    "wind_schwachwind": "#24527A",
    "smard_pv": "#F2C230",
    "smard_wind": "#4C78A8",
}


def parse_years(text: str) -> list[int]:
    """Akzeptiert 2024, 2021-2025 oder 2021,2023,2024."""
    years: set[int] = set()
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            first, last = token.split("-", 1)
            start, end = int(first), int(last)
            if end < start:
                raise ValueError(f"Ungültiger Jahresbereich: {token}")
            years.update(range(start, end + 1))
        else:
            years.add(int(token))
    result = sorted(years)
    if not result or any(year < 2015 or year > 2100 for year in result):
        raise ValueError("Keine plausiblen Jahre angegeben.")
    return result


def expected_local_timestamps_ms(year: int) -> np.ndarray:
    """UTC-Stunden, die ein vollständiges deutsches Kalenderjahr abdecken."""
    berlin = ZoneInfo(LOCAL_TIMEZONE)
    start = datetime(year, 1, 1, tzinfo=berlin).astimezone(timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=berlin).astimezone(timezone.utc)
    return np.arange(
        int(start.timestamp() * 1000),
        int(end.timestamp() * 1000),
        3_600_000,
        dtype=np.int64,
    )


def expected_timestamps_for_years(years: Iterable[int]) -> np.ndarray:
    return np.concatenate([expected_local_timestamps_ms(year) for year in years])


def sqlite_integrity(path: Path, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{label} fehlt: {path}")
    con = sqlite3.connect(path)
    try:
        result = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    if result != "ok":
        raise RuntimeError(f"{label} ist beschädigt: {result}")


def _capacity_columns(con: sqlite3.Connection) -> tuple[str | None, str | None]:
    columns = {row[1] for row in con.execute("PRAGMA table_info(hourly)")}
    pv_candidates = ("pv_capacity_mw", "solar_capacity_mw")
    wind_candidates = ("wind_onshore_capacity_mw", "wind_land_capacity_mw")
    pv = next((name for name in pv_candidates if name in columns), None)
    wind = next((name for name in wind_candidates if name in columns), None)
    return pv, wind


def load_smard(path: Path, years: list[int]) -> SmardData:
    """Liest reale Stundenwerte; unvollständige Jahre werden abgelehnt."""
    sqlite_integrity(path, "SMARD-Datenbank")
    con = sqlite3.connect(path)
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "hourly" not in tables:
            raise RuntimeError("SMARD-Datenbank enthält keine Tabelle 'hourly'.")
        columns = {row[1] for row in con.execute("PRAGMA table_info(hourly)")}
        required = {
            "timestamp_ms",
            "timestamp_berlin",
            "local_year",
            "pv_mwh",
            "wind_onshore_mwh",
            "lignite_mwh",
            "hard_coal_mwh",
            "gas_mwh",
            "other_conventional_mwh",
        }
        missing = sorted(required - columns)
        if missing:
            raise RuntimeError(
                "SMARD-Tabelle hourly: Spalten fehlen: " + ", ".join(missing)
            )
        pv_capacity_col, wind_capacity_col = _capacity_columns(con)
        select = [
            "timestamp_ms",
            "timestamp_berlin",
            "local_year",
            "pv_mwh",
            "wind_onshore_mwh",
            "lignite_mwh",
            "hard_coal_mwh",
            "gas_mwh",
            "other_conventional_mwh",
        ]
        if pv_capacity_col:
            select.append(pv_capacity_col)
        if wind_capacity_col:
            select.append(wind_capacity_col)
        placeholders = ",".join("?" for _ in years)
        rows = con.execute(
            f"SELECT {','.join(select)} FROM hourly "
            f"WHERE local_year IN ({placeholders}) ORDER BY timestamp_ms",
            years,
        ).fetchall()
    finally:
        con.close()
    if not rows:
        raise RuntimeError("Für die gewählten Jahre enthält SMARD keine Daten.")

    timestamps = np.asarray([int(row[0]) for row in rows], dtype=np.int64)
    expected = expected_timestamps_for_years(years)
    if not np.array_equal(timestamps, expected):
        details = []
        for year in years:
            actual_n = sum(int(row[2]) == year for row in rows)
            expected_n = len(expected_local_timestamps_ms(year))
            if actual_n != expected_n:
                details.append(f"{year}: {actual_n}/{expected_n} Stunden")
        raise RuntimeError(
            "SMARD-Jahre sind unvollständig oder nicht lückenlos. "
            + ("; ".join(details) or "Zeitstempel weichen ab.")
            + " Es wird nichts hochgerechnet."
        )

    numeric = np.asarray(
        [[row[2], row[3], row[4], row[5], row[6], row[7], row[8]] for row in rows],
        dtype=float,
    )
    if np.any(~np.isfinite(numeric)) or np.any(numeric[:, 1:] < 0):
        raise RuntimeError("SMARD enthält ungültige oder negative Erzeugungswerte.")

    fossil = numeric[:, 3:].sum(axis=1)
    fossil_emissions = (
        numeric[:, 3] * FOSSIL_EMISSIONS_T_CO2E_MWH["lignite"]
        + numeric[:, 4] * FOSSIL_EMISSIONS_T_CO2E_MWH["hard_coal"]
        + numeric[:, 5] * FOSSIL_EMISSIONS_T_CO2E_MWH["gas"]
        + numeric[:, 6] * FOSSIL_EMISSIONS_T_CO2E_MWH["other_conventional"]
    )
    fossil_factor = np.divide(
        fossil_emissions,
        fossil,
        out=np.zeros_like(fossil_emissions),
        where=fossil > 0,
    )

    next_index = 9
    pv_capacity = None
    wind_capacity = None
    if pv_capacity_col:
        pv_capacity = np.asarray([row[next_index] for row in rows], dtype=float)
        next_index += 1
    if wind_capacity_col:
        wind_capacity = np.asarray([row[next_index] for row in rows], dtype=float)
    for label, values in (
        ("PV-Kapazität", pv_capacity),
        ("Wind-Kapazität", wind_capacity),
    ):
        if values is not None and (
            np.any(~np.isfinite(values)) or np.any(values <= 0)
        ):
            raise RuntimeError(f"{label} in SMARD ist ungültig.")

    return SmardData(
        timestamp_ms=timestamps,
        timestamp_berlin=[str(row[1]) for row in rows],
        year=numeric[:, 0].astype(int),
        pv_mwh=numeric[:, 1],
        wind_onshore_mwh=numeric[:, 2],
        fossil_restmix_t_co2e_per_mwh=fossil_factor,
        pv_capacity_mw=pv_capacity,
        wind_onshore_capacity_mw=wind_capacity,
    )


def open_scenario_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS weather_hourly(
          site_id TEXT NOT NULL,
          timestamp_ms INTEGER NOT NULL,
          temp_c REAL NOT NULL,
          wind_10m_ms REAL NOT NULL,
          pressure_hpa REAL NOT NULL,
          sunshine_min REAL,
          cloud_okta REAL NOT NULL,
          PRIMARY KEY(site_id, timestamp_ms)
        );
        CREATE TABLE IF NOT EXISTS weather_quality(
          site_id TEXT NOT NULL,
          timestamp_ms INTEGER NOT NULL,
          temp_imputed INTEGER NOT NULL,
          wind_imputed INTEGER NOT NULL,
          pressure_imputed INTEGER NOT NULL,
          cloud_imputed INTEGER NOT NULL,
          PRIMARY KEY(site_id, timestamp_ms)
        );
        CREATE TABLE IF NOT EXISTS scenario_definition(
          scenario_id TEXT PRIMARY KEY,
          label TEXT NOT NULL,
          technology TEXT NOT NULL,
          installed_capacity_mw REAL NOT NULL,
          model_version TEXT NOT NULL,
          parameters_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scenario_hourly(
          scenario_id TEXT NOT NULL,
          site_id TEXT NOT NULL,
          timestamp_ms INTEGER NOT NULL,
          generation_mwh_per_mw REAL NOT NULL,
          raw_generation_mwh_per_mw REAL,
          normalization_factor REAL,
          normalization_target_mwh_per_mw REAL,
          PRIMARY KEY(scenario_id, site_id, timestamp_ms),
          FOREIGN KEY(scenario_id) REFERENCES scenario_definition(scenario_id)
        );
        CREATE TABLE IF NOT EXISTS verification_summary(
          year INTEGER NOT NULL,
          scenario_id TEXT NOT NULL,
          site_id TEXT NOT NULL,
          hours INTEGER NOT NULL,
          energy_mwh_per_mw REAL NOT NULL,
          raw_energy_mwh_per_mw REAL,
          target_energy_mwh_per_mw REAL,
          normalization_factor REAL,
          normalized_deviation_pct REAL,
          clipped_hours INTEGER,
          capacity_factor REAL NOT NULL,
          maximum_mw_per_mw REAL NOT NULL,
          zero_hours INTEGER NOT NULL,
          smard_hourly_correlation REAL,
          smard_monthly_share_mae_pp REAL,
          lifecycle_g_co2e_kwh REAL,
          gross_avoided_t_co2e_per_mw REAL,
          lifecycle_t_co2e_per_mw REAL,
          net_avoided_t_co2e_per_mw REAL,
          smard_shape_gross_avoided_t_co2e_per_mw REAL,
          thg_profile_delta_pct REAL,
          validation_status TEXT,
          normalization_source TEXT,
          reference_mode TEXT NOT NULL,
          PRIMARY KEY(year, scenario_id, site_id),
          FOREIGN KEY(scenario_id) REFERENCES scenario_definition(scenario_id)
        );
        CREATE TABLE IF NOT EXISTS validation(
          check_id TEXT PRIMARY KEY,
          status TEXT NOT NULL,
          value TEXT NOT NULL,
          note TEXT NOT NULL
        );
        """
    )
    # Rückwärtskompatible Erweiterung bereits vorhandener Ergebnisdatenbanken.
    migrations = {
        "scenario_hourly": {
            "raw_generation_mwh_per_mw": "REAL",
            "normalization_factor": "REAL",
            "normalization_target_mwh_per_mw": "REAL",
        },
        "verification_summary": {
            "raw_energy_mwh_per_mw": "REAL",
            "target_energy_mwh_per_mw": "REAL",
            "normalization_factor": "REAL",
            "normalized_deviation_pct": "REAL",
            "clipped_hours": "INTEGER",
            "lifecycle_g_co2e_kwh": "REAL",
            "gross_avoided_t_co2e_per_mw": "REAL",
            "lifecycle_t_co2e_per_mw": "REAL",
            "net_avoided_t_co2e_per_mw": "REAL",
            "smard_shape_gross_avoided_t_co2e_per_mw": "REAL",
            "thg_profile_delta_pct": "REAL",
            "validation_status": "TEXT",
            "normalization_source": "TEXT",
        },
    }
    for table, additions in migrations.items():
        present = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
        for column, declaration in additions.items():
            if column not in present:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    con.commit()
    return con


def _normalise_meteostat_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [
        str(getattr(column, "value", column)).lower() for column in frame.columns
    ]
    return frame


def fetch_meteostat(
    site: Site, timestamps_ms: np.ndarray
) -> tuple[pd.DataFrame, list[str]]:
    """Lädt Meteostat in ein flüchtiges Downloadverzeichnis."""
    try:
        import meteostat as ms
    except ImportError as exc:
        raise RuntimeError(
            "Meteostat fehlt. In der aktivierten .venv ausführen: "
            "python -m pip install meteostat"
        ) from exc

    start = datetime.fromtimestamp(int(timestamps_ms[0]) / 1000, timezone.utc)
    end = datetime.fromtimestamp(int(timestamps_ms[-1]) / 1000, timezone.utc)
    point = ms.Point(site.latitude, site.longitude, site.elevation_m)

    with tempfile.TemporaryDirectory(prefix="meteostat_download_") as tmp:
        old_cache = getattr(ms.config, "cache_directory", None)
        old_station_db = getattr(ms.config, "stations_db_file", None)
        ms.config.cache_directory = str(Path(tmp) / "data")
        if hasattr(ms.config, "stations_db_file"):
            ms.config.stations_db_file = str(Path(tmp) / "stations.db")
        try:
            stations = ms.stations.nearby(point, limit=4)
            if stations is None or len(stations) < 2:
                raise RuntimeError(
                    "Meteostat findet weniger als zwei geeignete Wetterstationen."
                )
            station_ids = [str(value) for value in getattr(stations, "index", [])]
            parameters = [
                ms.Parameter.TEMP,
                ms.Parameter.WSPD,
                ms.Parameter.PRES,
                ms.Parameter.TSUN,
                ms.Parameter.CLDC,
            ]
            series = ms.hourly(
                stations,
                start.replace(tzinfo=None),
                end.replace(tzinfo=None),
                timezone="UTC",
                parameters=parameters,
            )
            frame = ms.interpolate(series, point).fetch()
        finally:
            if old_cache is not None:
                ms.config.cache_directory = old_cache
            if old_station_db is not None and hasattr(ms.config, "stations_db_file"):
                ms.config.stations_db_file = old_station_db

    if frame is None or frame.empty:
        raise RuntimeError("Meteostat hat keine Wetterdaten geliefert.")
    frame = _normalise_meteostat_columns(frame)
    index = pd.DatetimeIndex(frame.index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    frame.index = index
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return frame, station_ids


def complete_weather_frame(
    raw: pd.DataFrame, timestamps_ms: np.ndarray
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    expected_index = pd.to_datetime(timestamps_ms, unit="ms", utc=True)
    required = ["temp", "wspd", "pres", "cldc"]
    missing_columns = [column for column in required if column not in raw.columns]
    if missing_columns:
        raise RuntimeError(
            "Meteostat liefert notwendige Spalten nicht: "
            + ", ".join(missing_columns)
        )
    frame = raw.reindex(expected_index)
    if "tsun" not in frame.columns:
        frame["tsun"] = np.nan
    frame = frame[["temp", "wspd", "pres", "tsun", "cldc"]].apply(
        pd.to_numeric, errors="coerce"
    )
    quality: dict[str, np.ndarray] = {}
    for column in required:
        missing_before = frame[column].isna()
        quality[column] = missing_before.to_numpy(dtype=bool)
        # Nur kurze Messlücken werden zeitlich geschlossen. Keine
        # Jahreserträge oder Anlagenwerte werden skaliert.
        frame[column] = frame[column].interpolate(
            method="time", limit=6, limit_direction="both"
        )
    still_missing = {column: int(frame[column].isna().sum()) for column in required}
    still_missing = {key: value for key, value in still_missing.items() if value}
    if still_missing:
        detail = ", ".join(f"{key}={value}" for key, value in still_missing.items())
        raise RuntimeError(
            "Wetterdaten bleiben nach räumlicher Interpolation und dem "
            f"Schließen kurzer Lücken unvollständig: {detail}."
        )

    checks = {
        "temp": (-50.0, 50.0),
        "wspd": (0.0, 180.0),  # Meteostat in km/h
        "pres": (850.0, 1100.0),
        "cldc": (0.0, 8.0),
        "tsun": (0.0, 60.0),
    }
    for column, (lower, upper) in checks.items():
        values = frame[column].dropna()
        if len(values) and ((values < lower).any() or (values > upper).any()):
            raise RuntimeError(
                f"Meteostat-Spalte {column} außerhalb {lower} bis {upper}."
            )
    return frame, quality


def ensure_weather(
    database: Path,
    site: Site,
    timestamps_ms: np.ndarray,
    *,
    offline: bool,
    refresh: bool,
) -> WeatherData:
    """Liest oder ergänzt Wetterdaten in genau einer Ergebnisdatenbank."""
    con = open_scenario_db(database)
    start_ms, end_ms = int(timestamps_ms[0]), int(timestamps_ms[-1])
    try:
        if refresh:
            con.execute(
                "DELETE FROM weather_hourly WHERE site_id=? "
                "AND timestamp_ms BETWEEN ? AND ?",
                (site.site_id, start_ms, end_ms),
            )
            con.execute(
                "DELETE FROM weather_quality WHERE site_id=? "
                "AND timestamp_ms BETWEEN ? AND ?",
                (site.site_id, start_ms, end_ms),
            )
            con.commit()
        present = {
            int(row[0])
            for row in con.execute(
                "SELECT timestamp_ms FROM weather_hourly WHERE site_id=? "
                "AND timestamp_ms BETWEEN ? AND ?",
                (site.site_id, start_ms, end_ms),
            )
        }
        missing = [int(value) for value in timestamps_ms if int(value) not in present]
        if missing:
            if offline:
                raise RuntimeError(
                    f"Datenbank enthält {len(missing)} Wetterstunden nicht; "
                    "--offline verhindert den Meteostat-Abruf."
                )
            print(f"Meteostat: {len(missing)} Wetterstunden werden geladen …")
            raw, stations = fetch_meteostat(site, timestamps_ms)
            frame, quality = complete_weather_frame(raw, timestamps_ms)
            rows = []
            quality_rows = []
            for index, timestamp in enumerate(timestamps_ms):
                if int(timestamp) not in missing:
                    continue
                row = frame.iloc[index]
                sunshine = None if pd.isna(row["tsun"]) else float(row["tsun"])
                rows.append(
                    (
                        site.site_id,
                        int(timestamp),
                        float(row["temp"]),
                        float(row["wspd"]) / 3.6,
                        float(row["pres"]),
                        sunshine,
                        float(row["cldc"]),
                    )
                )
                quality_rows.append(
                    (
                        site.site_id,
                        int(timestamp),
                        int(quality["temp"][index]),
                        int(quality["wspd"][index]),
                        int(quality["pres"][index]),
                        int(quality["cldc"][index]),
                    )
                )
            with con:
                con.executemany(
                    "INSERT OR REPLACE INTO weather_hourly VALUES (?,?,?,?,?,?,?)",
                    rows,
                )
                con.executemany(
                    "INSERT OR REPLACE INTO weather_quality VALUES (?,?,?,?,?,?)",
                    quality_rows,
                )
                metadata = {
                    "model_version": MODEL_VERSION,
                    "site": {
                        "id": site.site_id,
                        "name": site.name,
                        "latitude": site.latitude,
                        "longitude": site.longitude,
                        "elevation_m": site.elevation_m,
                    },
                    "meteostat_stations": stations,
                    "meteostat_method": (
                        "räumliche Interpolation aus bis zu vier nahen Stationen; "
                        "zeitliche Interpolation nur für Lücken bis sechs Stunden"
                    ),
                }
                for key, value in metadata.items():
                    con.execute(
                        "INSERT OR REPLACE INTO metadata VALUES (?,?)",
                        (key, json.dumps(value, ensure_ascii=False)),
                    )

        rows = con.execute(
            "SELECT w.timestamp_ms,w.temp_c,w.wind_10m_ms,w.pressure_hpa,"
            "w.sunshine_min,w.cloud_okta,"
            "COALESCE(q.temp_imputed,0),COALESCE(q.wind_imputed,0),"
            "COALESCE(q.pressure_imputed,0),COALESCE(q.cloud_imputed,0) "
            "FROM weather_hourly w LEFT JOIN weather_quality q "
            "ON q.site_id=w.site_id AND q.timestamp_ms=w.timestamp_ms "
            "WHERE w.site_id=? AND w.timestamp_ms BETWEEN ? AND ? "
            "ORDER BY w.timestamp_ms",
            (site.site_id, start_ms, end_ms),
        ).fetchall()
    finally:
        con.close()

    by_timestamp = {int(row[0]): row[1:] for row in rows}
    missing_after = [int(value) for value in timestamps_ms if int(value) not in by_timestamp]
    if missing_after:
        raise RuntimeError(
            f"Wetterdatenbank bleibt unvollständig: {len(missing_after)} Stunden."
        )
    ordered = [by_timestamp[int(value)] for value in timestamps_ms]
    values = np.asarray(
        [
            [row[0], row[1], row[2], np.nan if row[3] is None else row[3], row[4]]
            for row in ordered
        ],
        dtype=float,
    )
    flags = np.asarray([row[5:] for row in ordered], dtype=int)
    return WeatherData(
        temp_c=values[:, 0],
        wind_10m_ms=values[:, 1],
        pressure_hpa_msl=values[:, 2],
        sunshine_min=values[:, 3],
        cloud_okta=values[:, 4],
        imputed_temp=flags[:, 0].astype(bool),
        imputed_wind=flags[:, 1].astype(bool),
        imputed_pressure=flags[:, 2].astype(bool),
        imputed_cloud=flags[:, 3].astype(bool),
    )


def pv_profiles(
    site: Site, weather: WeatherData, timestamps_ms: np.ndarray
) -> dict[str, np.ndarray]:
    try:
        import pvlib
    except ImportError as exc:
        raise RuntimeError(
            "pvlib fehlt. In der aktivierten .venv ausführen: "
            "python -m pip install pvlib"
        ) from exc

    times = pd.to_datetime(timestamps_ms, unit="ms", utc=True)
    midpoints = times + pd.Timedelta(minutes=30)
    location = pvlib.location.Location(
        site.latitude, site.longitude, tz="UTC", altitude=site.elevation_m
    )
    solar_position = location.get_solarposition(midpoints)
    clear = location.get_clearsky(midpoints, model="ineichen")
    cloud_fraction = np.clip(weather.cloud_okta / 8.0, 0.0, 1.0)
    # Kasten-Czeplak: klarer Himmel wird mit beobachteter Bewölkung gedämpft.
    transmittance = 1.0 - 0.75 * np.power(cloud_fraction, 3.4)
    ghi = np.maximum(np.asarray(clear["ghi"], dtype=float) * transmittance, 0.0)
    decomposition = pvlib.irradiance.erbs(
        ghi,
        np.asarray(solar_position["zenith"], dtype=float),
        midpoints.dayofyear,
    )
    dni = np.maximum(
        np.nan_to_num(np.asarray(decomposition["dni"], dtype=float), nan=0.0),
        0.0,
    )
    dhi = np.maximum(
        np.nan_to_num(np.asarray(decomposition["dhi"], dtype=float), nan=0.0),
        0.0,
    )
    total_dc_w = PV_DC_MWP * 1_000_000.0

    def dc_surface(tilt: float, azimuth: float, dc_w: float) -> np.ndarray:
        poa = pvlib.irradiance.get_total_irradiance(
            surface_tilt=tilt,
            surface_azimuth=azimuth,
            solar_zenith=np.asarray(solar_position["zenith"], dtype=float),
            solar_azimuth=np.asarray(solar_position["azimuth"], dtype=float),
            dni=dni,
            ghi=ghi,
            dhi=dhi,
            model="isotropic",
        )["poa_global"]
        poa = np.maximum(np.nan_to_num(np.asarray(poa), nan=0.0), 0.0)
        cell_temperature = pvlib.temperature.faiman(
            poa, weather.temp_c, np.maximum(weather.wind_10m_ms, 0.1)
        )
        return np.maximum(
            np.asarray(
                pvlib.pvsystem.pvwatts_dc(
                    poa,
                    cell_temperature,
                    pdc0=dc_w,
                    gamma_pdc=PV_GAMMA_PDC,
                )
            ),
            0.0,
        )

    result: dict[str, np.ndarray] = {}
    for scenario_id, spec in SCENARIOS.items():
        if spec["technology"] != "pv":
            continue
        tilt = float(spec["tilt_deg"])
        if bool(spec["east_west"]):
            pdc = dc_surface(tilt, 90.0, total_dc_w / 2.0)
            pdc += dc_surface(tilt, 270.0, total_dc_w / 2.0)
        else:
            pdc = dc_surface(tilt, 180.0, total_dc_w)
        pdc *= 1.0 - PV_SYSTEM_LOSS
        inverter_dc_limit = (
            PV_AC_MW_PER_MWP * 1_000_000.0 / PV_INVERTER_EFFICIENCY
        )
        pac = pvlib.inverter.pvwatts(
            pdc,
            inverter_dc_limit,
            eta_inv_nom=PV_INVERTER_EFFICIENCY,
        )
        # Eine Stundenleistung in MW entspricht in der Stunde derselben MWh-Zahl.
        result[scenario_id] = np.clip(
            np.maximum(np.nan_to_num(np.asarray(pac), nan=0.0), 0.0) / 1_000_000,
            0.0,
            PV_AC_MW_PER_MWP,
        )
    return result


def wind_equivalent_speed(
    site: Site, weather: WeatherData, *, hub_height_m: float
) -> np.ndarray:
    """Windgeschwindigkeit auf Nabenhöhe und Standardluftdichte bezogen."""
    wind_hub = np.maximum(weather.wind_10m_ms, 0.0) * (
        hub_height_m / WIND_MEASUREMENT_HEIGHT_M
    ) ** WIND_SHEAR_EXPONENT
    temperature_k = np.maximum(weather.temp_c + 273.15, 220.0)
    # Meteostat PRES ist auf Meereshöhe bezogen. Barometrische Korrektur auf
    # Standortniveau, bevor die Luftdichte berechnet wird.
    site_pressure_pa = weather.pressure_hpa_msl * 100.0 * np.exp(
        -9.80665 * site.elevation_m / (287.05 * temperature_k)
    )
    density = site_pressure_pa / (287.05 * temperature_k)
    return wind_hub * np.power(
        np.maximum(density, 0.5) / 1.225, 1.0 / 3.0
    )


def wind_power_from_speed(
    equivalent_wind_ms: np.ndarray, *, rated_ms: float
) -> np.ndarray:
    """Generische 1-MW-Leistungskennlinie für eine vorgegebene Windreihe."""
    wind = np.maximum(np.asarray(equivalent_wind_ms, dtype=float), 0.0)
    power = np.zeros_like(wind)
    rising = (wind >= WIND_CUT_IN_MS) & (wind < rated_ms)
    power[rising] = (
        np.power(wind[rising], 3) - WIND_CUT_IN_MS**3
    ) / (rated_ms**3 - WIND_CUT_IN_MS**3)
    rated = (wind >= rated_ms) & (wind < WIND_CUT_OUT_MS)
    power[rated] = 1.0
    return np.clip(power * WIND_AVAILABILITY_AND_WAKE, 0.0, 1.0)


def wind_profile(
    site: Site,
    weather: WeatherData,
    *,
    hub_height_m: float,
    rated_ms: float,
    speed_scale: float = 1.0,
) -> np.ndarray:
    equivalent = wind_equivalent_speed(
        site, weather, hub_height_m=hub_height_m
    )
    return wind_power_from_speed(equivalent * speed_scale, rated_ms=rated_ms)


def build_scenarios(
    site: Site, weather: WeatherData, timestamps_ms: np.ndarray
) -> dict[str, np.ndarray]:
    profiles = pv_profiles(site, weather, timestamps_ms)
    for scenario_id, spec in SCENARIOS.items():
        if spec["technology"] != "wind":
            continue
        profiles[scenario_id] = wind_profile(
            site,
            weather,
            hub_height_m=float(spec["hub_height_m"]),
            rated_ms=float(spec["rated_ms"]),
        )
    for scenario_id, profile in profiles.items():
        if len(profile) != len(timestamps_ms):
            raise RuntimeError(f"{scenario_id}: falsche Zahl von Stundenwerten.")
        if np.any(~np.isfinite(profile)) or np.any(profile < -1e-10):
            raise RuntimeError(f"{scenario_id}: ungültige Stundenwerte.")
        cap = (
            PV_AC_MW_PER_MWP
            if SCENARIOS[scenario_id]["technology"] == "pv"
            else 1.0
        )
        if float(np.max(profile)) > cap + 1e-6:
            raise RuntimeError(
                f"{scenario_id}: Leistungsgrenze {cap:.4f} überschritten "
                f"({float(np.max(profile)):.3f})."
            )
        if float(np.sum(profile)) <= 0:
            raise RuntimeError(f"{scenario_id}: keine Erzeugung.")
    return profiles


def profile_cap(scenario_id: str) -> float:
    return (
        PV_AC_MW_PER_MWP
        if SCENARIOS[scenario_id]["technology"] == "pv"
        else 1.0
    )


def normalise_with_cap(
    values: np.ndarray, target_energy: float, cap: float
) -> tuple[np.ndarray, float, int]:
    """Skaliert eine Profilform auf die Zielenergie, ohne die Leistung zu reißen.

    Der Faktor wird per Bisektion bestimmt, weil das anschließende Kappen an der
    Anlagenleistung die Jahressumme nichtlinear verändert. Nullstunden bleiben
    Nullstunden. Die Funktion erfindet daher keine zusätzlichen Erzeugungszeiten.
    """
    raw = np.maximum(np.asarray(values, dtype=float), 0.0)
    if np.any(~np.isfinite(raw)) or float(raw.sum()) <= 0:
        raise RuntimeError("Normierung erhielt kein gültiges Erzeugungsprofil.")
    positive_hours = int(np.sum(raw > 0))
    maximum_energy = positive_hours * cap
    if target_energy > maximum_energy + 1e-8:
        raise RuntimeError(
            f"Zielertrag {target_energy:.1f} MWh ist mit {positive_hours} "
            f"positiven Stunden und Leistungsgrenze {cap:.4f} MW nicht erreichbar."
        )

    low = 0.0
    high = max(1.0, target_energy / float(raw.sum()))
    while float(np.minimum(raw * high, cap).sum()) < target_energy:
        high *= 2.0
        if high > 1e6:
            raise RuntimeError("Normierungsfaktor konnte nicht eingegrenzt werden.")
    for _ in range(80):
        middle = (low + high) / 2.0
        energy = float(np.minimum(raw * middle, cap).sum())
        if energy < target_energy:
            low = middle
        else:
            high = middle
    factor = (low + high) / 2.0
    normalized = np.minimum(raw * factor, cap)
    # Rundungsrest auf nicht gekappte positive Stunden verteilen.
    remainder = target_energy - float(normalized.sum())
    adjustable = (raw > 0) & (normalized < cap - 1e-12)
    if abs(remainder) > 1e-9 and np.any(adjustable):
        normalized[adjustable] += remainder / int(np.sum(adjustable))
    clipped_hours = int(np.sum((raw * factor) > cap + 1e-10))
    if abs(float(normalized.sum()) - target_energy) > 1e-6:
        raise RuntimeError("Normierung verfehlt den Zielertrag numerisch.")
    return normalized, float(factor), clipped_hours


def calibrate_wind_speed_to_energy(
    equivalent_speed: np.ndarray, *, rated_ms: float, target_energy: float
) -> tuple[np.ndarray, float, int]:
    """Kalibriert die Windgeschwindigkeit, nicht die erzeugte Leistung.

    Der Literaturwert bestimmt ausschließlich die Jahressumme. Die zeitliche
    Reihenfolge der Wetterstunden bleibt erhalten. Eine Windgeschwindigkeits-
    Kalibrierung ist physikalisch interpretierbarer als das nachträgliche
    Multiplizieren und Kappen der bereits berechneten Leistung.
    """
    speeds = np.maximum(np.asarray(equivalent_speed, dtype=float), 0.0)
    if np.any(~np.isfinite(speeds)) or float(speeds.max()) <= 0:
        raise RuntimeError("Windkalibrierung erhielt keine gültige Windreihe.")

    def energy(scale: float) -> float:
        return float(
            wind_power_from_speed(speeds * scale, rated_ms=rated_ms).sum()
        )

    low, high = 0.1, 1.0
    while energy(high) < target_energy:
        high *= 1.15
        if high > 2.5:
            raise RuntimeError(
                f"Wind-Literaturziel {target_energy:.1f} MWh/MW ist mit der "
                "Wetterreihe und Leistungskennlinie nicht robust erreichbar."
            )
    for _ in range(90):
        middle = (low + high) / 2.0
        if energy(middle) < target_energy:
            low = middle
        else:
            high = middle
    scale = (low + high) / 2.0
    profile = wind_power_from_speed(speeds * scale, rated_ms=rated_ms)
    if abs(float(profile.sum()) - target_energy) > 1e-5:
        raise RuntimeError("Windkalibrierung verfehlt den Zielertrag numerisch.")
    rated_hours = int(np.sum(profile >= WIND_AVAILABILITY_AND_WAKE - 1e-10))
    return profile, float(scale), rated_hours


def normalise_profiles(
    smard: SmardData,
    raw_profiles: dict[str, np.ndarray],
    site: Site,
    weather: WeatherData,
) -> tuple[dict[str, np.ndarray], dict[tuple[int, str], dict[str, object]]]:
    normalized = {
        scenario_id: np.zeros_like(values, dtype=float)
        for scenario_id, values in raw_profiles.items()
    }
    details: dict[tuple[int, str], dict[str, object]] = {}
    for year in sorted(np.unique(smard.year)):
        year = int(year)
        mask = smard.year == year
        for scenario_id, raw_all in raw_profiles.items():
            spec = SCENARIOS[scenario_id]
            target = float(spec["target_mwh_per_mw"])
            if str(spec["technology"]) == "wind":
                equivalent = wind_equivalent_speed(
                    site, weather, hub_height_m=float(spec["hub_height_m"])
                )[mask]
                part, factor, clipped_hours = calibrate_wind_speed_to_energy(
                    equivalent,
                    rated_ms=float(spec["rated_ms"]),
                    target_energy=target,
                )
                normalization_mode = "wind_speed_scale"
            else:
                part, factor, clipped_hours = normalise_with_cap(
                    raw_all[mask], target, profile_cap(scenario_id)
                )
                normalization_mode = "output_scale_with_physical_cap"
            normalized[scenario_id][mask] = part
            raw_energy = float(raw_all[mask].sum())
            achieved = float(part.sum())
            details[(year, scenario_id)] = {
                "raw_energy_mwh_per_mw": raw_energy,
                "target_energy_mwh_per_mw": target,
                "normalization_factor": factor,
                "normalization_mode": normalization_mode,
                "normalized_energy_mwh_per_mw": achieved,
                "normalized_deviation_pct": (achieved / target - 1.0) * 100.0,
                "clipped_hours": clipped_hours,
                "normalization_source": str(spec["target_source"]),
                "normalization_url": str(spec["target_url"]),
            }
    return normalized, details


def monthly_energy(values: np.ndarray, local_index: pd.DatetimeIndex) -> np.ndarray:
    months = np.asarray(local_index.month)
    return np.asarray([float(values[months == month].sum()) for month in range(1, 13)])


def safe_correlation(left: np.ndarray, right: np.ndarray, mask=None) -> float | None:
    if mask is not None:
        left = left[mask]
        right = right[mask]
    if len(left) < 2 or float(np.std(left)) == 0 or float(np.std(right)) == 0:
        return None
    return float(np.corrcoef(left, right)[0, 1])


def calculate_summaries(
    smard: SmardData,
    raw_profiles: dict[str, np.ndarray],
    profiles: dict[str, np.ndarray],
    normalization: dict[tuple[int, str], dict[str, object]],
) -> list[dict[str, object]]:
    local_index_all = pd.to_datetime(smard.timestamp_ms, unit="ms", utc=True).tz_convert(
        LOCAL_TIMEZONE
    )
    summaries: list[dict[str, object]] = []
    for year in sorted(np.unique(smard.year)):
        mask_year = smard.year == year
        local_index = local_index_all[mask_year]
        for scenario_id, profile_all in profiles.items():
            profile = profile_all[mask_year]
            raw_profile = raw_profiles[scenario_id][mask_year]
            technology = str(SCENARIOS[scenario_id]["technology"])
            smard_raw = (
                smard.pv_mwh[mask_year]
                if technology == "pv"
                else smard.wind_onshore_mwh[mask_year]
            )
            if technology == "pv":
                correlation_mask = (profile > 1e-8) | (smard_raw > 1e-6)
            else:
                correlation_mask = None
            correlation = safe_correlation(profile, smard_raw, correlation_mask)
            model_month = monthly_energy(profile, local_index)
            smard_month = monthly_energy(smard_raw, local_index)
            model_share = model_month / model_month.sum() * 100.0
            smard_share = smard_month / smard_month.sum() * 100.0
            monthly_mae = float(np.mean(np.abs(model_share - smard_share)))
            hours = int(mask_year.sum())
            norm = normalization[(int(year), scenario_id)]
            target = float(norm["target_energy_mwh_per_mw"])
            smard_shape, _, _ = normalise_with_cap(
                smard_raw,
                target,
                profile_cap(scenario_id),
            )
            fossil_factor = smard.fossil_restmix_t_co2e_per_mwh[mask_year]
            gross_avoided = float(np.dot(profile, fossil_factor))
            smard_shape_gross = float(np.dot(smard_shape, fossil_factor))
            lifecycle_factor = LIFECYCLE_G_CO2E_KWH[technology]
            lifecycle = float(profile.sum()) * lifecycle_factor / 1000.0
            net_avoided = gross_avoided - lifecycle
            profile_delta = (
                (gross_avoided / smard_shape_gross - 1.0) * 100.0
                if smard_shape_gross > 0
                else float("nan")
            )
            norm_deviation = float(norm["normalized_deviation_pct"])
            correlation_floor = 0.85 if technology == "pv" else 0.65
            correlation_ok = correlation is not None and correlation >= correlation_floor
            monthly_ok = monthly_mae <= 3.0
            status = (
                "OK"
                if abs(norm_deviation) <= 0.01
                and abs(profile_delta) <= REFERENCE_TOLERANCE_PCT
                and correlation_ok
                and monthly_ok
                else "PRÜFEN"
            )
            summaries.append(
                {
                    "year": int(year),
                    "scenario_id": scenario_id,
                    "label": SCENARIOS[scenario_id]["label"],
                    "technology": technology,
                    "hours": hours,
                    "energy_mwh_per_mw": float(profile.sum()),
                    "raw_energy_mwh_per_mw": float(raw_profile.sum()),
                    "target_energy_mwh_per_mw": target,
                    "normalization_factor": float(norm["normalization_factor"]),
                    "normalization_mode": str(norm["normalization_mode"]),
                    "normalized_deviation_pct": norm_deviation,
                    "clipped_hours": int(norm["clipped_hours"]),
                    "capacity_factor": float(profile.sum() / hours),
                    "maximum_mw_per_mw": float(profile.max()),
                    "zero_hours": int(np.sum(profile <= 1e-9)),
                    "smard_hourly_correlation": correlation,
                    "smard_monthly_share_mae_pp": monthly_mae,
                    "lifecycle_g_co2e_kwh": lifecycle_factor,
                    "gross_avoided_t_co2e_per_mw": gross_avoided,
                    "lifecycle_t_co2e_per_mw": lifecycle,
                    "net_avoided_t_co2e_per_mw": net_avoided,
                    "smard_shape_gross_avoided_t_co2e_per_mw": smard_shape_gross,
                    "thg_profile_delta_pct": profile_delta,
                    "validation_status": status,
                    "normalization_source": str(norm["normalization_source"]),
                    "normalization_url": str(norm["normalization_url"]),
                    "reference_mode": (
                        "Literatur-Jahresertrag; SMARD-Profil- und THG-Vergleich"
                    ),
                }
            )
    return summaries


def write_database(
    path: Path,
    site: Site,
    smard_path: Path,
    smard: SmardData,
    raw_profiles: dict[str, np.ndarray],
    profiles: dict[str, np.ndarray],
    normalization: dict[tuple[int, str], dict[str, object]],
    summaries: list[dict[str, object]],
) -> None:
    con = open_scenario_db(path)
    try:
        with con:
            for scenario_id, spec in SCENARIOS.items():
                parameters = dict(spec)
                parameters.update(
                    {
                        "pv_ac_mw": PV_AC_MW_PER_MWP,
                        "pv_dc_mwp": PV_DC_MWP,
                        "pv_ac_mw_per_mwp": PV_AC_MW_PER_MWP,
                        "pv_dc_ac_ratio": PV_DC_AC_RATIO,
                        "pv_system_loss": PV_SYSTEM_LOSS,
                        "pv_gamma_pdc": PV_GAMMA_PDC,
                        "pv_inverter_efficiency": PV_INVERTER_EFFICIENCY,
                        "wind_measurement_height_m": WIND_MEASUREMENT_HEIGHT_M,
                        "wind_shear_exponent": WIND_SHEAR_EXPONENT,
                        "wind_cut_in_ms": WIND_CUT_IN_MS,
                        "wind_cut_out_ms": WIND_CUT_OUT_MS,
                        "wind_availability_and_wake": WIND_AVAILABILITY_AND_WAKE,
                        "lifecycle_g_co2e_kwh": LIFECYCLE_G_CO2E_KWH[
                            str(spec["technology"])
                        ],
                        "uba_reference_url": UBA_REFERENCE_URL,
                        "normalization_mode": (
                            "wind_speed_scale" if str(spec["technology"]) == "wind"
                            else "output_scale_with_physical_cap"
                        ),
                    }
                )
                con.execute(
                    "INSERT OR REPLACE INTO scenario_definition VALUES (?,?,?,?,?,?)",
                    (
                        scenario_id,
                        str(spec["label"]),
                        str(spec["technology"]),
                        1.0,
                        MODEL_VERSION,
                        json.dumps(parameters, ensure_ascii=False, sort_keys=True),
                    ),
                )
            start_ms, end_ms = int(smard.timestamp_ms[0]), int(smard.timestamp_ms[-1])
            con.execute(
                "DELETE FROM scenario_hourly WHERE site_id=? "
                "AND timestamp_ms BETWEEN ? AND ?",
                (site.site_id, start_ms, end_ms),
            )
            for scenario_id, values in profiles.items():
                rows = []
                for index, (timestamp, value) in enumerate(
                    zip(smard.timestamp_ms, values)
                ):
                    year = int(smard.year[index])
                    norm = normalization[(year, scenario_id)]
                    rows.append(
                        (
                            scenario_id,
                            site.site_id,
                            int(timestamp),
                            float(value),
                            float(raw_profiles[scenario_id][index]),
                            float(norm["normalization_factor"]),
                            float(norm["target_energy_mwh_per_mw"]),
                        )
                    )
                con.executemany(
                    "INSERT INTO scenario_hourly("
                    "scenario_id,site_id,timestamp_ms,generation_mwh_per_mw,"
                    "raw_generation_mwh_per_mw,normalization_factor,"
                    "normalization_target_mwh_per_mw) VALUES (?,?,?,?,?,?,?)",
                    rows,
                )
            years = sorted({int(item["year"]) for item in summaries})
            placeholders = ",".join("?" for _ in years)
            con.execute(
                f"DELETE FROM verification_summary WHERE site_id=? "
                f"AND year IN ({placeholders})",
                [site.site_id, *years],
            )
            con.executemany(
                "INSERT INTO verification_summary("
                "year,scenario_id,site_id,hours,energy_mwh_per_mw,"
                "raw_energy_mwh_per_mw,target_energy_mwh_per_mw,"
                "normalization_factor,normalized_deviation_pct,clipped_hours,"
                "capacity_factor,maximum_mw_per_mw,zero_hours,"
                "smard_hourly_correlation,smard_monthly_share_mae_pp,"
                "lifecycle_g_co2e_kwh,gross_avoided_t_co2e_per_mw,"
                "lifecycle_t_co2e_per_mw,net_avoided_t_co2e_per_mw,"
                "smard_shape_gross_avoided_t_co2e_per_mw,thg_profile_delta_pct,"
                "validation_status,normalization_source,reference_mode"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    (
                        int(item["year"]),
                        str(item["scenario_id"]),
                        site.site_id,
                        int(item["hours"]),
                        float(item["energy_mwh_per_mw"]),
                        float(item["raw_energy_mwh_per_mw"]),
                        float(item["target_energy_mwh_per_mw"]),
                        float(item["normalization_factor"]),
                        float(item["normalized_deviation_pct"]),
                        int(item["clipped_hours"]),
                        float(item["capacity_factor"]),
                        float(item["maximum_mw_per_mw"]),
                        int(item["zero_hours"]),
                        item["smard_hourly_correlation"],
                        float(item["smard_monthly_share_mae_pp"]),
                        float(item["lifecycle_g_co2e_kwh"]),
                        float(item["gross_avoided_t_co2e_per_mw"]),
                        float(item["lifecycle_t_co2e_per_mw"]),
                        float(item["net_avoided_t_co2e_per_mw"]),
                        float(item["smard_shape_gross_avoided_t_co2e_per_mw"]),
                        float(item["thg_profile_delta_pct"]),
                        str(item["validation_status"]),
                        str(item["normalization_source"]),
                        str(item["reference_mode"]),
                    )
                    for item in summaries
                ),
            )
            metadata = {
                "model_version": MODEL_VERSION,
                "last_run_utc": datetime.now(timezone.utc).isoformat(),
                "smard_source": str(smard_path.resolve()),
                "site": {
                    "id": site.site_id,
                    "name": site.name,
                    "latitude": site.latitude,
                    "longitude": site.longitude,
                    "elevation_m": site.elevation_m,
                },
                "normalization": {
                    "mode": (
                        "PV: calendar-year output scaling with physical AC cap; "
                        "Wind: calendar-year wind-speed calibration"
                    ),
                    "raw_profile_preserved": True,
                    "tolerance_pct": REFERENCE_TOLERANCE_PCT,
                    "pv_targets": "PVGIS 5.3 SARAH3, 2005–2023",
                    "wind_targets": (
                        "WindGuard 2026, Region Mitte; netzkorrigierte Werte auf "
                        "marktseitig zugängliche Einspeisung zurückgeführt"
                    ),
                },
                "units": {
                    "scenario_hourly.generation_mwh_per_mw": (
                        "normierte MWh in einer Stunde je MWp DC (PV) bzw. "
                        "je MW Nennleistung (Wind)"
                    ),
                    "scenario_hourly.raw_generation_mwh_per_mw": (
                        "rohe Modell-MWh in einer Stunde in derselben Bezugsgröße"
                    ),
                },
                "thg_method": (
                    "stündlicher Durchschnitt des fossilen SMARD-Restmixes; "
                    "kein kausaler Grenzkraftwerksfaktor"
                ),
                "uba_reference_url": UBA_REFERENCE_URL,
                "smard_reference_url": SMARD_REFERENCE_URL,
            }
            for key, value in metadata.items():
                con.execute(
                    "INSERT OR REPLACE INTO metadata VALUES (?,?)",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
            checks = {
                "smard_hours": ("OK", str(len(smard.timestamp_ms)), "lückenlos"),
                "scenario_count": (
                    "OK",
                    str(len(profiles)),
                    "Rohprofil und literaturnormiertes Profil gespeichert",
                ),
                "scenario_maximum": (
                    "OK",
                    f"{max(float(np.max(value)) for value in profiles.values()):.6f}",
                    "muss <= 1 MW/MW sein",
                ),
                "literature_targets": (
                    "OK",
                    str(len(normalization)),
                    "jedes Szenariojahr erreicht seinen dokumentierten Zielertrag",
                ),
                "sqlite_integrity": ("OK", "ok", "nach Schreibvorgang erneut geprüft"),
            }
            for check_id, (status, value, note) in checks.items():
                con.execute(
                    "INSERT OR REPLACE INTO validation VALUES (?,?,?,?)",
                    (check_id, status, value, note),
                )
    finally:
        con.close()
    sqlite_integrity(path, "Wetter-/Szenariendatenbank")


def setup_plot_style() -> None:
    try:
        import matplotlib as mpl
    except ImportError as exc:
        raise RuntimeError(
            "matplotlib fehlt. In der aktivierten .venv ausführen: "
            "python -m pip install matplotlib"
        ) from exc
    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": "#dddddd",
            "grid.linewidth": 0.7,
            "axes.axisbelow": True,
            "savefig.facecolor": "white",
        }
    )


def save_figure(fig, base: Path) -> None:
    fig.savefig(base.with_suffix(".svg"), bbox_inches="tight")
    fig.savefig(base.with_suffix(".png"), dpi=180, bbox_inches="tight")


def plot_individual_profiles(
    out: Path,
    site: Site,
    smard: SmardData,
    raw_profiles: dict[str, np.ndarray],
    profiles: dict[str, np.ndarray],
    normalization: dict[tuple[int, str], dict[str, object]],
) -> None:
    import matplotlib.pyplot as plt

    setup_plot_style()
    local_index_all = pd.to_datetime(smard.timestamp_ms, unit="ms", utc=True).tz_convert(
        LOCAL_TIMEZONE
    )
    for year in sorted(np.unique(smard.year)):
        year = int(year)
        mask = smard.year == year
        local_index = local_index_all[mask]
        for scenario_id, values_all in profiles.items():
            values = values_all[mask]
            raw_values = raw_profiles[scenario_id][mask]
            norm = normalization[(year, scenario_id)]
            fig, axes = plt.subplots(2, 1, figsize=(11.8, 6.8))
            fig.subplots_adjust(top=0.83, bottom=0.11, hspace=0.35)
            color = COLORS[scenario_id]
            axes[0].plot(
                local_index,
                raw_values,
                color="#9a9a9a",
                lw=0.5,
                alpha=0.75,
                label="Rohprofil",
            )
            axes[0].plot(
                local_index,
                values,
                color=color,
                lw=0.55,
                label="Literaturkalibriert",
            )
            axes[0].fill_between(local_index, 0, values, color=color, alpha=0.15)
            axes[0].set_ylabel("Leistung je Bezugs-MW")
            axes[0].set_ylim(0, 1.02)
            axes[0].set_title("Chronologische Jahresstunden", loc="left")
            axes[0].legend(frameon=False, fontsize=8.5)
            duration = np.sort(values)[::-1]
            raw_duration = np.sort(raw_values)[::-1]
            axes[1].plot(
                np.arange(1, len(raw_duration) + 1),
                raw_duration,
                color="#9a9a9a",
                lw=1.0,
                alpha=0.8,
            )
            axes[1].plot(
                np.arange(1, len(duration) + 1), duration, color=color, lw=1.5
            )
            axes[1].fill_between(
                np.arange(1, len(duration) + 1), 0, duration, color=color, alpha=0.12
            )
            axes[1].set_xlabel("Jahresstunden, nach Erzeugung absteigend")
            axes[1].set_ylabel("Leistung je Bezugs-MW")
            axes[1].set_ylim(0, 1.02)
            axes[1].set_title("Jahresdauerlinie", loc="left")
            energy = float(values.sum())
            capacity_factor = energy / len(values) * 100.0
            fig.suptitle(
                f"{SCENARIOS[scenario_id]['label']} · Verifikation {year}",
                x=0.075,
                y=0.97,
                ha="left",
                fontsize=15,
                fontweight="bold",
            )
            fig.text(
                0.075,
                0.905,
                f"{site.name} · {SCENARIOS[scenario_id]['capacity_basis']} · "
                f"Roh {float(norm['raw_energy_mwh_per_mw']):.0f} → "
                f"Ziel {energy:.0f} MWh je Bezugs-MW · "
                f"{str(norm['normalization_mode'])} "
                f"{float(norm['normalization_factor']):.3f} · "
                f"Kapazitätsfaktor {capacity_factor:.1f} %",
                color="#444444",
                fontsize=9.5,
            )
            fig.text(
                0.075,
                0.875,
                str(norm["normalization_source"]),
                color="#666666",
                fontsize=8.3,
            )
            save_figure(fig, out / f"01_{scenario_id}_{year}")
            plt.close(fig)


def plot_scenario_comparison(
    out: Path, smard: SmardData, profiles: dict[str, np.ndarray]
) -> None:
    import matplotlib.pyplot as plt

    setup_plot_style()
    for year in sorted(np.unique(smard.year)):
        year = int(year)
        mask = smard.year == year
        fig, axes = plt.subplots(2, 1, figsize=(11.7, 8.0), sharex=True)
        fig.subplots_adjust(top=0.86, bottom=0.10, hspace=0.28)
        for technology, ax in (("pv", axes[0]), ("wind", axes[1])):
            for scenario_id, spec in SCENARIOS.items():
                if spec["technology"] != technology:
                    continue
                values = np.sort(profiles[scenario_id][mask])[::-1]
                ax.plot(
                    np.arange(1, len(values) + 1),
                    values,
                    label=f"{spec['label']} · {values.sum():.0f} MWh/MW",
                    color=COLORS[scenario_id],
                    lw=1.5,
                )
            ax.set_ylim(0, 1.02)
            ax.set_ylabel("Leistung je Bezugs-MW")
            ax.set_title(
                "Photovoltaik" if technology == "pv" else "Wind an Land",
                loc="left",
            )
            ax.legend(frameon=False, fontsize=8.7, ncol=2)
        axes[1].set_xlabel("Jahresstunden, nach Erzeugung absteigend")
        fig.suptitle(
            f"Szenarienvergleich · Jahresdauerlinien {year}",
            x=0.075,
            y=0.97,
            ha="left",
            fontsize=15,
            fontweight="bold",
        )
        fig.text(
            0.075,
            0.915,
            "Stundenprofile auf dokumentierte PVGIS-/WindGuard-Jahreserträge "
            "kalibriert; Rohwerte bleiben separat erhalten.",
            color="#555555",
            fontsize=9.4,
        )
        save_figure(fig, out / f"02_szenarienvergleich_{year}")
        plt.close(fig)


def plot_smard_reference(
    out: Path, smard: SmardData, profiles: dict[str, np.ndarray]
) -> None:
    """Vergleicht die kalibrierten Szenarioformen mit SMARD-Flottenformen."""
    import matplotlib.pyplot as plt

    setup_plot_style()
    month_labels = [
        "Jan",
        "Feb",
        "Mär",
        "Apr",
        "Mai",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Okt",
        "Nov",
        "Dez",
    ]
    local_index_all = pd.to_datetime(smard.timestamp_ms, unit="ms", utc=True).tz_convert(
        LOCAL_TIMEZONE
    )
    for year in sorted(np.unique(smard.year)):
        year = int(year)
        mask = smard.year == year
        index = local_index_all[mask]
        fig, axes = plt.subplots(2, 1, figsize=(10.8, 7.7), sharex=True)
        fig.subplots_adjust(top=0.84, bottom=0.11, hspace=0.28)
        panels = [
            (
                axes[0],
                "pv",
                smard.pv_mwh[mask],
                "smard_pv",
                "SMARD PV-Flotte",
            ),
            (
                axes[1],
                "wind",
                smard.wind_onshore_mwh[mask],
                "smard_wind",
                "SMARD Wind-an-Land-Flotte",
            ),
        ]
        for ax, technology, reference, reference_color, reference_label in panels:
            reference_month = monthly_energy(reference, index)
            reference_share = reference_month / reference_month.sum() * 100.0
            ax.plot(
                range(1, 13),
                reference_share,
                marker="s",
                lw=2.2,
                color=COLORS[reference_color],
                label=reference_label,
            )
            for scenario_id, spec in SCENARIOS.items():
                if spec["technology"] != technology:
                    continue
                model_month = monthly_energy(profiles[scenario_id][mask], index)
                share = model_month / model_month.sum() * 100.0
                ax.plot(
                    range(1, 13),
                    share,
                    marker="o",
                    ms=3.8,
                    lw=1.25,
                    color=COLORS[scenario_id],
                    label=str(spec["label"]),
                )
            ax.set_ylabel("Anteil am Jahresertrag %")
            ax.set_ylim(bottom=0)
            ax.set_title(
                "Photovoltaik · Saisonform"
                if technology == "pv"
                else "Wind an Land · Saisonform",
                loc="left",
            )
            ax.legend(frameon=False, fontsize=8.4, ncol=3)
        axes[1].set_xticks(range(1, 13), month_labels)
        fig.suptitle(
            f"Optischer Referenzvergleich mit SMARD · {year}",
            x=0.075,
            y=0.97,
            ha="left",
            fontsize=15,
            fontweight="bold",
        )
        capacity_note = (
            "Szenario-Jahressummen: PVGIS/WindGuard · Stunden- und Saisonform: "
            "Modell gegen reale SMARD-Flotte; kein erfundener SMARD-Ertrag je MW."
        )
        fig.text(0.075, 0.905, capacity_note, color="#555555", fontsize=9.2)
        save_figure(fig, out / f"03_smard_referenzvergleich_{year}")
        plt.close(fig)


def plot_weather_check(
    out: Path, site: Site, smard: SmardData, weather: WeatherData
) -> None:
    import matplotlib.pyplot as plt

    setup_plot_style()
    local_index_all = pd.to_datetime(smard.timestamp_ms, unit="ms", utc=True).tz_convert(
        LOCAL_TIMEZONE
    )
    month_labels = [
        "Jan",
        "Feb",
        "Mär",
        "Apr",
        "Mai",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Okt",
        "Nov",
        "Dez",
    ]
    for year in sorted(np.unique(smard.year)):
        year = int(year)
        mask = smard.year == year
        months = np.asarray(local_index_all[mask].month)

        def monthly_mean(values: np.ndarray) -> list[float]:
            part = values[mask]
            return [float(np.nanmean(part[months == month])) for month in range(1, 13)]

        fig, axes = plt.subplots(3, 1, figsize=(10.8, 8.3), sharex=True)
        fig.subplots_adjust(top=0.86, bottom=0.10, hspace=0.30)
        axes[0].plot(range(1, 13), monthly_mean(weather.temp_c), marker="o")
        axes[0].set_ylabel("°C")
        axes[0].set_title("Lufttemperatur · Monatsmittel", loc="left")
        axes[1].plot(
            range(1, 13), monthly_mean(weather.wind_10m_ms), marker="o", color="#24527A"
        )
        axes[1].set_ylabel("m/s")
        axes[1].set_title("Windgeschwindigkeit in 10 m · Monatsmittel", loc="left")
        axes[2].plot(
            range(1, 13), monthly_mean(weather.cloud_okta), marker="o", color="#777777"
        )
        axes[2].set_ylabel("Okta")
        axes[2].set_ylim(0, 8.2)
        axes[2].set_title("Bewölkung · Monatsmittel", loc="left")
        axes[2].set_xticks(range(1, 13), month_labels)
        fig.suptitle(
            f"Wetterdatenprüfung · {site.name} · {year}",
            x=0.075,
            y=0.97,
            ha="left",
            fontsize=15,
            fontweight="bold",
        )
        imputed = (
            int(np.sum(weather.imputed_temp[mask]))
            + int(np.sum(weather.imputed_wind[mask]))
            + int(np.sum(weather.imputed_pressure[mask]))
            + int(np.sum(weather.imputed_cloud[mask]))
        )
        fig.text(
            0.075,
            0.915,
            f"Meteostat-Stunden · {int(mask.sum())} Stunden · "
            f"{imputed} interpolierte Pflichtwerte (Summe über vier Variablen).",
            color="#555555",
            fontsize=9.2,
        )
        save_figure(fig, out / f"04_wetterdatenpruefung_{year}")
        plt.close(fig)


def plot_literature_normalization(
    out: Path, summaries: list[dict[str, object]]
) -> None:
    """Zeigt Rohwert, Zielwert und den offengelegten Kalibrierungseingriff."""
    import matplotlib.pyplot as plt

    setup_plot_style()
    for year in sorted({int(item["year"]) for item in summaries}):
        rows = [item for item in summaries if int(item["year"]) == year]
        rows.sort(key=lambda item: list(SCENARIOS).index(str(item["scenario_id"])))
        labels = [str(item["label"]) for item in rows]
        raw = np.asarray([float(item["raw_energy_mwh_per_mw"]) for item in rows])
        target = np.asarray([float(item["target_energy_mwh_per_mw"]) for item in rows])
        y = np.arange(len(rows))
        fig, ax = plt.subplots(figsize=(10.8, 6.2))
        fig.subplots_adjust(left=0.25, right=0.96, top=0.84, bottom=0.12)
        ax.barh(y + 0.18, raw, height=0.32, color="#b9b9b9", label="Rohprofil")
        ax.barh(
            y - 0.18,
            target,
            height=0.32,
            color=[COLORS[str(item["scenario_id"])] for item in rows],
            label="Literaturziel = kalibrierter Ertrag",
        )
        for index, item in enumerate(rows):
            factor = float(item["normalization_factor"])
            ax.text(
                max(raw[index], target[index]) + 30,
                index,
                (
                    f"Leistung × {factor:.2f}"
                    if str(item.get("normalization_mode", "")).startswith("output")
                    else f"Wind v × {factor:.2f}"
                ),
                va="center",
                fontsize=8.5,
                color="#444444",
            )
            low = target[index] * (1 - REFERENCE_TOLERANCE_PCT / 100)
            high = target[index] * (1 + REFERENCE_TOLERANCE_PCT / 100)
            ax.plot([low, high], [index - 0.36, index - 0.36], color="#333333", lw=1)
            ax.plot([low, low], [index - 0.41, index - 0.31], color="#333333", lw=1)
            ax.plot([high, high], [index - 0.41, index - 0.31], color="#333333", lw=1)
        ax.set_yticks(y, labels)
        ax.invert_yaxis()
        ax.set_xlabel("Jahresertrag MWh je MWp DC (PV) bzw. MW Nennleistung (Wind)")
        ax.set_xlim(0, max(target.max(), raw.max()) * 1.20)
        ax.legend(frameon=False, loc="lower right")
        fig.suptitle(
            f"Literaturkalibrierung der Szenarien · {year}",
            x=0.075,
            y=0.97,
            ha="left",
            fontsize=15,
            fontweight="bold",
        )
        fig.text(
            0.075,
            0.905,
            "PV: PVGIS 5.3/SARAH3, Kassel 2005–2023 · Wind: WindGuard 2026, "
            "Region Mitte · schwarze Spanne: ±10 % um den Zielwert.",
            color="#555555",
            fontsize=9.1,
        )
        save_figure(fig, out / f"05_literaturnormierung_{year}")
        plt.close(fig)


def plot_energy_and_ghg(out: Path, summaries: list[dict[str, object]]) -> None:
    """Artikelnahe Kontrolle von Energie und THG mit SMARD-Profilbenchmark."""
    import matplotlib.pyplot as plt

    setup_plot_style()
    for year in sorted({int(item["year"]) for item in summaries}):
        rows = [item for item in summaries if int(item["year"]) == year]
        rows.sort(key=lambda item: list(SCENARIOS).index(str(item["scenario_id"])))
        labels = [str(item["label"]) for item in rows]
        x = np.arange(len(rows))
        energy = np.asarray([float(item["energy_mwh_per_mw"]) for item in rows])
        net = np.asarray([float(item["net_avoided_t_co2e_per_mw"]) for item in rows])
        smard_net = np.asarray(
            [
                float(item["smard_shape_gross_avoided_t_co2e_per_mw"])
                - float(item["lifecycle_t_co2e_per_mw"])
                for item in rows
            ]
        )
        colors = [COLORS[str(item["scenario_id"])] for item in rows]
        fig, axes = plt.subplots(2, 1, figsize=(11.8, 8.3), sharex=True)
        fig.subplots_adjust(top=0.85, bottom=0.18, hspace=0.30)
        axes[0].bar(x, energy, color=colors)
        axes[0].set_ylabel("MWh je MW und Jahr")
        axes[0].set_title("Literaturkalibrierter Energieertrag", loc="left")
        for position, value in zip(x, energy):
            axes[0].text(position, value + 25, f"{value:.0f}", ha="center", fontsize=8.5)
        axes[1].bar(x, net, color=colors, label="Szenario-Stundenprofil")
        axes[1].scatter(
            x,
            smard_net,
            marker="D",
            s=38,
            color="#222222",
            zorder=4,
            label="gleicher Ertrag, SMARD-Flottenprofil",
        )
        axes[1].set_ylabel("t CO₂e je MW und Jahr")
        axes[1].set_title(
            "Netto-THG-Verdrängung im stündlichen fossilen SMARD-Restmix",
            loc="left",
        )
        axes[1].legend(frameon=False, fontsize=8.8)
        axes[1].set_xticks(x, labels, rotation=24, ha="right")
        fig.suptitle(
            f"Energie- und THG-Plausibilitätsvergleich · SMARD {year}",
            x=0.075,
            y=0.97,
            ha="left",
            fontsize=15,
            fontweight="bold",
        )
        fig.text(
            0.075,
            0.905,
            "THG ist eine rechnerische Restmix-Zurechnung, kein kausaler "
            "Grenzkraftwerksnachweis. Lebenszyklusabzug: UBA-Bestandsfaktoren.",
            color="#555555",
            fontsize=9.1,
        )
        save_figure(fig, out / f"06_energie_thg_smard_{year}")
        plt.close(fig)


def write_summary_csv(out: Path, summaries: list[dict[str, object]]) -> Path:
    path = out / "szenarien_pruefergebnisse.csv"
    fields = [
        "year",
        "scenario_id",
        "label",
        "technology",
        "hours",
        "raw_energy_mwh_per_mw",
        "target_energy_mwh_per_mw",
        "energy_mwh_per_mw",
        "normalization_factor",
        "normalization_mode",
        "normalized_deviation_pct",
        "clipped_hours",
        "capacity_factor",
        "maximum_mw_per_mw",
        "zero_hours",
        "smard_hourly_correlation",
        "smard_monthly_share_mae_pp",
        "lifecycle_g_co2e_kwh",
        "gross_avoided_t_co2e_per_mw",
        "lifecycle_t_co2e_per_mw",
        "net_avoided_t_co2e_per_mw",
        "smard_shape_gross_avoided_t_co2e_per_mw",
        "thg_profile_delta_pct",
        "validation_status",
        "normalization_source",
        "normalization_url",
        "reference_mode",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summaries)
    return path


def write_smard_summary_csv(out: Path, smard: SmardData) -> Path:
    path = out / "smard_jahresvergleich.csv"
    fields = [
        "year",
        "hours",
        "pv_feed_in_twh",
        "wind_onshore_feed_in_twh",
        "mean_hourly_fossil_restmix_t_co2e_per_mwh",
        "source",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for year in sorted(np.unique(smard.year)):
            mask = smard.year == year
            writer.writerow(
                {
                    "year": int(year),
                    "hours": int(mask.sum()),
                    "pv_feed_in_twh": float(smard.pv_mwh[mask].sum() / 1e6),
                    "wind_onshore_feed_in_twh": float(
                        smard.wind_onshore_mwh[mask].sum() / 1e6
                    ),
                    "mean_hourly_fossil_restmix_t_co2e_per_mwh": float(
                        np.mean(smard.fossil_restmix_t_co2e_per_mwh[mask])
                    ),
                    "source": "SMARD-SQLite / Bundesnetzagentur",
                }
            )
    return path


def write_report(
    out: Path,
    site: Site,
    smard_path: Path,
    database: Path,
    smard: SmardData,
    summaries: list[dict[str, object]],
    weather: WeatherData,
) -> Path:
    path = out / "VERIFIKATIONSBERICHT.txt"
    lines = [
        "WETTERDATEN UND SZENARIENVERIFIKATION",
        "=" * 44,
        "",
        f"Standort: {site.name} ({site.latitude:.4f}, {site.longitude:.4f}, "
        f"{site.elevation_m:.0f} m)",
        f"SMARD: {smard_path.resolve()}",
        f"Ergebnisdatenbank: {database.resolve()}",
        "Ertragskalibrierung: PV-Leistungsprofil bzw. Windgeschwindigkeit werden "
        "auf den dokumentierten Jahreswert kalibriert; Rohprofil bleibt gespeichert",
        "PV-Bezug: MWp DC; Wind-Bezug: MW Nennleistung",
        "",
        "Aktuelle SMARD-Vergleichsdaten:",
        *[
            f"- {int(year)}: PV {smard.pv_mwh[smard.year == year].sum()/1e6:.3f} TWh; "
            f"Wind an Land {smard.wind_onshore_mwh[smard.year == year].sum()/1e6:.3f} TWh"
            for year in sorted(np.unique(smard.year))
        ],
        "",
        "Szenarioergebnisse:",
    ]
    for item in summaries:
        correlation = item["smard_hourly_correlation"]
        corr_text = "n.v." if correlation is None else f"{float(correlation):.3f}"
        lines.append(
            f"- {item['year']} · {item['label']}: "
            f"Roh {float(item['raw_energy_mwh_per_mw']):.1f} → "
            f"Ziel {float(item['energy_mwh_per_mw']):.1f} MWh/MW "
            f"({item['normalization_mode']} {float(item['normalization_factor']):.3f}, "
            f"{int(item['clipped_hours'])} gekappte Stunden), "
            f"CF {float(item['capacity_factor']) * 100:.1f} %, "
            f"SMARD-Stundenkorrelation r={corr_text}, "
            f"netto {float(item['net_avoided_t_co2e_per_mw']):.1f} t CO2e/MW, "
            f"THG-Abweichung zum gleichen SMARD-Flottenprofil "
            f"{float(item['thg_profile_delta_pct']):+.1f} %, "
            f"Status {item['validation_status']}"
        )
        lines.append(f"  Quelle: {item['normalization_source']}")
    lines.extend(
        [
            "",
            "Wetterdatenqualität:",
            f"- Temperatur interpoliert: {int(np.sum(weather.imputed_temp))}",
            f"- Wind interpoliert: {int(np.sum(weather.imputed_wind))}",
            f"- Luftdruck interpoliert: {int(np.sum(weather.imputed_pressure))}",
            f"- Bewölkung interpoliert: {int(np.sum(weather.imputed_cloud))}",
            "",
            "Methodische Grenze:",
            "- Meteostat liefert Standortwetter, keine Windpark-Ertragsprognose.",
            "- PV-Strahlung wird aus Clear-sky-Geometrie und Bewölkung geschätzt.",
            "- Die Windkennlinien sind dokumentierte generische Annahmen.",
            "- Die Literaturkalibrierung sichert die Jahressumme, nicht jede Stunde; "
            "PV skaliert das Leistungsprofil mit AC-Grenze, Wind die Windgeschwindigkeit.",
            "- Der SMARD-Vergleich normiert das reale Flottenprofil auf denselben "
            "Jahresertrag und prüft damit die THG-Sensitivität der Profilform.",
            "- Die THG-Zahl nutzt den stündlichen Durchschnitt des fossilen Restmixes; "
            "sie ist keine kausale Grenzkraftwerksanalyse.",
            "- Lebenszyklusemissionen werden konservativ mit den UBA-Bestandsfaktoren "
            "56,49 g CO2e/kWh (PV) und 17,58 g CO2e/kWh (Wind an Land) abgezogen.",
            "",
            "Referenzen:",
            f"- PVGIS: {PVGIS_REFERENCE_URL}",
            f"- WindGuard: {WINDGUARD_REFERENCE_URL}",
            f"- UBA: {UBA_REFERENCE_URL}",
            f"- SMARD/Bundesnetzagentur: {SMARD_REFERENCE_URL}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def export_hourly_csv(
    out: Path,
    site: Site,
    smard: SmardData,
    weather: WeatherData,
    raw_profiles: dict[str, np.ndarray],
    profiles: dict[str, np.ndarray],
) -> Path:
    path = out / "szenarien_stundenwerte.csv"
    fields = [
        "timestamp_ms",
        "timestamp_berlin",
        "site_id",
        "temp_c",
        "wind_10m_ms",
        "pressure_hpa_msl",
        "sunshine_min",
        "cloud_okta",
        "fossil_restmix_t_co2e_per_mwh",
        *(f"raw_{scenario_id}" for scenario_id in profiles),
        *(f"norm_{scenario_id}" for scenario_id in profiles),
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, timestamp in enumerate(smard.timestamp_ms):
            row: dict[str, object] = {
                "timestamp_ms": int(timestamp),
                "timestamp_berlin": smard.timestamp_berlin[index],
                "site_id": site.site_id,
                "temp_c": float(weather.temp_c[index]),
                "wind_10m_ms": float(weather.wind_10m_ms[index]),
                "pressure_hpa_msl": float(weather.pressure_hpa_msl[index]),
                "sunshine_min": (
                    ""
                    if np.isnan(weather.sunshine_min[index])
                    else float(weather.sunshine_min[index])
                ),
                "cloud_okta": float(weather.cloud_okta[index]),
                "fossil_restmix_t_co2e_per_mwh": float(
                    smard.fossil_restmix_t_co2e_per_mwh[index]
                ),
            }
            for scenario_id, values in profiles.items():
                row[f"raw_{scenario_id}"] = float(raw_profiles[scenario_id][index])
                row[f"norm_{scenario_id}"] = float(values[index])
            writer.writerow(row)
    return path


def run(args: argparse.Namespace) -> None:
    site = Site(args.site, args.latitude, args.longitude, args.elevation)
    if not (-90 <= site.latitude <= 90 and -180 <= site.longitude <= 180):
        raise RuntimeError("Standortkoordinaten sind ungültig.")
    years = parse_years(args.years)
    print(f"SMARD wird geprüft: {args.smard_db}")
    smard = load_smard(args.smard_db, years)
    print(f"SMARD vollständig: {len(smard.timestamp_ms)} Stunden")
    weather = ensure_weather(
        args.database,
        site,
        smard.timestamp_ms,
        offline=args.offline,
        refresh=args.refresh_weather,
    )
    print("Wetterdaten vollständig; Rohszenarien werden berechnet …")
    raw_profiles = build_scenarios(site, weather, smard.timestamp_ms)
    print("Rohprofile werden auf PVGIS-/WindGuard-Jahreserträge kalibriert …")
    profiles, normalization = normalise_profiles(
        smard, raw_profiles, site, weather
    )
    summaries = calculate_summaries(
        smard, raw_profiles, profiles, normalization
    )
    write_database(
        args.database,
        site,
        args.smard_db,
        smard,
        raw_profiles,
        profiles,
        normalization,
        summaries,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    # Prüfgrafiken werden bewusst vor allen optionalen Exporten erzeugt.
    print(f"Verifikationsgrafiken werden geschrieben: {args.out}")
    # Auch Matplotlibs Schrift-/Konfigurationscache bleibt flüchtig. Damit
    # erzeugt der Lauf neben Ergebnisdatenbank und Ausgaben keine Cache-Ordner.
    old_mpl_config = os.environ.get("MPLCONFIGDIR")
    with tempfile.TemporaryDirectory(prefix="matplotlib_config_") as mpl_tmp:
        os.environ["MPLCONFIGDIR"] = mpl_tmp
        try:
            plot_individual_profiles(
                args.out, site, smard, raw_profiles, profiles, normalization
            )
            plot_scenario_comparison(args.out, smard, profiles)
            plot_smard_reference(args.out, smard, profiles)
            plot_weather_check(args.out, site, smard, weather)
            plot_literature_normalization(args.out, summaries)
            plot_energy_and_ghg(args.out, summaries)
        finally:
            if old_mpl_config is None:
                os.environ.pop("MPLCONFIGDIR", None)
            else:
                os.environ["MPLCONFIGDIR"] = old_mpl_config
    summary_path = write_summary_csv(args.out, summaries)
    smard_summary_path = write_smard_summary_csv(args.out, smard)
    report_path = write_report(
        args.out, site, args.smard_db, args.database, smard, summaries, weather
    )
    if args.export_hourly_csv:
        export_hourly_csv(
            args.out, site, smard, weather, raw_profiles, profiles
        )
    print("")
    print("Fertig.")
    print(f"  Datenbank: {args.database}")
    print(f"  Grafiken:  {args.out}")
    print(f"  Prüftabelle: {summary_path}")
    print(f"  SMARD-Jahresvergleich: {smard_summary_path}")
    print(f"  Bericht: {report_path}")
    print("  Ertragskalibrierung: PVGIS-Jahreswerte; WindGuard-Zielwerte; Rohprofile separat")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Erzeugt eine Wetter-/Szenariendatenbank und separate "
            "Verifikationsgrafiken mit transparenter Literaturkalibrierung."
        )
    )
    parser.add_argument(
        "--smard-db",
        type=Path,
        default=SCRIPT_DIR / "smard_stundendaten_2021_2025.sqlite",
        help="vorhandene SMARD-SQLite (keine SMARD-Netzabfrage)",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=SCRIPT_DIR / "wetterdaten_szenarien.sqlite",
        help="eine gemeinsame SQLite für Wetter, Modelle und Ergebnisse",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=SCRIPT_DIR / "verifikationsgrafiken",
        help="Zielordner für SVG, PNG, CSV und Bericht",
    )
    parser.add_argument(
        "--years",
        default="2025",
        help="Kalenderjahre: 2025, 2021-2025 oder kommasepariert",
    )
    parser.add_argument("--site", default="Kassel", help="Standortname")
    parser.add_argument("--latitude", type=float, default=51.3127)
    parser.add_argument("--longitude", type=float, default=9.4797)
    parser.add_argument("--elevation", type=float, default=167.0)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="nur vorhandene Wetterstunden in der Ergebnisdatenbank verwenden",
    )
    parser.add_argument(
        "--refresh-weather",
        action="store_true",
        help="Wetterstunden für den gewählten Zeitraum neu laden",
    )
    parser.add_argument(
        "--export-hourly-csv",
        action="store_true",
        help="zusätzlich große CSV mit allen Stundenwerten schreiben",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        run(args)
    except (RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
