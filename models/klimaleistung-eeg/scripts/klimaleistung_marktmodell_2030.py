#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Sebastian Putzke
# SPDX-License-Identifier: Apache-2.0
"""
Stündliches Klimaleistungs-Marktmodell Deutschland 2030
========================================================

Zweck
-----
Erzeugt eine erste, transparente Angebots-/Nachfrage-Simulation für Strom
mit strengem stündlichem THG-freiem Nachweis. Das Modell verbindet:

1. relative Einspeiseprofile des SMARD-Wetterjahres 2024,
2. EEG-Mittelfristprognose 2030 (Trend-Szenario),
3. eine synthetische stündliche 24/7-Nachfrage,
4. 30 % Fernwärme aus Großwärmepumpen als Sockellast-Szenario,
5. Angebotsstufen aus den für 2030 prognostizierten EEG-Förderlücken,
6. einen stündlichen Mindest-Clearingpreis und eine Preisgarantie-Sensitivität.

Wichtig
-------
Der berechnete Preis ist die anbieterseitige MINDEST-Clearingprämie. Ohne
reale Käufergebote ist er kein empirischer Marktpreis. In Stunden mit
Unterdeckung setzt das Modell eine frei parametrierbare Knappheitsprämie.

Ausgabe
-------
- klimaleistung_marktmodell_2030.res
- klimaleistung_marktmodell_2030_stunden.csv
- klimaleistung_angebotsstufen_2030.csv
- klimaleistung_pilotgarantie_2030.csv
- 01_klimaleistung_preis_und_residuallast_2030.png/.svg
- 02_klimaleistung_angebots_nachfrage_dauerlinie_2030.png/.svg
- 03_klimaleistung_residuallast_heatmap_2030.png/.svg
- 01_ERKLAERTEXT_KLIMALEISTUNG_MARKTMODELL_2030.md

Beispiel
--------
python klimaleistung_marktmodell_2030.py \
  --smard-db smard_stundendaten_2021_2025.sqlite \
  --weather-db wetter_und_referenzdaten.sqlite \
  --output-dir klimaleistung_marktmodell_2030
"""

from __future__ import annotations

import argparse
import csv
import math
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np

MODEL_VERSION = "1.2.0"
MODEL_YEAR = 2030
WEATHER_YEAR = 2024
WEATHER_SITE = "kassel_mitte"
AUTHOR_NAME = "Sebastian Putzke"
COPYRIGHT_YEAR = 2026
LICENSE_LABEL = "CC BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"

# Quellen:
# EEG-Mittelfristprognose 2026-2030 (Trend-Szenario):
# https://www.netztransparenz.de/xspproxy/api/staticfiles/ntp-relaunch/dokumente/
# erneuerbare%20energien%20und%20umlagen/eeg/eeg%20finanzierung/
# mittelfristprognose/2026-2030/20251015_endbericht%20ie%20leipzig.pdf
#
# Fernwärme 2030: 137 TWh Nachfrage, 156 TWh Erzeugung inkl. Verluste:
# https://www.umweltbundesamt.de/system/files/medien/1410/publikationen/
# 2021-08-05_cc_54-2021_effiziente_waerme-kaelteversorgung.pdf
#
# WPG §29: mindestens 30 % jährliche Nettowärmeerzeugung ab 2030:
# https://www.gesetze-im-internet.de/wpg/__29.html
#
# Großwärmepumpen: Carnot-Gütegrad typischerweise 40-60 %, hier 50 %:
# https://www.agora-energiewende.de/fileadmin/Projekte/2022/
# 2022-11_DE_Large_Scale_Heatpumps/A-EW_293_Rollout_Grosswaermepumpen_WEB.pdf

# 2030 physisch marktverfügbare Erzeugung [GWh]. Eigenverbrauch wird abgezogen.
# Anschlussförderung bleibt marktverfügbar. Rundungsdifferenz von 1 GWh in den
# Veräußerungsformen gegenüber den Technologietotals ist quellenbedingt.
ANNUAL_MARKETABLE_GWH = {
    "hydro": 6_036 - 430,
    "biomass": 38_636 - 246,
    "geothermal": 237,
    "wind_onshore": 214_284,
    "wind_offshore": 53_995,
    "pv_ground": 57_743 - 155,
    "pv_other": 116_259 - 21_858,
}

SMARD_PROFILE_COLUMN = {
    "hydro": "hydro_mwh",
    "biomass": "biomass_mwh",
    "geothermal": "other_renewable_mwh",
    "wind_onshore": "wind_onshore_mwh",
    "wind_offshore": "wind_offshore_mwh",
    "pv_ground": "pv_mwh",
    "pv_other": "pv_mwh",
}

# Optimistische 2030-Nachfrage nach Strom mit strengem stündlichem THG-freiem
# Nachweis [TWh]. Die Annahmen bilden bewusst ein hohes Markthochlauf-Szenario.
#
# BNetzA-Monitoring 2025: 2024 wurden 74,0 TWh Ökostrom an Haushalte und
# 62,5 TWh an weitere Letztverbraucher geliefert. Im Szenario wechseln 25 %
# dieser Mengen bis 2030 auf einen strengen stündlichen Nachweis.
#
# Öffentliche Hand: die letzte umfassende nationale Größenordnung von 18 TWh
# wird vollständig angesetzt. DB: 80 % des Traktionsstroms 2024 von 7,172 TWh.
# Diese Bruttobetrachtung kann Überschneidungen mit den heutigen Ökostrommengen
# enthalten; sie wird deshalb ausdrücklich als optimistisches Ober-Szenario
# ausgewiesen und zusätzlich mit einer Überschneidungssensitivität dokumentiert.
GREEN_TARIFF_HOUSEHOLDS_2024_TWH = 74.0
GREEN_TARIFF_OTHER_2024_TWH = 62.5
GREEN_TARIFF_SWITCH_SHARE_2030 = 0.25
PUBLIC_SECTOR_ELECTRICITY_TWH = 18.0
DB_TRACTION_ELECTRICITY_2024_TWH = 7.172
DB_RENEWABLE_SHARE_2030 = 0.80

STRICT_DEMAND_TWH = {
    "rfnbo_electrolysis": 40.0,
    "data_centres": 15.5,
    "public_sector": PUBLIC_SECTOR_ELECTRICITY_TWH,
    "db_traction": DB_TRACTION_ELECTRICITY_2024_TWH * DB_RENEWABLE_SHARE_2030,
    "green_tariff_households": GREEN_TARIFF_HOUSEHOLDS_2024_TWH * GREEN_TARIFF_SWITCH_SHARE_2030,
    "green_tariff_other": GREEN_TARIFF_OTHER_2024_TWH * GREEN_TARIFF_SWITCH_SHARE_2030,
}

# Erste Überschneidungssensitivität: Der 25-%-Umstiegspool kann bereits Teile
# von Rechenzentren, öffentlicher Hand und DB enthalten. Mangels Aufschlüsselung
# wird keine Korrektur im Hauptszenario vorgenommen. Für die Sensitivität wird
# pauschal ein Viertel der separat erfassten nichtprivaten Lasten abgezogen.
OVERLAP_SENSITIVITY_SHARE = 0.25

DEMAND_LABELS = {
    "rfnbo_electrolysis": "RFNBO-Elektrolyse",
    "data_centres": "Rechenzentren / Cloud / KI",
    "public_sector": "Öffentliche Hand",
    "db_traction": "DB-Traktionsstrom / öffentliche Beteiligung",
    "green_tariff_households": "25 % heutige Haushalts-Ökostrommenge",
    "green_tariff_other": "25 % heutige Ökostrommenge weiterer Letztverbraucher",
}

DEMAND_DERIVATIONS = {
    "rfnbo_electrolysis": "10 GW × 4.000 Volllaststunden; hohes Zielerreichungsszenario",
    "data_centres": "31 TWh Gesamtverbrauch 2030 × 50 % strenger Nachweis",
    "public_sector": "18 TWh geschätzter öffentlicher Stromverbrauch × 100 %",
    "db_traction": "7,172 TWh Traktionsstrom × 80 % erneuerbarer Bahnstrom 2030",
    "green_tariff_households": "74,0 TWh Ökostrom 2024 × 25 % Umstieg",
    "green_tariff_other": "62,5 TWh Ökostrom 2024 × 25 % Umstieg",
}

# Fossiler Restmix einschließlich separat ermittelter Vorkettenaufschläge.
FOSSIL_TOTAL_T_CO2E_MWH = {
    "lignite_mwh": 1.093,
    "hard_coal_mwh": 0.971,
    "gas_mwh": 0.580,
    "other_conventional_mwh": 0.994,
}

# 2030 Basepreis und Marktwertfaktoren der EEG-Mittelfristprognose.
BASE_PRICE_2030_EUR_MWH = 70.0
MARKET_VALUE_FACTOR_2030 = {
    "hydro": 1.00,
    "biomass": 1.00,
    "geothermal": 1.00,
    "wind_onshore": 0.89,
    "wind_offshore": 0.89,
    "pv_ground": 0.46,
    "pv_other": 0.46,
}

# Fernwärmeszenario. 156 TWh entspricht der 2030-Erzeugung einschließlich
# Netzverlusten in der UBA-Potenzialanalyse. Die 30 % sind eine bewusste
# Elektrifizierungsannahme: real können auch Geothermie, Biomasse, Solarthermie
# und unvermeidbare Abwärme den gesetzlichen Anteil erfüllen.
DISTRICT_HEAT_NET_GENERATION_TWH = 156.0
DISTRICT_HEAT_HP_SHARE = 0.30
DISTRICT_HEAT_BASE_SHARE = 0.20
HEATING_BALANCE_TEMP_C = 15.0
DISTRICT_HEAT_SINK_TEMP_C = 90.0
CARNOT_QUALITY_FACTOR = 0.50

DEFAULT_CLIMATE_FLOOR_EUR_T = 74.0
DEFAULT_SCARCITY_PREMIUM_EUR_MWH = 200.0
DEFAULT_PILOT_TWH = (10.0, 25.0, 50.0, 75.0, 100.0, 125.0, 150.0)


@dataclass(frozen=True)
class OfferTranche:
    technology: str
    label: str
    annual_gwh: float
    offer_eur_mwh: float


@dataclass
class HourlyInput:
    timestamp_ms: np.ndarray
    timestamp_utc: list[str]
    timestamp_berlin: list[str]
    weather_local_dt: list[datetime]
    model_local_dt: list[datetime]
    rows: list[sqlite3.Row]
    temp_c: np.ndarray


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smard-db", type=Path, required=True)
    parser.add_argument("--weather-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("klimaleistung_marktmodell_2030"))
    parser.add_argument("--weather-year", type=int, default=WEATHER_YEAR)
    parser.add_argument("--weather-site", default=WEATHER_SITE)
    parser.add_argument("--climate-floor-eur-t", type=float, default=DEFAULT_CLIMATE_FLOOR_EUR_T)
    parser.add_argument("--scarcity-premium-eur-mwh", type=float, default=DEFAULT_SCARCITY_PREMIUM_EUR_MWH)
    return parser.parse_args()


def ensure_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} nicht gefunden: {path}")


def load_hourly_inputs(smard_db: Path, weather_db: Path, year: int, site: str) -> HourlyInput:
    ensure_file(smard_db, "SMARD-Datenbank")
    ensure_file(weather_db, "Wetterdatenbank")

    con = sqlite3.connect(smard_db)
    con.row_factory = sqlite3.Row
    source_rows = con.execute(
        "SELECT * FROM hourly WHERE local_year=? ORDER BY timestamp_ms", (year,)
    ).fetchall()
    con.close()
    if len(source_rows) not in (8760, 8784):
        raise ValueError(f"Erwartet 8.760/8.784 SMARD-Stunden, gefunden: {len(source_rows)}")

    # 2030 ist kein Schaltjahr. Beim Wetterjahr 2024 werden die 24 lokalen
    # Stunden des 29. Februar entfernt; alle Jahresprofile werden danach erneut
    # exakt auf ihre 2030-Mengen normiert.
    rows = [
        row for row in source_rows
        if not (datetime.fromisoformat(str(row["timestamp_berlin"])).month == 2
                and datetime.fromisoformat(str(row["timestamp_berlin"])).day == 29)
    ]
    if len(rows) != 8760:
        raise ValueError(f"Nach Entfernung des 29. Februar werden 8.760 Stunden erwartet, gefunden: {len(rows)}")

    con = sqlite3.connect(weather_db)
    weather_rows = con.execute(
        "SELECT timestamp_ms, temp_c FROM weather_hourly WHERE site_id=? ORDER BY timestamp_ms",
        (site,),
    ).fetchall()
    con.close()
    weather = {int(ts): float(temp) for ts, temp in weather_rows}

    timestamp_ms = np.array([int(row["timestamp_ms"]) for row in rows], dtype=np.int64)
    missing = [int(ts) for ts in timestamp_ms if int(ts) not in weather]
    if missing:
        raise ValueError(f"Wetterdaten fehlen für {len(missing)} SMARD-Stunden; erstes Timestamp: {missing[0]}")

    weather_local_dt = [datetime.fromisoformat(str(row["timestamp_berlin"])) for row in rows]
    model_local_dt = [datetime(MODEL_YEAR, 1, 1) + timedelta(hours=i) for i in range(8760)]
    temp_c = np.array([weather[int(ts)] for ts in timestamp_ms], dtype=float)
    return HourlyInput(
        timestamp_ms=timestamp_ms,
        timestamp_utc=[str(row["timestamp_utc"]) for row in rows],
        timestamp_berlin=[str(row["timestamp_berlin"]) for row in rows],
        weather_local_dt=weather_local_dt,
        model_local_dt=model_local_dt,
        rows=rows,
        temp_c=temp_c,
    )


def normalize_profile(raw: np.ndarray, annual_mwh: float, label: str) -> np.ndarray:
    raw = np.asarray(raw, dtype=float)
    if np.any(~np.isfinite(raw)) or np.any(raw < 0):
        raise ValueError(f"Ungültiges Profil: {label}")
    total = float(raw.sum())
    if total <= 0:
        raise ValueError(f"Profil hat keine positive Jahresmenge: {label}")
    result = raw / total * annual_mwh
    if not math.isclose(float(result.sum()), annual_mwh, rel_tol=0.0, abs_tol=max(1e-4, annual_mwh * 1e-10)):
        raise AssertionError(f"Normierung fehlgeschlagen: {label}")
    return result


def build_supply(inputs: HourlyInput) -> dict[str, np.ndarray]:
    supply: dict[str, np.ndarray] = {}
    for technology, annual_gwh in ANNUAL_MARKETABLE_GWH.items():
        raw = np.array([float(row[SMARD_PROFILE_COLUMN[technology]]) for row in inputs.rows])
        supply[technology] = normalize_profile(raw, annual_gwh * 1_000.0, technology)
    return supply


def easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def nationwide_holidays(year: int) -> set[date]:
    easter = easter_sunday(year)
    return {
        date(year, 1, 1),
        easter - timedelta(days=2),
        easter + timedelta(days=1),
        date(year, 5, 1),
        easter + timedelta(days=39),
        easter + timedelta(days=50),
        date(year, 10, 3),
        date(year, 12, 25),
        date(year, 12, 26),
    }


def daylight_indicator(local_dt: datetime) -> float:
    day_of_year = local_dt.timetuple().tm_yday
    daylight_hours = 12.0 + 4.2 * math.sin(2.0 * math.pi * (day_of_year - 80) / 365.25)
    sunrise = 12.0 - daylight_hours / 2.0
    sunset = 12.0 + daylight_hours / 2.0
    hour = local_dt.hour + local_dt.minute / 60.0
    return 1.0 if hour < sunrise or hour >= sunset else 0.05


def raw_strict_demand_profile(category: str, local_dt: datetime, holidays: set[date]) -> float:
    hour = local_dt.hour
    weekday = local_dt.weekday()
    weekend = weekday >= 5
    holiday = local_dt.date() in holidays
    month = local_dt.month

    if category == "rfnbo_electrolysis":
        # Flexible, erneuerbarenorientierte Fahrweise; die Jahresmenge bleibt
        # fest. Kein perfekter Preisoptimierer und keine saisonale Speicherung.
        hourly = 1.20 if hour <= 5 else 0.88 if hour <= 9 else 1.08 if hour <= 15 else 0.72 if hour <= 20 else 1.12
        weekly = 1.08 if weekend or holiday else 0.97
        seasonal = 1.05 if month in (3, 4, 5, 6, 7) else 0.97
        maintenance = 0.84 if month == 8 and 8 <= local_dt.day <= 21 else 1.0
        return hourly * weekly * seasonal * maintenance * 0.98

    if category == "data_centres":
        daily = 1.015 if 8 <= hour <= 21 else 0.985
        weekly = 0.99 if weekend or holiday else 1.0
        cooling = 1.07 if month in (6, 7, 8) else 0.98 if month in (12, 1, 2) else 1.0
        maintenance = 0.995 if month == 4 and 10 <= local_dt.day <= 16 else 1.0
        return daily * weekly * cooling * maintenance

    if category == "public_sector":
        # Aggregat aus Verwaltung/Schulen, Kliniken, Wasser/Abwasser und
        # Straßenbeleuchtung. Das hohe Szenario setzt den gesamten geschätzten
        # öffentlichen Stromverbrauch mit strengem Nachweis an.
        if weekend or holiday:
            office = 0.22 if 8 <= hour <= 18 else 0.12
        else:
            office = 1.00 if 8 <= hour <= 17 else 0.45 if 6 <= hour <= 20 else 0.15
        if month in (7, 8):
            office *= 0.82
        hospital = 0.95 + (0.05 if 7 <= hour <= 20 else 0.0)
        water = 0.88 + (0.12 if 6 <= hour <= 22 else 0.0)
        lighting = daylight_indicator(local_dt)
        return 0.50 * office + 0.20 * hospital + 0.15 * water + 0.15 * lighting

    if category == "db_traction":
        # Synthetisches Bahnstromprofil: ausgeprägter Personenverkehr morgens
        # und abends, Güter-/Nachtverkehr als Sockel; Feiertage reduziert.
        if 0 <= hour <= 4:
            daily = 0.48
        elif hour == 5:
            daily = 0.72
        elif 6 <= hour <= 9:
            daily = 1.28
        elif 10 <= hour <= 15:
            daily = 1.00
        elif 16 <= hour <= 19:
            daily = 1.32
        else:
            daily = 0.78
        weekly = 0.87 if weekend else 1.0
        if holiday:
            weekly *= 0.88
        seasonal = 1.03 if month in (6, 7, 8, 12) else 0.99
        return daily * weekly * seasonal

    if category == "green_tariff_households":
        # 25 % der heutigen Haushalts-Ökostrommenge wechseln im Szenario zu
        # stündlichem Nachweis. Typisches Haushaltsprofil mit Morgen-/Abendspitze.
        if 0 <= hour <= 5:
            daily = 0.52
        elif 6 <= hour <= 8:
            daily = 1.05
        elif 9 <= hour <= 15:
            daily = 0.78
        elif 16 <= hour <= 21:
            daily = 1.35
        else:
            daily = 0.85
        weekly = 1.07 if weekend or holiday else 1.0
        seasonal = 1.13 if month in (12, 1, 2) else 0.92 if month in (6, 7, 8) else 1.0
        return daily * weekly * seasonal

    if category == "green_tariff_other":
        # 25 % der heutigen Ökostrommenge weiterer Letztverbraucher.
        # Mischprofil aus kontinuierlicher Industrie, Zwei-Schicht-Betrieben
        # und Gewerbe/Büro. Öffentliche und DB-Anteile können statistisch
        # überlappen; das ist Teil des transparenten Ober-Szenarios.
        continuous = 0.96 if weekend or holiday else 1.0
        two_shift = 0.22 if weekend or holiday else 1.0 if 6 <= hour <= 21 else 0.30
        office = 0.20 if weekend or holiday else 1.0 if 8 <= hour <= 18 else 0.22
        summer = 0.82 if month == 8 and 1 <= local_dt.day <= 14 else 1.0
        winter = 0.78 if month == 12 and local_dt.day >= 24 else 1.0
        return (0.50 * continuous + 0.30 * two_shift + 0.20 * office) * summer * winter

    raise KeyError(category)


def build_strict_demand(inputs: HourlyInput) -> dict[str, np.ndarray]:
    holidays = nationwide_holidays(MODEL_YEAR)
    demand: dict[str, np.ndarray] = {}
    for category, annual_twh in STRICT_DEMAND_TWH.items():
        raw = np.array([raw_strict_demand_profile(category, dt, holidays) for dt in inputs.model_local_dt])
        demand[category] = normalize_profile(raw, annual_twh * 1_000_000.0, category)
    return demand


def build_district_heat_hp(inputs: HourlyInput) -> dict[str, np.ndarray | float | int]:
    hours = len(inputs.temp_c)
    annual_heat_mwh = DISTRICT_HEAT_NET_GENERATION_TWH * 1_000_000.0
    target_hp_heat_mwh = annual_heat_mwh * DISTRICT_HEAT_HP_SHARE

    # Fernwärme-Gesamtlast: konstante Sockellast plus temperaturabhängige Raumwärme.
    base_heat = np.full(hours, annual_heat_mwh * DISTRICT_HEAT_BASE_SHARE / hours)
    degree_hours = np.maximum(HEATING_BALANCE_TEMP_C - inputs.temp_c, 0.0)
    if float(degree_hours.sum()) <= 0:
        raise ValueError("Temperaturprofil erzeugt keine Heizgradstunden")
    space_heat = normalize_profile(
        degree_hours,
        annual_heat_mwh * (1.0 - DISTRICT_HEAT_BASE_SHARE),
        "Fernwärme-Raumwärme",
    )
    total_heat = base_heat + space_heat

    # Sockellast zuerst: thermische WP-Leistung wird per Bisektion so gewählt,
    # dass min(Fernwärmelast_h, WP-Leistung) exakt 30 % Jahreswärme ergibt.
    lower = 0.0
    upper = float(total_heat.max())
    iterations = 0
    for iterations in range(1, 201):
        midpoint = 0.5 * (lower + upper)
        produced = float(np.minimum(total_heat, midpoint).sum())
        if produced < target_hp_heat_mwh:
            lower = midpoint
        else:
            upper = midpoint
        if upper - lower < 1e-7:
            break
    thermal_capacity_mw = 0.5 * (lower + upper)
    hp_heat = np.minimum(total_heat, thermal_capacity_mw)

    # Stündlicher COP aus 50 % Carnot-Gütegrad, Außenluft als Wärmequelle,
    # Fernwärme-Senkentemperatur exakt 90 °C. Keine pauschale Jahresarbeitszahl.
    hot_kelvin = DISTRICT_HEAT_SINK_TEMP_C + 273.15
    cold_kelvin = inputs.temp_c + 273.15
    temperature_lift = hot_kelvin - cold_kelvin
    if np.any(temperature_lift <= 0):
        raise ValueError("Ungültiger Temperaturhub für Wärmepumpe")
    cop = CARNOT_QUALITY_FACTOR * hot_kelvin / temperature_lift
    hp_electricity = hp_heat / cop

    target_error_mwh = float(hp_heat.sum() - target_hp_heat_mwh)
    if abs(target_error_mwh) > 1.0:
        raise AssertionError(f"WP-Zielmenge verfehlt: {target_error_mwh:.6f} MWh")

    # Sensitivitätsprofile: proportional zu jeder Laststunde und vollkommen flach.
    proportional_heat = total_heat * DISTRICT_HEAT_HP_SHARE
    flat_heat = np.full(hours, target_hp_heat_mwh / hours)

    return {
        "total_heat_mwh": total_heat,
        "hp_heat_mwh": hp_heat,
        "cop": cop,
        "hp_electricity_mwh": hp_electricity,
        "thermal_capacity_mw": thermal_capacity_mw,
        "iterations": iterations,
        "target_error_mwh": target_error_mwh,
        "proportional_hp_electricity_mwh": proportional_heat / cop,
        "flat_hp_electricity_mwh": flat_heat / cop,
    }


def build_fossil_intensity(inputs: HourlyInput) -> np.ndarray:
    fossil_generation = np.zeros(len(inputs.rows), dtype=float)
    emissions = np.zeros(len(inputs.rows), dtype=float)
    for column, total_emission in FOSSIL_TOTAL_T_CO2E_MWH.items():
        generation = np.array([float(row[column]) for row in inputs.rows])
        fossil_generation += generation
        emissions += generation * total_emission
    intensity = np.divide(
        emissions,
        fossil_generation,
        out=np.full(len(inputs.rows), np.nan),
        where=fossil_generation > 0,
    )
    if np.any(np.isnan(intensity)):
        intensity[np.isnan(intensity)] = float(np.nanmedian(intensity))
    return intensity


def market_value_eur_mwh(technology: str) -> float:
    return BASE_PRICE_2030_EUR_MWH * MARKET_VALUE_FACTOR_2030[technology]


def offer_tranches() -> list[OfferTranche]:
    tranches: list[OfferTranche] = []

    def add(technology: str, label: str, annual_gwh: float, offer: float) -> None:
        if annual_gwh > 0:
            tranches.append(OfferTranche(technology, label, annual_gwh, max(0.0, offer)))

    # Mengen: Anhang B; Zahlungen: Anhang C der EEG-Mittelfristprognose.
    add("hydro", "sonstige Direktvermarktung/Anschlussförderung", 1_066 + 29, 0.0)
    add("hydro", "Marktprämie", 3_815, 109.8e6 / (3_815e3))
    add("hydro", "feste Einspeisevergütung", 697, 76.8e6 / (697e3) - market_value_eur_mwh("hydro"))

    add("biomass", "sonstige Direktvermarktung/Anschlussförderung", 5_747 + 57, 0.0)
    add("biomass", "Marktprämie inkl. Flexibilitätsprämie", 31_410, (3_448.2 + 461.2) * 1e6 / (31_410e3))
    add("biomass", "feste Einspeisevergütung", 1_177, 224.0e6 / (1_177e3) - market_value_eur_mwh("biomass"))

    add("geothermal", "Marktprämie", 235, 38.4e6 / (235e3))
    add("geothermal", "feste Einspeisevergütung", 2, 0.4e6 / (2e3) - market_value_eur_mwh("geothermal"))

    add("wind_onshore", "sonstige Direktvermarktung", 26_496, 0.0)
    add("wind_onshore", "Marktprämie", 186_983, 1_790.5e6 / (186_983e3))
    add("wind_onshore", "feste Einspeisevergütung", 804, 57.2e6 / (804e3) - market_value_eur_mwh("wind_onshore"))

    add("wind_offshore", "sonstige Direktvermarktung", 43_609, 0.0)
    add("wind_offshore", "Marktprämie", 10_386, 827.1e6 / (10_386e3))

    add("pv_ground", "sonstige Direktvermarktung/Anschlussförderung", 13_879 + 40, 0.0)
    add("pv_ground", "Marktprämie", 40_832, 1_198.6e6 / (40_832e3))
    add("pv_ground", "feste Einspeisevergütung", 2_837, 556.0e6 / (2_837e3) - market_value_eur_mwh("pv_ground"))

    add("pv_other", "sonstige Direktvermarktung/Anschlussförderung", 2_958 + 3_646, 0.0)
    add("pv_other", "Marktprämie", 15_127, 765.1e6 / (15_127e3))
    add("pv_other", "feste Einspeisevergütung", 72_670, 6_816.7e6 / (72_670e3) - market_value_eur_mwh("pv_other"))

    return tranches


def build_tranche_profiles(
    technology_supply: dict[str, np.ndarray], tranches: Iterable[OfferTranche]
) -> list[tuple[OfferTranche, np.ndarray]]:
    result: list[tuple[OfferTranche, np.ndarray]] = []
    for tranche in tranches:
        profile = normalize_profile(
            technology_supply[tranche.technology],
            tranche.annual_gwh * 1_000.0,
            f"{tranche.technology}/{tranche.label}",
        )
        result.append((tranche, profile))
    return result


def clear_market(
    demand_mwh: np.ndarray,
    tranche_profiles: list[tuple[OfferTranche, np.ndarray]],
    scarcity_premium_eur_mwh: float,
) -> dict[str, np.ndarray]:
    ordered = sorted(tranche_profiles, key=lambda item: item[0].offer_eur_mwh)
    hours = len(demand_mwh)
    price = np.zeros(hours, dtype=float)
    accepted = np.zeros(hours, dtype=float)
    shortage = np.zeros(hours, dtype=float)
    marginal = np.full(hours, "", dtype=object)

    for hour in range(hours):
        remaining = float(demand_mwh[hour])
        for tranche, profile in ordered:
            available = float(profile[hour])
            if remaining > 1e-9 and available > 0:
                taken = min(remaining, available)
                accepted[hour] += taken
                remaining -= taken
                price[hour] = tranche.offer_eur_mwh
                marginal[hour] = f"{tranche.technology}: {tranche.label}"
        if remaining > 1e-9:
            shortage[hour] = remaining
            price[hour] = scarcity_premium_eur_mwh
            marginal[hour] = "Knappheit/zusätzliche gesicherte THG-freie Lieferung"

    return {
        "price_eur_mwh": price,
        "accepted_mwh": accepted,
        "shortage_mwh": shortage,
        "marginal_offer": marginal,
    }


def guarantee_for_pilot(
    annual_pilot_twh: float,
    total_supply_mwh: np.ndarray,
    demand_mwh: np.ndarray,
    private_price_eur_mwh: np.ndarray,
    climate_floor_eur_mwh: np.ndarray,
) -> dict[str, float]:
    pilot_supply = normalize_profile(total_supply_mwh, annual_pilot_twh * 1_000_000.0, f"Pilot {annual_pilot_twh:g} TWh")
    privately_absorbed = np.minimum(pilot_supply, demand_mwh)
    unmatched = np.maximum(pilot_supply - demand_mwh, 0.0)
    top_up = np.maximum(climate_floor_eur_mwh - private_price_eur_mwh, 0.0) * privately_absorbed
    last_resort_purchase = climate_floor_eur_mwh * unmatched
    return {
        "pilot_twh": annual_pilot_twh,
        "private_twh": float(privately_absorbed.sum() / 1e6),
        "state_purchase_twh": float(unmatched.sum() / 1e6),
        "state_purchase_hours": int(np.count_nonzero(unmatched > 1e-9)),
        "top_up_billion_eur": float(top_up.sum() / 1e9),
        "last_resort_billion_eur": float(last_resort_purchase.sum() / 1e9),
        "total_guarantee_billion_eur": float((top_up.sum() + last_resort_purchase.sum()) / 1e9),
    }


def simulate_variant(
    demand_without_heat: np.ndarray,
    hp_electricity: np.ndarray,
    tranche_profiles: list[tuple[OfferTranche, np.ndarray]],
    total_supply: np.ndarray,
    intensity: np.ndarray,
    climate_floor_eur_t: float,
    scarcity_premium_eur_mwh: float,
) -> dict[str, float]:
    demand = demand_without_heat + hp_electricity
    clearing = clear_market(demand, tranche_profiles, scarcity_premium_eur_mwh)
    price_t = clearing["price_eur_mwh"] / intensity
    floor_mwh = climate_floor_eur_t * intensity
    top_up = np.maximum(floor_mwh - clearing["price_eur_mwh"], 0.0) * clearing["accepted_mwh"]
    return {
        "hp_electricity_twh": float(hp_electricity.sum() / 1e6),
        "hp_peak_gw": float(hp_electricity.max() / 1e3),
        "total_demand_twh": float(demand.sum() / 1e6),
        "shortage_hours": int(np.count_nonzero(clearing["shortage_mwh"] > 1e-9)),
        "shortage_twh": float(clearing["shortage_mwh"].sum() / 1e6),
        "hours_price_at_or_above_floor": int(np.count_nonzero(price_t >= climate_floor_eur_t)),
        "all_matched_top_up_billion_eur": float(top_up.sum() / 1e9),
        "surplus_twh": float(np.maximum(total_supply - demand, 0.0).sum() / 1e6),
    }


def write_semicolon_csv(path: Path, header: list[str], rows: Iterable[Iterable[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)


def fmt_de(value: float, digits: int = 2) -> str:
    text = f"{value:,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def create_plots(
    output_dir: Path,
    price_eur_t: np.ndarray,
    price_eur_mwh: np.ndarray,
    net_balance_mwh: np.ndarray,
    total_supply_mwh: np.ndarray,
    total_demand_mwh: np.ndarray,
    floor_eur_t: float,
    scarcity_premium_eur_mwh: float,
) -> None:
    hours = np.arange(1, len(price_eur_t) + 1)
    shortage_mask = net_balance_mwh < -1e-9
    known_mask = ~shortage_mask
    shortage_hours = int(shortage_mask.sum())

    # Gemeinsame Artikelgrafik: oben anbieterseitige Preisuntergrenze, unten
    # physische Angebots-/Nachfrage-Passung. Die beiden Felder sind bewusst
    # separat sortiert; benachbarte Punkte sind keine Kalenderstunden.
    known_prices = np.sort(price_eur_t[known_mask])[::-1]
    known_x = np.arange(shortage_hours + 1, len(price_eur_t) + 1)

    supply_twh = float(total_supply_mwh.sum() / 1e6)
    demand_twh = float(total_demand_mwh.sum() / 1e6)
    shortage_twh = float(np.maximum(-net_balance_mwh, 0.0).sum() / 1e6)
    max_shortage_gw = float(np.maximum(-net_balance_mwh, 0.0).max() / 1_000.0)

    fig, (ax_price, ax_balance) = plt.subplots(
        2,
        1,
        figsize=(13.2, 9.4),
        gridspec_kw={"height_ratios": [1.0, 1.05], "hspace": 0.30},
    )
    fig.suptitle(
        "Stündlicher Wert THG-freien Stroms 2030",
        x=0.075,
        y=0.982,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.075,
        0.947,
        "Angebotsseitige Preisuntergrenze und stündliche Deckung in einem transparent optimistischen 24/7-Nachfrageszenario",
        ha="left",
        fontsize=10.5,
        color="#4A4A4A",
    )
    fig.text(
        0.075,
        0.916,
        f"Szenario: {demand_twh:.0f} TWh strenge Nachfrage · {supply_twh:.0f} TWh THG-freies Angebot",
        ha="left",
        fontsize=10,
        color="#4A4A4A",
    )

    if shortage_hours:
        ax_price.axvspan(
            0.5,
            shortage_hours + 0.5,
            facecolor="#F4E8E8",
            hatch="////",
            edgecolor="#A33A3A",
            linewidth=0.8,
            alpha=0.95,
        )
        ax_price.text(
            max(1, shortage_hours * 0.62),
            max(floor_eur_t * 1.33, np.nanpercentile(known_prices, 99) * 0.78),
            f"{shortage_hours} Stunden\nPreis offen:\nzusätzliches Angebot fehlt",
            ha="center",
            va="center",
            fontsize=9.1,
            color="#7A1F1F",
            bbox={
                "facecolor": "white",
                "edgecolor": "#A33A3A",
                "alpha": 0.90,
                "boxstyle": "round,pad=0.40",
            },
        )
    ax_price.plot(
        known_x,
        known_prices,
        linewidth=2.0,
        color="#24527A",
        label="anbieterseitige Preisuntergrenze",
    )
    ax_price.axhline(
        floor_eur_t,
        linestyle="--",
        linewidth=1.6,
        color="#D6A100",
        label=f"beispielhafter Mindestpreis: {floor_eur_t:g} €/t",
    )
    below = known_prices < floor_eur_t
    if np.any(below):
        ax_price.fill_between(
            known_x,
            known_prices,
            floor_eur_t,
            where=below,
            color="#F2C230",
            alpha=0.20,
            label="mögliche staatliche Aufstockung",
        )
    ax_price.set_xlim(1, len(price_eur_t))
    ax_price.set_ylim(bottom=0)
    ax_price.set_ylabel("Klimaleistungspreis [€/t CO₂e]")
    ax_price.set_xlabel("Jahresstunden, nach Preis absteigend sortiert")
    ax_price.set_title(
        "A · Anbieterseitige Preisuntergrenze",
        loc="left",
        fontsize=11.5,
        fontweight="bold",
        pad=8,
    )
    ax_price.grid(True, axis="y", alpha=0.22)
    ax_price.spines[["top", "right"]].set_visible(False)
    ax_price.legend(loc="upper right", frameon=False, fontsize=9.2)

    balance_order = np.argsort(net_balance_mwh)
    sorted_supply = total_supply_mwh[balance_order] / 1_000.0
    sorted_demand = total_demand_mwh[balance_order] / 1_000.0
    sorted_balance = net_balance_mwh[balance_order] / 1_000.0
    ax_balance.plot(
        hours,
        sorted_supply,
        linewidth=1.35,
        color="#75B9E6",
        alpha=0.88,
        label="THG-freies Angebot",
    )
    ax_balance.plot(
        hours,
        sorted_demand,
        linewidth=1.25,
        color="#3D434A",
        alpha=0.92,
        label="strenge 24/7-Nachfrage",
    )
    ax_balance.plot(
        hours,
        sorted_balance,
        linewidth=1.35,
        color="#24527A",
        label="Differenz",
    )
    ax_balance.fill_between(
        hours,
        0,
        sorted_balance,
        where=sorted_balance >= 0,
        color="#4F8A4C",
        alpha=0.16,
        label="Überschuss",
    )
    ax_balance.fill_between(
        hours,
        0,
        sorted_balance,
        where=sorted_balance < 0,
        color="#C94C4C",
        alpha=0.25,
        label="Unterdeckung",
    )
    ax_balance.axhline(0.0, linestyle=":", linewidth=1.0, color="#555555")
    ax_balance.set_xlim(1, len(price_eur_t))
    ax_balance.set_xlabel("Jahresstunden, nach Angebot − Nachfrage aufsteigend sortiert")
    ax_balance.set_ylabel("Leistung [GW]")
    ax_balance.set_title(
        "B · Stündliche Differenz zwischen Angebot und Nachfrage",
        loc="left",
        fontsize=11.5,
        fontweight="bold",
        pad=8,
    )
    ax_balance.grid(True, axis="y", alpha=0.22)
    ax_balance.spines[["top", "right"]].set_visible(False)
    ax_balance.legend(loc="upper left", ncol=3, frameon=False, fontsize=9.0)
    ax_balance.text(
        0.985,
        0.055,
        f"Unterdeckung: {shortage_hours} h · {shortage_twh:.2f} TWh\nmaximal {max_shortage_gw:.1f} GW",
        transform=ax_balance.transAxes,
        ha="right",
        va="bottom",
        fontsize=9.2,
        color="#7A1F1F",
        bbox={
            "facecolor": "white",
            "edgecolor": "#C94C4C",
            "alpha": 0.90,
            "boxstyle": "round,pad=0.40",
        },
    )

    fig.text(
        0.075,
        0.032,
        "Modell: optimistisches Markthochlauf-Szenario; Profile 2024 auf 2030 skaliert. Die Preislinie ist keine Marktpreisprognose.",
        fontsize=8.1,
        color="#4A4A4A",
    )
    fig.text(
        0.075,
        0.014,
        "Quellen: SMARD, EEG-Mittelfristprognose 2030, BNetzA-Monitoring 2025 · Methodik: Begleittext",
        ha="left",
        fontsize=8.1,
        color="#4A4A4A",
    )
    fig.text(
        0.925,
        0.014,
        f"© {AUTHOR_NAME} {COPYRIGHT_YEAR} · {LICENSE_LABEL}",
        ha="right",
        fontsize=8.1,
        color="#4A4A4A",
    )
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.10, top=0.88, hspace=0.34)
    fig.savefig(output_dir / "01_klimaleistung_preis_und_residuallast_2030.png", dpi=240)
    fig.savefig(output_dir / "01_klimaleistung_preis_und_residuallast_2030.svg")
    plt.close(fig)

    # Separate, kompakte Dauerlinie für die physische Passung.
    fig, ax = plt.subplots(figsize=(12.5, 6.8))
    ax.plot(hours, sorted_supply, linewidth=1.35, color="#75B9E6", label="erneuerbares Angebot")
    ax.plot(hours, sorted_demand, linewidth=1.35, color="#3D434A", label="strenge 24/7-Nachfrage")
    ax.fill_between(hours, sorted_supply, sorted_demand, where=sorted_supply >= sorted_demand, color="#5A9E55", alpha=0.18, label="Überschuss")
    ax.fill_between(hours, sorted_supply, sorted_demand, where=sorted_supply < sorted_demand, color="#C94C4C", alpha=0.28, label="Unterdeckung")
    ax.set_xlim(1, len(price_eur_t))
    ax.set_xlabel("Jahresstunden, nach Angebot − Nachfrage aufsteigend sortiert")
    ax.set_ylabel("Leistung [GW]")
    ax.set_title("Klimaleistung 2030: stündliche Passung von Angebot und strenger Nachfrage")
    ax.grid(True, axis="y", alpha=0.22)
    ax.legend(loc="upper left", ncol=2, frameon=False)
    fig.tight_layout()
    fig.savefig(output_dir / "02_klimaleistung_angebots_nachfrage_dauerlinie_2030.png", dpi=240)
    fig.savefig(output_dir / "02_klimaleistung_angebots_nachfrage_dauerlinie_2030.svg")
    plt.close(fig)

    # Kalender-Heatmap: zeigt, wann statt nur wie oft Knappheit auftritt.
    matrix = net_balance_mwh.reshape(365, 24).T / 1_000.0
    low_scale = min(float(np.nanpercentile(matrix, 1)), -1.0)
    high_scale = max(float(np.nanpercentile(matrix, 98)), 1.0)
    fig, ax = plt.subplots(figsize=(13.2, 5.2))
    image = ax.imshow(
        matrix, aspect="auto", origin="lower", interpolation="nearest",
        cmap="RdYlGn", norm=TwoSlopeNorm(vmin=low_scale, vcenter=0.0, vmax=high_scale),
    )
    month_starts = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    month_labels = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
    ax.set_xticks(month_starts)
    ax.set_xticklabels(month_labels)
    ax.set_yticks([0, 4, 8, 12, 16, 20, 23])
    ax.set_ylabel("Stunde des Tages")
    ax.set_xlabel("Kalendertag 2030")
    ax.set_title("Klimaleistung 2030: Kalender der stündlichen Angebotsdifferenz")
    cbar = fig.colorbar(image, ax=ax, pad=0.015)
    positive_ticks = [value for value in (0, 20, 40, 60, 80, 100) if value <= high_scale + 1e-9]
    cbar.set_ticks([low_scale, *positive_ticks])
    cbar.set_ticklabels([f"{low_scale:.1f}", *[f"{value:g}" for value in positive_ticks]])
    cbar.set_label("Erneuerbares Angebot − strenge Nachfrage [GW]")
    fig.tight_layout()
    fig.savefig(output_dir / "03_klimaleistung_residuallast_heatmap_2030.png", dpi=240)
    fig.savefig(output_dir / "03_klimaleistung_residuallast_heatmap_2030.svg")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    inputs = load_hourly_inputs(args.smard_db, args.weather_db, args.weather_year, args.weather_site)
    supply = build_supply(inputs)
    strict_demand = build_strict_demand(inputs)
    district_heat = build_district_heat_hp(inputs)
    fossil_intensity = build_fossil_intensity(inputs)

    total_supply = np.sum(np.vstack(list(supply.values())), axis=0)
    demand_without_heat = np.sum(np.vstack(list(strict_demand.values())), axis=0)
    hp_electricity = np.asarray(district_heat["hp_electricity_mwh"], dtype=float)
    total_demand = demand_without_heat + hp_electricity
    net_balance = total_supply - total_demand

    # Sensitivität gegen mögliche Doppelzählung: 25 % der separat ausgewiesenen
    # Rechenzentrums-, öffentlichen und DB-Nachfrage werden als bereits im
    # allgemeinen Ökostrom-Umstiegspool enthalten behandelt.
    overlap_adjusted_without_heat = demand_without_heat.copy()
    for key in ("data_centres", "public_sector", "db_traction"):
        overlap_adjusted_without_heat -= strict_demand[key] * OVERLAP_SENSITIVITY_SHARE
    overlap_adjusted_total_demand = overlap_adjusted_without_heat + hp_electricity

    tranches = offer_tranches()
    tranche_profiles = build_tranche_profiles(supply, tranches)
    clearing = clear_market(total_demand, tranche_profiles, args.scarcity_premium_eur_mwh)
    overlap_clearing = clear_market(overlap_adjusted_total_demand, tranche_profiles, args.scarcity_premium_eur_mwh)
    price_eur_mwh = clearing["price_eur_mwh"]
    price_eur_t = price_eur_mwh / fossil_intensity
    climate_floor_eur_mwh = args.climate_floor_eur_t * fossil_intensity
    top_up_all = np.maximum(climate_floor_eur_mwh - price_eur_mwh, 0.0) * clearing["accepted_mwh"]

    pilot_results = [
        guarantee_for_pilot(
            pilot_twh,
            total_supply,
            total_demand,
            price_eur_mwh,
            climate_floor_eur_mwh,
        )
        for pilot_twh in DEFAULT_PILOT_TWH
    ]

    variant_results = {
        "Sockellast, iterativ": simulate_variant(
            demand_without_heat,
            hp_electricity,
            tranche_profiles,
            total_supply,
            fossil_intensity,
            args.climate_floor_eur_t,
            args.scarcity_premium_eur_mwh,
        ),
        "30 % jeder Wärmelaststunde": simulate_variant(
            demand_without_heat,
            np.asarray(district_heat["proportional_hp_electricity_mwh"], dtype=float),
            tranche_profiles,
            total_supply,
            fossil_intensity,
            args.climate_floor_eur_t,
            args.scarcity_premium_eur_mwh,
        ),
        "konstante thermische Leistung": simulate_variant(
            demand_without_heat,
            np.asarray(district_heat["flat_hp_electricity_mwh"], dtype=float),
            tranche_profiles,
            total_supply,
            fossil_intensity,
            args.climate_floor_eur_t,
            args.scarcity_premium_eur_mwh,
        ),
    }

    create_plots(
        args.output_dir,
        price_eur_t,
        price_eur_mwh,
        net_balance,
        total_supply,
        total_demand,
        args.climate_floor_eur_t,
        args.scarcity_premium_eur_mwh,
    )

    offer_csv = args.output_dir / "klimaleistung_angebotsstufen_2030.csv"
    write_semicolon_csv(
        offer_csv,
        ["energietraeger", "veraeusserungsform", "jahresmenge_gwh", "mindestpraemie_eur_mwh"],
        (
            (t.technology, t.label, f"{t.annual_gwh:.3f}", f"{t.offer_eur_mwh:.6f}")
            for t in sorted(tranches, key=lambda item: item.offer_eur_mwh)
        ),
    )

    demand_csv = args.output_dir / "klimaleistung_nachfrageannahmen_2030.csv"
    write_semicolon_csv(
        demand_csv,
        ["kategorie", "jahresmenge_twh", "herleitung", "szenariocharakter"],
        (
            (
                DEMAND_LABELS[key],
                f"{STRICT_DEMAND_TWH[key]:.6f}",
                DEMAND_DERIVATIONS[key],
                "optimistische Annahme / hohes Markthochlauf-Szenario",
            )
            for key in STRICT_DEMAND_TWH
        ),
    )

    pilot_csv = args.output_dir / "klimaleistung_pilotgarantie_2030.csv"
    write_semicolon_csv(
        pilot_csv,
        [
            "pilot_twh",
            "privat_absorbiert_twh",
            "staatlicher_ankauf_twh",
            "stunden_staatlicher_ankauf",
            "aufstockung_mrd_eur",
            "ankauf_mrd_eur",
            "garantie_gesamt_mrd_eur",
        ],
        (
            (
                f"{r['pilot_twh']:.3f}",
                f"{r['private_twh']:.6f}",
                f"{r['state_purchase_twh']:.6f}",
                r["state_purchase_hours"],
                f"{r['top_up_billion_eur']:.6f}",
                f"{r['last_resort_billion_eur']:.6f}",
                f"{r['total_guarantee_billion_eur']:.6f}",
            )
            for r in pilot_results
        ),
    )

    hourly_csv = args.output_dir / "klimaleistung_marktmodell_2030_stunden.csv"
    hourly_header = [
        "timestamp_modell_2030",
        "timestamp_wetter_utc_2024",
        "timestamp_wetter_berlin_2024",
        "temp_c",
        "cop_fw_90c",
        *[f"angebot_{key}_mwh" for key in supply],
        "angebot_gesamt_mwh",
        *[f"nachfrage_{key}_mwh" for key in strict_demand],
        "nachfrage_fernwaerme_wp_mwh",
        "nachfrage_gesamt_mwh",
        "differenz_angebot_minus_nachfrage_mwh",
        "unterdeckung_mwh",
        "fossiler_restmix_t_co2e_mwh",
        "mindest_clearingpraemie_eur_mwh",
        "mindest_clearingpreis_eur_t_co2e",
        "garantiewert_eur_mwh",
        "preis_aus_angebot_bestimmbar",
        "marginales_angebot",
    ]

    def hourly_rows() -> Iterable[list[object]]:
        for index in range(len(inputs.rows)):
            yield [
                inputs.model_local_dt[index].isoformat(sep=" "),
                inputs.timestamp_utc[index],
                inputs.timestamp_berlin[index],
                f"{inputs.temp_c[index]:.3f}",
                f"{np.asarray(district_heat['cop'])[index]:.6f}",
                *[f"{supply[key][index]:.6f}" for key in supply],
                f"{total_supply[index]:.6f}",
                *[f"{strict_demand[key][index]:.6f}" for key in strict_demand],
                f"{hp_electricity[index]:.6f}",
                f"{total_demand[index]:.6f}",
                f"{net_balance[index]:.6f}",
                f"{clearing['shortage_mwh'][index]:.6f}",
                f"{fossil_intensity[index]:.9f}",
                f"{price_eur_mwh[index]:.6f}",
                f"{price_eur_t[index]:.6f}",
                f"{climate_floor_eur_mwh[index]:.6f}",
                "ja" if clearing["shortage_mwh"][index] <= 1e-9 else "nein",
                clearing["marginal_offer"][index],
            ]

    write_semicolon_csv(hourly_csv, hourly_header, hourly_rows())

    shortage_mask = clearing["shortage_mwh"] > 1e-9
    known_price_mask = ~shortage_mask
    shortage_hours = int(np.count_nonzero(shortage_mask))
    floor_hours = int(np.count_nonzero((price_eur_t < args.climate_floor_eur_t) & known_price_mask))
    high_price_hours = int(np.count_nonzero((price_eur_t >= args.climate_floor_eur_t) & known_price_mask))
    unknown_price_hours = shortage_hours
    marginal_counts = Counter(str(value) for value in clearing["marginal_offer"])

    known_prices_t = price_eur_t[known_price_mask]
    quantiles = np.quantile(known_prices_t, [0.0, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99, 1.0])
    known_weights = clearing["accepted_mwh"][known_price_mask]
    weighted_price_mwh = float(np.sum(price_eur_mwh[known_price_mask] * known_weights) / np.sum(known_weights))
    weighted_price_t = float(np.sum(price_eur_t[known_price_mask] * known_weights) / np.sum(known_weights))

    overlap_shortage_hours = int(np.count_nonzero(overlap_clearing["shortage_mwh"] > 1e-9))
    overlap_shortage_twh = float(overlap_clearing["shortage_mwh"].sum() / 1e6)
    overlap_demand_twh = float(overlap_adjusted_total_demand.sum() / 1e6)
    gross_demand_twh = float(total_demand.sum() / 1e6)

    result_file = args.output_dir / "klimaleistung_marktmodell_2030.res"
    with result_file.open("w", encoding="utf-8") as file:
        file.write("STÜNDLICHES KLIMALEISTUNGS-MARKTMODELL 2030\n")
        file.write("=" * 72 + "\n")
        file.write(f"Modellversion: {MODEL_VERSION}\n")
        file.write(f"Modellkalender: {MODEL_YEAR} (8.760 Stunden)\n")
        file.write(f"Wetter-/Profiljahr: {args.weather_year}; 29. Februar entfernt und Profile neu normiert\n")
        file.write(f"Wetterstandort: {args.weather_site}\n\n")

        file.write("KERNAUSSAGE\n")
        file.write("-" * 72 + "\n")
        file.write(
            "Das Modell ist ein transparent optimistisches Markthochlauf-Szenario. "
            "Es prüft nicht, ob die Jahresmenge erneuerbarer Erzeugung ausreicht, sondern "
            "ob Angebot und streng nachgewiesene Nachfrage in jeder Stunde zusammenpassen. "
            "Knappheitsstunden erzeugen einen Wert für zeitlich passende Klimaleistung; "
            "Überschussstunden können eine staatliche Preisuntergrenze erfordern.\n\n"
        )

        file.write("OPTIMISTISCHE NACHFRAGEANNAHMEN 2030\n")
        file.write("-" * 72 + "\n")
        for key, annual_twh in STRICT_DEMAND_TWH.items():
            file.write(f"{DEMAND_LABELS[key]}: {fmt_de(annual_twh,3)} TWh – {DEMAND_DERIVATIONS[key]}\n")
        file.write(f"Summe ohne Fernwärme-Wärmepumpen: {fmt_de(demand_without_heat.sum()/1e6,3)} TWh\n")
        file.write(
            "Die 25-%-Annahme bezieht sich auf die 2024 von der Bundesnetzagentur "
            "ausgewiesene Ökostrommenge, nicht auf die Zahl der Verträge. Die Statistik "
            "trennt öffentliche, DB- und private Großkunden nicht. Das Hauptszenario zieht "
            "daher keine Überschneidungen ab und ist bewusst hoch.\n"
        )
        file.write(
            f"Überschneidungssensitivität: 25 % der separat erfassten Rechenzentrums-, "
            f"öffentlichen und DB-Last werden als bereits im Ökostrom-Umstiegspool enthalten "
            f"behandelt. Nachfrage inkl. Fernwärme dann {fmt_de(overlap_demand_twh,3)} TWh.\n\n"
        )

        file.write("MENGEN 2030\n")
        file.write("-" * 72 + "\n")
        file.write(f"Marktverfügbare erneuerbare Erzeugung: {fmt_de(total_supply.sum()/1e6)} TWh\n")
        file.write(f"Strenge 24/7-Nachfrage ohne Fernwärme: {fmt_de(demand_without_heat.sum()/1e6)} TWh\n")
        file.write(f"Fernwärme-Nettowärmeerzeugung: {fmt_de(DISTRICT_HEAT_NET_GENERATION_TWH,1)} TWh_th\n")
        file.write(f"Davon Wärmepumpen-Szenario: {fmt_de(DISTRICT_HEAT_HP_SHARE*100,0)} % = {fmt_de(np.asarray(district_heat['hp_heat_mwh']).sum()/1e6)} TWh_th\n")
        file.write(f"Wärmepumpenstrom Sockellast: {fmt_de(hp_electricity.sum()/1e6)} TWh_el\n")
        file.write(f"Gewichteter COP: {fmt_de(np.asarray(district_heat['hp_heat_mwh']).sum()/hp_electricity.sum(),3)}\n")
        file.write(f"Ermittelte thermische WP-Leistung: {fmt_de(float(district_heat['thermal_capacity_mw'])/1000,3)} GW_th\n")
        file.write(f"Elektrische WP-Spitze: {fmt_de(hp_electricity.max()/1000,3)} GW_el\n")
        file.write(f"Gesamte strenge Nachfrage inkl. Fernwärme: {fmt_de(gross_demand_twh)} TWh\n\n")

        file.write("STÜNDLICHE PASSUNG\n")
        file.write("-" * 72 + "\n")
        file.write(f"Stunden mit vollständiger erneuerbarer Deckung: {len(inputs.rows)-shortage_hours} von {len(inputs.rows)} ({fmt_de((len(inputs.rows)-shortage_hours)/len(inputs.rows)*100,2)} %)\n")
        file.write(f"Stunden mit Unterdeckung: {shortage_hours}\n")
        file.write(f"Unterdeckte Jahresmenge: {fmt_de(clearing['shortage_mwh'].sum()/1e6,3)} TWh\n")
        file.write(f"Maximale stündliche Unterdeckung: {fmt_de(clearing['shortage_mwh'].max()/1000,3)} GW\n")
        file.write(f"Rechnerischer Jahresüberschuss: {fmt_de(np.maximum(net_balance,0).sum()/1e6)} TWh\n")
        file.write(f"Überschneidungssensitivität: {overlap_shortage_hours} Unterdeckungsstunden / {fmt_de(overlap_shortage_twh,3)} TWh Unterdeckung.\n\n")

        file.write("PREISMODELL\n")
        file.write("-" * 72 + "\n")
        file.write(
            "Jede 2030-Veräußerungsform bietet stündlich ihre verfügbare Menge zu der "
            "Prämie an, die ihre prognostizierte EEG-Förderlücke ersetzt. Das letzte zur "
            "Deckung benötigte Angebot setzt die anbieterseitige Preisuntergrenze.\n"
        )
        file.write(
            f"In {unknown_price_hours} Unterdeckungsstunden ist der Preis aus den vorhandenen "
            f"Angeboten nicht bestimmbar. Der Szenariowert von {fmt_de(args.scarcity_premium_eur_mwh,0)} €/MWh "
            "wird nur für die Garantiekosten-Sensitivität verwendet und nicht als Marktpreis dargestellt.\n"
        )
        file.write(f"Mengengewichtete anbieterseitige Preisuntergrenze in bestimmbaren Stunden: {fmt_de(weighted_price_mwh,2)} €/MWh bzw. {fmt_de(weighted_price_t,2)} €/t CO2e\n")
        file.write(f"Bestimmbare Stunden unter {fmt_de(args.climate_floor_eur_t,0)} €/t: {floor_hours}\n")
        file.write(f"Bestimmbare Stunden mindestens {fmt_de(args.climate_floor_eur_t,0)} €/t: {high_price_hours}\n")
        file.write(f"Preis nicht bestimmbar: {unknown_price_hours} Stunden\n")
        file.write(f"Garantie-Aufstockung auf alle privat gedeckten Mengen im Szenario: {fmt_de(top_up_all.sum()/1e9,3)} Mrd. €/a\n")
        file.write("Preisquantile der bestimmbaren Stunden [€/t CO2e]:\n")
        for label, value in zip(("Minimum", "P25", "Median", "P75", "P90", "P95", "P99", "Maximum"), quantiles):
            file.write(f"  {label:8s}: {fmt_de(float(value),2)}\n")
        file.write("\n")

        file.write(f"MENGENBEGRENZTE GARANTIE BEI {fmt_de(args.climate_floor_eur_t,0)} €/t\n")
        file.write("-" * 72 + "\n")
        file.write("Pilot | privat | staatlich gekauft | Ankaufstunden | Aufstockung | Ankauf | Gesamt\n")
        for result in pilot_results:
            file.write(
                f"{result['pilot_twh']:5.0f} TWh | "
                f"{fmt_de(result['private_twh'],3):>8s} | "
                f"{fmt_de(result['state_purchase_twh'],3):>8s} | "
                f"{result['state_purchase_hours']:5d} | "
                f"{fmt_de(result['top_up_billion_eur'],3):>7s} | "
                f"{fmt_de(result['last_resort_billion_eur'],3):>6s} | "
                f"{fmt_de(result['total_guarantee_billion_eur'],3):>7s} Mrd. €\n"
            )
        file.write("\n")

        file.write("WÄRMEPROFIL-SENSITIVITÄT\n")
        file.write("-" * 72 + "\n")
        for name, result in variant_results.items():
            file.write(
                f"{name}: WP-Strom {fmt_de(result['hp_electricity_twh'],3)} TWh; "
                f"Spitze {fmt_de(result['hp_peak_gw'],3)} GW; "
                f"Unterdeckung {result['shortage_hours']} h / {fmt_de(result['shortage_twh'],3)} TWh; "
                f"Garantie-Aufstockung {fmt_de(result['all_matched_top_up_billion_eur'],3)} Mrd. €.\n"
            )
        file.write("\n")

        file.write("HÄUFIGSTE MARGINALE ANGEBOTE\n")
        file.write("-" * 72 + "\n")
        for label, count in marginal_counts.most_common(12):
            file.write(f"{count:5d} h  {label}\n")
        file.write("\n")

        file.write("METHODIK UND GRENZEN\n")
        file.write("-" * 72 + "\n")
        file.write("1. Optimistisches Ober-Szenario, keine neutrale Nachfrageprognose.\n")
        file.write("2. 25 % der Ökostrommenge 2024 wechseln annahmegemäß bis 2030 auf stündlichen Nachweis.\n")
        file.write("3. Überschneidungen zwischen Ökostromstatistik, öffentlicher Hand, DB und Rechenzentren sind nicht auflösbar; eine Sensitivität wird separat ausgewiesen.\n")
        file.write("4. Das Modell nutzt 2024 als einzelnes Wetter- und Einspeisejahr; der 29. Februar wird entfernt und alle Profile werden auf 2030-Mengen neu normiert.\n")
        file.write("5. Kassel ist ein Temperaturproxy für Deutschland; ein regional gewichtetes Temperaturmodell fehlt.\n")
        file.write("6. Die 30 % Fernwärme werden vollständig Großwärmepumpen zugerechnet. Das ist ein elektrisches Obergrenzenszenario.\n")
        file.write("7. Wärmespeicher und vollständige Strompreisoptimierung der Wärmepumpen fehlen.\n")
        file.write("8. Die €/t-Umrechnung nutzt den stündlichen fossilen Restmix 2024 einschließlich Vorkettenaufschlägen; ein 2030-Restmix fehlt.\n")
        file.write("9. Reale Käufergebote, Speicher-, Import- und Firming-Angebote fehlen.\n")
        file.write("10. Die Preislinie ist eine Angebotsuntergrenze; Knappheitsstunden haben ohne zusätzliches Angebot keinen bestimmbaren Preis.\n\n")

        file.write("QUELLEN\n")
        file.write("-" * 72 + "\n")
        file.write("Bundesnetzagentur/Bundeskartellamt, Monitoringbericht Energie 2025: 74,0 TWh Ökostrom Haushalte und 62,5 TWh weitere Letztverbraucher im Jahr 2024.\n")
        file.write("https://data.bundesnetzagentur.de/Bundesnetzagentur/SharedDocs/Mediathek/Monitoringberichte/MonitoringberichtEnergie2025.pdf\n")
        file.write("Deutsche Bahn, Integrierter Bericht 2024: 7.172 GWh Traktionsstrom und 69,8 % erneuerbarer Bahnstrommix; DB-Ziel 80 % bis 2030.\n")
        file.write("https://ibir.deutschebahn.com/2024/de/zusammengefasster-lagebericht/entwicklung-der-geschaeftsfelder/geschaeftsfeld-db-energie/entwicklung-im-berichtsjahr/\n")
        file.write("BMWE, Stand und Entwicklung des Rechenzentrumsstandorts Deutschland: 31 TWh Strombedarf 2030.\n")
        file.write("https://www.bundeswirtschaftsministerium.de/Redaktion/DE/Publikationen/Technologie/stand-und-entwicklung-des-rechenzentrumsstandorts-deutschland.pdf?__blob=publicationFile&v=1\n")
        file.write("EU 2023/1184: stündliche zeitliche Korrelation für RFNBO ab 2030.\n")
        file.write("https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32023R1184\n")
        file.write("EEG-Mittelfristprognose 2026-2030, IE Leipzig/r2b/ÜNB.\n")
        file.write("https://www.netztransparenz.de/xspproxy/api/staticfiles/ntp-relaunch/dokumente/erneuerbare%20energien%20und%20umlagen/eeg/eeg%20finanzierung/mittelfristprognose/2026-2030/20251015_endbericht%20ie%20leipzig.pdf\n")
        file.write("Wärmeplanungsgesetz §29: https://www.gesetze-im-internet.de/wpg/__29.html\n")
        file.write("UBA, Potenzial effiziente Wärme- und Kälteversorgung.\n")
        file.write("https://www.umweltbundesamt.de/system/files/medien/1410/publikationen/2021-08-05_cc_54-2021_effiziente_waerme-kaelteversorgung.pdf\n")
        file.write("Agora/Fraunhofer IEG, Roll-out von Großwärmepumpen.\n")
        file.write("https://www.agora-energiewende.de/fileadmin/Projekte/2022/2022-11_DE_Large_Scale_Heatpumps/A-EW_293_Rollout_Grosswaermepumpen_WEB.pdf\n")
        file.write("SMARD-Stundendaten und lokale Wetterdaten: übergebene SQLite-Datenbanken.\n")

    explanation_file = args.output_dir / "01_ERKLAERTEXT_KLIMALEISTUNG_MARKTMODELL_2030.md"
    with explanation_file.open("w", encoding="utf-8") as file:
        file.write("# Stündlicher Wert THG-freien Stroms 2030\n\n")
        file.write("## Aussage der Grafik\n\n")
        file.write(
            "Die Grafik ist **keine Marktpreisprognose**. Sie zeigt einen ersten, transparenten Modelllauf dafür, "
            "warum nachweislich THG-freier Strom trotz ausreichender Jahreserzeugung einen stündlich unterschiedlichen "
            "Wert besitzt.\n\n"
        )
        file.write(
            "**Feld A** sortiert die 8.760 Jahresstunden nach der anbieterseitigen Preisuntergrenze. Diese wird aus "
            "den für 2030 prognostizierten EEG-Förderlücken der jeweils zuletzt benötigten Angebotsstufe abgeleitet "
            "und anschließend mit dem stündlichen fossilen Restmix in Euro je Tonne CO₂e umgerechnet. Die gelbe Linie "
            f"markiert beispielhaft einen staatlichen Mindestpreis von **{args.climate_floor_eur_t:g} €/t CO₂e**. "
            "Der gelbe Bereich darunter ist ein möglicher Aufstockungsbereich, nicht bereits eine berechnete "
            "Haushaltsausgabe.\n\n"
        )
        file.write(
            "In den schraffierten Knappheitsstunden reicht das modellierte THG-freie Angebot nicht aus. Dort kann "
            "aus den vorhandenen Angeboten kein Preis bestimmt werden; dafür wären Speicher, gesicherte THG-freie "
            "Erzeugung, Importe oder Lastverschiebung nötig.\n\n"
        )
        file.write(
            "**Feld B** sortiert dieselben Stunden separat nach `THG-freies Angebot − strenge 24/7-Nachfrage`. "
            "Positive Werte zeigen Überschuss, negative Werte Unterdeckung. Weil beide Felder unterschiedlich "
            "sortiert sind, dürfen ihre Punkte nicht horizontal miteinander verbunden werden.\n\n"
        )

        file.write("## Optimistische Nachfrageannahme 2030\n\n")
        file.write(
            "Das Szenario ist bewusst optimistisch. Es soll prüfen, ob auch bei einem starken Markthochlauf noch "
            "stündliche Knappheit und damit ein eigenständiger Wert der Klimaleistung bestehen.\n\n"
        )
        file.write("| Nachfragegruppe | 2030 [TWh] | Annahme |\n|---|---:|---|\n")
        for key, annual_twh in STRICT_DEMAND_TWH.items():
            file.write(f"| {DEMAND_LABELS[key]} | {fmt_de(annual_twh,3)} | {DEMAND_DERIVATIONS[key]} |\n")
        file.write(f"| **Summe ohne Fernwärme** | **{fmt_de(demand_without_heat.sum()/1e6,3)}** | |\n")
        file.write(
            f"| Fernwärme-Großwärmepumpen | {fmt_de(hp_electricity.sum()/1e6,3)} | "
            "30 % von 156 TWh Fernwärmeerzeugung; temperaturabhängiger COP bei 90 °C Vorlauf |\n"
        )
        file.write(f"| **Gesamte strenge Nachfrage** | **{fmt_de(gross_demand_twh,3)}** | optimistisches Markthochlauf-Szenario |\n\n")
        file.write(
            "Die Annahme von **25 % Ökostromkunden** wird als 25 % der 2024 gelieferten Ökostrommenge modelliert: "
            "18,5 TWh Haushalte und 15,625 TWh weitere Letztverbraucher. Unterstellt wird, dass der zusätzliche "
            "Aufpreis für einen stündlichen Nachweis moderat genug ist, um diesen hohen Umstieg bis 2030 zu tragen. "
            "Das ist eine transparente Annahme, keine beobachtete Prognose.\n\n"
        )
        file.write(
            "Die Ökostromstatistik trennt die weiteren Letztverbraucher nicht nach privaten Unternehmen, öffentlicher "
            "Hand, DB oder Rechenzentren. Das Bruttoszenario kann deshalb Doppelzählungen enthalten. In einer ersten "
            "Überschneidungssensitivität werden 25 % der separat erfassten Rechenzentrums-, öffentlichen und DB-Last "
            f"abgezogen. Die Nachfrage sinkt dann auf **{fmt_de(overlap_demand_twh,3)} TWh**, die Unterdeckung auf "
            f"**{overlap_shortage_hours} Stunden beziehungsweise {fmt_de(overlap_shortage_twh,3)} TWh**.\n\n"
        )

        file.write("## Ergebnis des Modelllaufs\n\n")
        file.write(f"- THG-freies Angebot: **{fmt_de(total_supply.sum()/1e6,2)} TWh**.\n")
        file.write(f"- Strenge 24/7-Nachfrage: **{fmt_de(gross_demand_twh,2)} TWh**.\n")
        file.write(f"- Unterdeckung: **{shortage_hours} Stunden beziehungsweise {fmt_de(clearing['shortage_mwh'].sum()/1e6,3)} TWh**.\n")
        file.write(f"- Maximale stündliche Unterdeckung: **{fmt_de(clearing['shortage_mwh'].max()/1000,3)} GW**.\n")
        file.write(f"- Stunden mit bestimmbarer Preisuntergrenze unter {args.climate_floor_eur_t:g} €/t: **{floor_hours}**.\n")
        file.write(f"- Stunden mit bestimmbarer Preisuntergrenze mindestens auf Mindestpreishöhe: **{high_price_hours}**.\n\n")

        file.write("## Methodische Grenzen\n\n")
        file.write(
            "Die Preislinie bildet nur die **Angebotsseite** ab. Ein tatsächlicher Marktpreis benötigt reale "
            "Käufergebote. Die Erzeugungsprofile stammen aus dem Wetter- und Einspeisejahr 2024, der 29. Februar "
            "wurde entfernt und die Profile wurden auf die für 2030 angenommenen Jahresmengen skaliert. Die "
            "Umrechnung in Euro je Tonne nutzt den stündlichen fossilen Restmix 2024 einschließlich der im "
            "Klimaleistungsmodell dokumentierten Vorkettenaufschläge. Ein eigener fossiler Restmix 2030, mehrere "
            "Wetterjahre, Speicher, Importe und reale Lastflexibilität sind noch nicht enthalten.\n\n"
        )

        file.write("## Quellen\n\n")
        file.write(
            "- **EEG-Mittelfristprognose 2026–2030, Trendszenario**: Erzeugungsmengen, Veräußerungsformen, "
            "Basepreis und Marktwertfaktoren 2030. IE Leipzig, r2b und Übertragungsnetzbetreiber.  "
            "https://www.netztransparenz.de/xspproxy/api/staticfiles/ntp-relaunch/dokumente/erneuerbare%20energien%20und%20umlagen/eeg/eeg%20finanzierung/mittelfristprognose/2026-2030/20251015_endbericht%20ie%20leipzig.pdf\n"
        )
        file.write(
            "- **SMARD-Stundendaten 2024**: relative Einspeiseprofile und fossiler Restmix; lokale SQLite-Datenbank "
            "des Projekts. Datenquelle: Bundesnetzagentur/SMARD. https://www.smard.de/\n"
        )
        file.write(
            "- **Monitoringbericht Energie 2025**: 74,0 TWh Ökostrom an Haushalte und 62,5 TWh an weitere "
            "Letztverbraucher im Jahr 2024. Bundesnetzagentur und Bundeskartellamt.  "
            "https://data.bundesnetzagentur.de/Bundesnetzagentur/SharedDocs/Mediathek/Monitoringberichte/MonitoringberichtEnergie2025.pdf\n"
        )
        file.write(
            "- **Deutsche Bahn, Integrierter Bericht 2024**: 7.172 GWh Traktionsstrom; Ziel von 80 % erneuerbarem "
            "Bahnstrom bis 2030.  "
            "https://ibir.deutschebahn.com/2024/de/zusammengefasster-lagebericht/entwicklung-der-geschaeftsfelder/geschaeftsfeld-db-energie/entwicklung-im-berichtsjahr/\n"
        )
        file.write(
            "- **Rechenzentren in Deutschland**: prognostizierter Strombedarf von 31 TWh im Jahr 2030. "
            "Bundeswirtschaftsministerium.  "
            "https://www.bundeswirtschaftsministerium.de/Redaktion/DE/Publikationen/Technologie/stand-und-entwicklung-des-rechenzentrumsstandorts-deutschland.pdf?__blob=publicationFile&v=1\n"
        )
        file.write(
            "- **Delegierte Verordnung (EU) 2023/1184**: zeitliche Korrelation für RFNBO-Strom ab 2030.  "
            "https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32023R1184\n"
        )
        file.write(
            "- **Fernwärme und Großwärmepumpen**: UBA-Potenzialanalyse, Wärmeplanungsgesetz § 29 sowie "
            "Agora Energiewende/Fraunhofer IEG zur Auslegung großer Wärmepumpen.  "
            "https://www.umweltbundesamt.de/system/files/medien/1410/publikationen/2021-08-05_cc_54-2021_effiziente_waerme-kaelteversorgung.pdf  \n"
            "https://www.gesetze-im-internet.de/wpg/__29.html  \n"
            "https://www.agora-energiewende.de/fileadmin/Projekte/2022/2022-11_DE_Large_Scale_Heatpumps/A-EW_293_Rollout_Grosswaermepumpen_WEB.pdf\n\n"
        )

        file.write("## Urheberrecht und Lizenz\n\n")
        file.write(
            f"Grafik © {AUTHOR_NAME} {COPYRIGHT_YEAR}. Freigegeben unter **{LICENSE_LABEL}**: freie Weitergabe und "
            "Bearbeitung, auch kommerziell, bei angemessener Namensnennung, Link auf die Lizenz und Kennzeichnung "
            f"von Änderungen. Lizenz: {LICENSE_URL}\n"
        )

    # Technische Prüfungen
    checks = {
        "supply_sum": math.isclose(float(total_supply.sum()), sum(ANNUAL_MARKETABLE_GWH.values()) * 1_000.0, abs_tol=2_000.0),
        "strict_demand_sum": math.isclose(float(demand_without_heat.sum()), sum(STRICT_DEMAND_TWH.values()) * 1e6, abs_tol=1.0),
        "hp_heat_target": abs(float(district_heat["target_error_mwh"])) <= 1.0,
        "finite_prices": bool(np.all(np.isfinite(price_eur_t))),
        "nonnegative": bool(np.all(total_supply >= 0) and np.all(total_demand >= 0) and np.all(price_eur_mwh >= 0)),
    }
    failed = [name for name, valid in checks.items() if not valid]
    if failed:
        raise AssertionError(f"Validierungsfehler: {', '.join(failed)}")

    print("Klimaleistungs-Marktmodell erfolgreich erstellt")
    print(f"Angebot: {total_supply.sum()/1e6:.3f} TWh")
    print(f"Nachfrage inkl. Fernwärme-WP: {total_demand.sum()/1e6:.3f} TWh")
    print(f"WP-Strom: {hp_electricity.sum()/1e6:.3f} TWh; gewichteter COP: {np.asarray(district_heat['hp_heat_mwh']).sum()/hp_electricity.sum():.3f}")
    print(f"Unterdeckung: {shortage_hours} h / {clearing['shortage_mwh'].sum()/1e6:.3f} TWh")
    print(f"Preis unter {args.climate_floor_eur_t:g} €/t: {floor_hours} h")
    print(f"Ausgabe: {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        raise
