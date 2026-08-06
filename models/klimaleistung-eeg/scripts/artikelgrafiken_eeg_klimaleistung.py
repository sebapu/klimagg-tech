#!/usr/bin/env python3
# Copyright (c) 2026 Sebastian Putzke
# SPDX-License-Identifier: Apache-2.0
"""Artikelgrafiken zu EEG-Förderung und Klimaleistung.

Das Skript verbindet drei bereits getrennt geprüfte Datenquellen:

* SMARD-Stundendaten: Einspeiseprofile, Day-ahead-Preis und fossiler Restmix,
* Wetter-/Szenariendatenbank: literaturnormierte PV- und Windprofile,
* Netztransparenz-EEG-Datenbank: Vollvergütung und Marktprämie 2024.

Erzeugt werden genau zwei Hauptgrafiken:

1. rechnerisch verdrängte fossile THG in t CO2e/(MW*a) je Referenz-/Anlagenfall,
2. Gesamterlös in Tsd. EUR/(MW*a): EEG-Vollvergütung, Markt + Prämie und
   Markt + Klimaleistung in drei Blöcken zu je 50 EUR/t CO2e.

PV wird auf MWp DC bezogen, alle übrigen Technologien auf MW Nennleistung.
Das Skript modelliert keine Batterie und legt keinen Download-Cache an.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - verständliche CLI-Meldung
    raise SystemExit("Abhängigkeit fehlt: python -m pip install numpy matplotlib") from exc


SCRIPT_DIR = Path(__file__).resolve().parent
VERSION = "7.3.0"
CLIMATE_PRICE_STEPS = (50.0, 100.0, 150.0)
AUTHOR_NAME = "Sebastian Putzke"
LICENSE_LABEL = "CC BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
COPYRIGHT_YEAR = datetime.now().year

# Die vierte PV-Variante bleibt in Datenbank, CSV und Methodik erhalten, wird
# aber nicht geplottet: Ost-West 30° liefert gegenüber Ost-West 15° keinen
# zusätzlichen qualitativen Vergleich, erhöht jedoch die grafische Dichte.
PLOT_CASE_IDS = {
    "pv_reference",
    "pv_sued_30",
    "pv_sued_60",
    "pv_ost_west_15",
    "wind_onshore_reference",
    "wind_standard",
    "wind_schwachwind",
    "wind_offshore_reference",
    "biomass_reference",
    "hydro_reference",
}

# Palette des letzten Artikelgrafik-Stands: Wind bewusst blau/marine, nicht
# violett. Szenarien werden nur durch Helligkeit und Beschriftung getrennt.
CARRIER_COLORS = {
    "Solar": "#F2C230",
    "Wind an Land": "#4C78A8",
    "Wind auf See": "#24527A",
    "Biomasse": "#4F8A4C",
    "Wasser": "#15979F",
}
CARRIER_ORDER = ["Solar", "Wind an Land", "Wind auf See", "Biomasse", "Wasser"]

SMARD_COLUMN = {
    "Solar": "pv_mwh",
    "Wind an Land": "wind_onshore_mwh",
    "Wind auf See": "wind_offshore_mwh",
    "Biomasse": "biomass_mwh",
    "Wasser": "hydro_mwh",
}

# UBA/AGEE-Stat: installierte Bruttoleistung zum Jahresende, MW. Biomasse ist
# die Summe aus fester, flüssiger und gasförmiger Biomasse. Für das jeweilige
# Referenzjahr wird zwischen Vorjahres- und Jahresendbestand linear interpoliert.
# Quelle: UBA, "Erneuerbare Energien in Deutschland 2025", Tabelle 2.
CAPACITY_YEAR_END_MW = {
    2023: {
        "Solar": 84_082.0,
        "Wind an Land": 60_971.0,
        "Wind auf See": 8_473.0,
        "Biomasse": 2_594.0 + 192.0 + 7_715.0,
        "Wasser": 5_607.0,
    },
    2024: {
        "Solar": 102_364.0,
        "Wind an Land": 63_535.0,
        "Wind auf See": 9_215.0,
        "Biomasse": 2_611.0 + 187.0 + 7_800.0,
        "Wasser": 5_496.0,
    },
    2025: {
        "Solar": 119_952.0,
        "Wind an Land": 68_145.0,
        "Wind auf See": 9_733.0,
        "Biomasse": 2_654.0 + 178.0 + 7_866.0,
        "Wasser": 5_497.0,
    },
}

# Direkte kraftwerksseitige THG-Emissionen je erzeugter MWh Strom.
# Grundlage: UBA Emissionsbilanz 2024; Brennstoffemissionen geteilt durch die
# dort ausgewiesenen mittleren Brutto-Nutzungsgrade. Für die heterogene
# SMARD-Sammelkategorie "Sonstige Konventionelle" bleibt Leichtöl der
# transparente direkte Proxy.
DIRECT_FOSSIL_EMISSIONS_T_CO2E_MWH = {
    "lignite": 0.40903 / 0.397,
    "hard_coal": 0.38251 / 0.436,
    "gas": 0.24773 / 0.566,
    "other_conventional": 0.31270 / 0.383,
}

# Expliziter Vorketten-Aufschlag je erzeugter MWh Strom. Der Aufschlag wird
# getrennt von der direkten Verbrennung ausgewiesen und erst im Rechenkern
# addiert. Verwendet werden konservative obere, aber noch belastbar
# dokumentierte Werte – keine extremen Einzelstudien oder vom UBA selbst als
# hoch unsicher bezeichneten Sensitivitäten.
#
# Braunkohle: UNECE-Lebenszyklusmittel 1,093 t/MWh minus direkter UBA-Wert.
# Steinkohle: höchster regulärer UBA-Lieferlandwert 11,4 g CO2e/MJ (Russland),
#              umgerechnet mit 43,6 % Brutto-Nutzungsgrad.
# Erdgas: höchster regulärer UBA-LNG-Wert inkl. Verteilung 22,4 g CO2e/MJ
#         (US-LNG), umgerechnet mit 56,6 % Brutto-Nutzungsgrad. Die UBA-
#         Sensitivität 30,0 g/MJ wird nicht als Hauptwert verwendet, weil sie
#         dort ausdrücklich als hoch unsicher eingestuft wird.
# Sonstige: konservativer Ölprodukt-Proxy aus JEC WTT v5, 18,9 g CO2e/MJ
#           Kraftstoffbereitstellung, umgerechnet mit 38,3 % Nutzungsgrad.
UPSTREAM_SURCHARGE_T_CO2E_MWH = {
    "lignite": 1.093 - DIRECT_FOSSIL_EMISSIONS_T_CO2E_MWH["lignite"],
    "hard_coal": 11.4 * 0.0036 / 0.436,
    "gas": 22.4 * 0.0036 / 0.566,
    "other_conventional": 18.9 * 0.0036 / 0.383,
}

# Gesamtansatz für die stündliche Klimaleistungsrechnung. Der Name bleibt als
# kompatible öffentliche Schnittstelle für das separate Deckungsanalyse-Skript
# erhalten; in Methodik und Ergebnisdateien werden direkte Emissionen und
# Vorketten-Aufschlag immer getrennt ausgewiesen.
FOSSIL_EMISSIONS_T_CO2E_MWH = {
    key: DIRECT_FOSSIL_EMISSIONS_T_CO2E_MWH[key]
    + UPSTREAM_SURCHARGE_T_CO2E_MWH[key]
    for key in DIRECT_FOSSIL_EMISSIONS_T_CO2E_MWH
}

# Die Artikelgrafik bilanziert bewusst nur die unter der Modellannahme
# rechnerisch verdrängten fossilen Emissionen. Lebenszyklus- und direkte
# Emissionen der erneuerbaren Technologien werden nicht eingerechnet, damit
# alle Energieträger mit exakt derselben stündlichen Verdrängungsregel
# verglichen werden. Diese Bruttowirkung ist keine vollständige Ökobilanz.

UBA_CAPACITY_URL = (
    "https://www.umweltbundesamt.de/system/files/medien/479/publikationen/"
    "2026-03/UBA_Erneuerbare%20Energien%20in%20Deutschland%202025.pdf"
)
UBA_EMISSIONS_URL = (
    "https://www.umweltbundesamt.de/system/files/medien/11850/publikationen/"
    "2026-01/11_2026_CC.pdf"
)
UBA_UPSTREAM_URL = (
    "https://www.umweltbundesamt.de/system/files/medien/1410/publikationen/"
    "cc_61-2021_emissionsfaktoren-stromerzeugung_bf.pdf"
)
UNECE_LCA_URL = "https://unece.org/sites/default/files/2021-11/LCA_final.pdf"
JEC_WTT_URL = "https://doi.org/10.2760/100379"
SMARD_URL = "https://www.smard.de/"
NETZTRANSPARENZ_EEG_URL = (
    "https://www.netztransparenz.de/de-de/Erneuerbare-Energien-und-Umlagen/"
    "EEG/EEG-Abrechnungen/EEG-Jahresabrechnungen/EEG-Bewegungsdaten"
)
EEG_MARKET_PREMIUM_LAW_URL = (
    "https://www.gesetze-im-internet.de/eeg_2014/anlage_1.html"
)

SCENARIO_SPECS = {
    "pv_sued_30": ("Solar", "PV Süd 30°", "Süd\n30°"),
    "pv_sued_60": ("Solar", "PV Süd 60°", "Süd\n60°"),
    "pv_ost_west_15": ("Solar", "PV Ost–West 15°", "O–W\n15°"),
    "pv_ost_west_30": ("Solar", "PV Ost–West 30°", "O–W\n30°"),
    "wind_standard": ("Wind an Land", "Wind Standardanlage", "Standard\nanlage"),
    "wind_schwachwind": (
        "Wind an Land",
        "Wind Schwachwindanlage",
        "Schwach-\nwind",
    ),
}


@dataclass
class SmardData:
    timestamp_ms: np.ndarray
    price_eur_mwh: np.ndarray
    fossil_factor_t_mwh: np.ndarray
    generation: dict[str, np.ndarray]


@dataclass
class Case:
    case_id: str
    carrier: str
    label: str
    short_label: str
    is_reference: bool
    capacity_basis: str
    energy_mwh_per_mw: float
    market_revenue_eur_per_mw: float
    displaced_thg_t_co2e_per_mw: float
    displaced_thg_t_co2e_per_mwh: float
    method: str
    source: str
    source_url: str
    validation_status: str
    raw_energy_mwh_per_mw: float | None = None
    normalization_factor: float | None = None
    smard_hourly_correlation: float | None = None
    smard_monthly_share_mae_pp: float | None = None
    normalization_mode: str = "none"
    smard_shape_market_value_eur_per_mwh: float | None = None
    market_value_profile_delta_pct: float | None = None
    smard_shape_displaced_thg_t_co2e_per_mw: float | None = None
    thg_profile_delta_pct: float | None = None


@dataclass
class EegStats:
    carrier: str
    full_min_ct_kwh: float
    full_max_ct_kwh: float
    full_mean_ct_kwh: float
    premium_min_ct_kwh: float
    premium_max_ct_kwh: float
    premium_mean_ct_kwh: float
    full_quantity_kwh: float
    premium_quantity_kwh: float
    included_full_categories: int
    excluded_full_categories: int
    included_premium_categories: int
    excluded_premium_categories: int
    zero_full_categories: int
    zero_premium_categories: int
    negative_full_quantity_kwh: float
    negative_premium_quantity_kwh: float
    negative_full_payment_eur: float
    negative_premium_payment_eur: float
    raw_full_min_ct_kwh: float
    raw_full_max_ct_kwh: float
    raw_premium_min_ct_kwh: float
    raw_premium_max_ct_kwh: float

def de(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def shade(color: str, amount: float) -> tuple[float, float, float]:
    from matplotlib.colors import to_rgb

    rgb = np.asarray(to_rgb(color), dtype=float)
    target = np.ones(3) if amount >= 0 else np.zeros(3)
    return tuple(rgb + (target - rgb) * abs(amount))


def sqlite_integrity(path: Path, label: str) -> None:
    if not path.exists():
        raise RuntimeError(f"{label} nicht gefunden: {path}")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = con.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(
            f"{label} ist nicht vollständig lesbar: {path} ({exc}). "
            "Bei kopierten Dateien Dateigröße/Übertragung prüfen."
        ) from exc
    finally:
        con.close()
    if result != "ok":
        raise RuntimeError(f"{label} beschädigt (SQLite integrity_check: {result}).")


def read_metadata(con: sqlite3.Connection) -> dict[str, str]:
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "metadata" not in tables:
        return {}
    return {str(key): str(value) for key, value in con.execute("SELECT key,value FROM metadata")}


def load_smard(path: Path, year: int) -> SmardData:
    sqlite_integrity(path, "SMARD-Datenbank")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cols = {row[1] for row in con.execute("PRAGMA table_info(hourly)")}
        required = {
            "timestamp_ms",
            "local_year",
            "price_eur_mwh",
            "lignite_mwh",
            "hard_coal_mwh",
            "gas_mwh",
            "other_conventional_mwh",
            *SMARD_COLUMN.values(),
        }
        missing = required - cols
        if missing:
            raise RuntimeError("SMARD-Spalten fehlen: " + ", ".join(sorted(missing)))
        names = [
            "timestamp_ms",
            "price_eur_mwh",
            "lignite_mwh",
            "hard_coal_mwh",
            "gas_mwh",
            "other_conventional_mwh",
            *SMARD_COLUMN.values(),
        ]
        rows = con.execute(
            "SELECT " + ",".join(names) + " FROM hourly "
            "WHERE local_year=? ORDER BY timestamp_ms",
            (year,),
        ).fetchall()
    finally:
        con.close()
    if len(rows) not in {8760, 8784}:
        raise RuntimeError(
            f"SMARD {year}: {len(rows)} statt 8.760/8.784 Stunden. "
            "Unvollständige Jahre werden nicht hochgerechnet."
        )
    array = np.asarray(rows, dtype=float)
    timestamps = array[:, 0].astype(np.int64)
    if np.any(np.diff(timestamps) != 3_600_000):
        raise RuntimeError(f"SMARD {year}: Zeitachse ist nicht lückenlos stündlich.")
    if np.any(~np.isfinite(array)):
        raise RuntimeError(f"SMARD {year}: nichtnumerische oder fehlende Werte.")
    if np.any(array[:, 2:] < 0):
        raise RuntimeError(f"SMARD {year}: negative Erzeugungswerte gefunden.")

    lignite, coal, gas, other = array[:, 2], array[:, 3], array[:, 4], array[:, 5]
    fossil = lignite + coal + gas + other
    emissions = (
        lignite * FOSSIL_EMISSIONS_T_CO2E_MWH["lignite"]
        + coal * FOSSIL_EMISSIONS_T_CO2E_MWH["hard_coal"]
        + gas * FOSSIL_EMISSIONS_T_CO2E_MWH["gas"]
        + other * FOSSIL_EMISSIONS_T_CO2E_MWH["other_conventional"]
    )
    fossil_factor = np.divide(
        emissions, fossil, out=np.zeros_like(emissions), where=fossil > 0
    )
    generation = {
        carrier: array[:, 6 + index]
        for index, carrier in enumerate(SMARD_COLUMN)
    }
    return SmardData(
        timestamp_ms=timestamps,
        price_eur_mwh=array[:, 1],
        fossil_factor_t_mwh=fossil_factor,
        generation=generation,
    )


def interpolated_capacity_profile_mw(carrier: str, year: int, hours: int) -> np.ndarray:
    """Linearer Kapazitätspfad zwischen den amtlichen Jahresendbeständen.

    Die SMARD-Erzeugung wird dadurch stündlich auf die jeweils angenäherte
    Flottenleistung bezogen. Das ist belastbarer als ein einziger Jahresmittelwert,
    bleibt aber mangels monatlicher MaStR-Kapazitätsreihe eine transparente
    Interpolationsannahme.
    """
    if hours <= 1:
        raise RuntimeError("Kapazitätsinterpolation benötigt mehr als eine Stunde.")
    if year not in CAPACITY_YEAR_END_MW or year - 1 not in CAPACITY_YEAR_END_MW:
        raise RuntimeError(
            f"Für {year} fehlen belastbare Anfangs-/Endkapazitäten. "
            "Derzeit sind Referenzen für 2024 und 2025 hinterlegt."
        )
    start = float(CAPACITY_YEAR_END_MW[year - 1][carrier])
    end = float(CAPACITY_YEAR_END_MW[year][carrier])
    if start <= 0 or end <= 0:
        raise RuntimeError(f"Ungültige Kapazität für {carrier}: {start}/{end} MW.")
    return np.linspace(start, end, hours, endpoint=True, dtype=float)


def build_reference_cases(smard: SmardData, year: int) -> list[Case]:
    """Nationale Netzeinspeisungsreferenzen je stündlich angenähertem MW.

    Die realisierte SMARD-Erzeugung umfasst nur die Netzeinspeisung in das Netz
    der allgemeinen Versorgung. Genau diese vermarktbare beziehungsweise
    vergütbare Menge ist der Vergleichsgegenstand der Artikelgrafiken. Daher
    wird die SMARD-Reihe ohne Ertragsnormierung durch einen linearen
    Kapazitätspfad zwischen den amtlichen Jahresendbeständen geteilt.
    """
    labels = {
        "Solar": ("PV · SMARD-Netzeinspeisung", "SMARD\nNetz"),
        "Wind an Land": ("Wind an Land · SMARD-Netzeinspeisung", "SMARD\nNetz"),
        "Wind auf See": ("Wind auf See · SMARD-Netzeinspeisung", "SMARD\nNetz"),
        "Biomasse": ("Biomasse · SMARD-Netzeinspeisung", "SMARD\nNetz"),
        "Wasser": ("Wasser · SMARD-Netzeinspeisung", "SMARD\nNetz"),
    }
    ids = {
        "Solar": "pv_reference",
        "Wind an Land": "wind_onshore_reference",
        "Wind auf See": "wind_offshore_reference",
        "Biomasse": "biomass_reference",
        "Wasser": "hydro_reference",
    }
    cases: list[Case] = []
    for carrier in CARRIER_ORDER:
        feed_in = np.asarray(smard.generation[carrier], dtype=float)
        capacity = interpolated_capacity_profile_mw(carrier, year, len(feed_in))
        profile = np.divide(
            feed_in, capacity, out=np.zeros_like(feed_in), where=capacity > 0
        )
        if np.any(~np.isfinite(profile)) or np.any(profile < 0):
            raise RuntimeError(f"Ungültiges SMARD-Netzeinspeisungsprofil für {carrier}.")
        if float(profile.max()) > 1.05:
            raise RuntimeError(
                f"SMARD-Netzeinspeisung {carrier} überschreitet 1 MW/MW deutlich "
                f"({float(profile.max()):.3f}); Kapazitätsabgrenzung prüfen."
            )
        energy = float(profile.sum())
        if energy <= 0:
            raise RuntimeError(f"Nichtpositive SMARD-Netzeinspeisung für {carrier}.")
        market_revenue = float(np.dot(profile, smard.price_eur_mwh))
        displaced = float(np.dot(profile, smard.fossil_factor_t_mwh))
        if displaced <= 0:
            raise RuntimeError(f"Nichtpositive THG-Verdrängung für {carrier}.")
        label, short = labels[carrier]
        cases.append(
            Case(
                case_id=ids[carrier],
                carrier=carrier,
                label=label,
                short_label=short,
                is_reference=True,
                capacity_basis="MWp DC" if carrier == "Solar" else "MW Nennleistung",
                energy_mwh_per_mw=energy,
                market_revenue_eur_per_mw=market_revenue,
                displaced_thg_t_co2e_per_mw=displaced,
                displaced_thg_t_co2e_per_mwh=displaced / energy,
                method=(
                    "Stündliche realisierte SMARD-Netzeinspeisung geteilt durch "
                    "linear zwischen den UBA/AGEE-Stat-Jahresendbeständen "
                    "interpolierte installierte Leistung; stündlicher Day-ahead-Preis "
                    "und stündlicher fossiler SMARD-Restmix"
                ),
                source=(
                    f"SMARD realisierte Nettostromerzeugung {year}; "
                    f"UBA/AGEE-Stat Kapazitäten {year - 1}/{year}"
                ),
                source_url=UBA_CAPACITY_URL,
                validation_status="SMARD-NETZEINSPEISUNG · KEINE ERTRAGSNORMIERUNG",
                raw_energy_mwh_per_mw=energy,
                normalization_factor=1.0,
                normalization_mode="none",
                smard_shape_market_value_eur_per_mwh=market_revenue / energy,
                market_value_profile_delta_pct=0.0,
                smard_shape_displaced_thg_t_co2e_per_mw=displaced,
                thg_profile_delta_pct=0.0,
            )
        )
    return cases


def select_site_id(
    con: sqlite3.Connection, year: int, requested_site_id: str | None
) -> str:
    rows = con.execute(
        "SELECT DISTINCT site_id FROM verification_summary WHERE year=? ORDER BY site_id",
        (year,),
    ).fetchall()
    site_ids = [str(row[0]) for row in rows]

    available = con.execute(
        "SELECT year,site_id,COUNT(*) FROM verification_summary "
        "GROUP BY year,site_id ORDER BY year,site_id"
    ).fetchall()
    available_text = "; ".join(
        f"{int(available_year)}: {site_id} ({int(count)} Szenarien)"
        for available_year, site_id, count in available
    ) or "keine verifizierten Jahre/Standorte"

    if requested_site_id:
        if requested_site_id not in site_ids:
            raise RuntimeError(
                f"site_id '{requested_site_id}' fehlt für das Auswertungsjahr {year}. "
                f"Verfügbar: {available_text}"
            )
        return requested_site_id
    if not site_ids:
        raise RuntimeError(
            f"Szenariendatenbank enthält keine verifizierten Szenarien für {year}. "
            f"Verfügbar: {available_text}. Auswertungsjahr mit --year wählen."
        )
    if len(site_ids) > 1:
        raise RuntimeError(
            f"Szenariendatenbank enthält für {year} mehrere Standorte: "
            + ", ".join(site_ids)
            + ". Mit --site-id auswählen."
        )
    return site_ids[0]


def load_scenario_cases(
    path: Path, smard: SmardData, year: int, requested_site_id: str | None
) -> tuple[list[Case], str]:
    sqlite_integrity(path, "Wetter-/Szenariendatenbank")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required_tables = {"scenario_definition", "scenario_hourly", "verification_summary"}
        missing = required_tables - tables
        if missing:
            raise RuntimeError(
                "Szenariendatenbank-Tabellen fehlen: " + ", ".join(sorted(missing))
            )
        site_id = select_site_id(con, year, requested_site_id)
        timestamp_index = {int(value): index for index, value in enumerate(smard.timestamp_ms)}
        start_ms, end_ms = int(smard.timestamp_ms[0]), int(smard.timestamp_ms[-1])
        cases: list[Case] = []
        for scenario_id, (carrier, fallback_label, short_label) in SCENARIO_SPECS.items():
            definition = con.execute(
                "SELECT label,model_version,parameters_json FROM scenario_definition WHERE scenario_id=?",
                (scenario_id,),
            ).fetchone()
            if not definition:
                raise RuntimeError(f"Szenario fehlt: {scenario_id}")
            label = str(definition[0] or fallback_label)
            scenario_model_version = str(definition[1] or "0")
            try:
                version_parts = tuple(
                    int(part) for part in scenario_model_version.split(".")[:2]
                )
            except ValueError:
                version_parts = (0, 0)
            if version_parts < (2, 2):
                raise RuntimeError(
                    f"{scenario_id}: Szenariomodell {scenario_model_version} ist "
                    "für die wissenschaftlich korrigierte Auswertung zu alt. "
                    "wetterdaten_szenarienverifizierung.py Version 2.2 oder neuer "
                    "für 2024 erneut ausführen."
                )
            try:
                parameters = json.loads(definition[2] or "{}")
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Ungültiges parameters_json: {scenario_id}") from exc
            summary = con.execute(
                "SELECT energy_mwh_per_mw,gross_avoided_t_co2e_per_mw,"
                "validation_status,normalization_source,reference_mode,"
                "target_energy_mwh_per_mw,normalized_deviation_pct,"
                "thg_profile_delta_pct,raw_energy_mwh_per_mw,"
                "normalization_factor,smard_hourly_correlation,"
                "smard_monthly_share_mae_pp FROM verification_summary "
                "WHERE year=? AND scenario_id=? AND site_id=?",
                (year, scenario_id, site_id),
            ).fetchone()
            if not summary:
                raise RuntimeError(
                    f"Verifikationszusammenfassung fehlt: {year}/{site_id}/{scenario_id}"
                )
            rows = con.execute(
                "SELECT timestamp_ms,generation_mwh_per_mw FROM scenario_hourly "
                "WHERE scenario_id=? AND site_id=? AND timestamp_ms BETWEEN ? AND ? "
                "ORDER BY timestamp_ms",
                (scenario_id, site_id, start_ms, end_ms),
            ).fetchall()
            if len(rows) != len(smard.timestamp_ms):
                raise RuntimeError(
                    f"{scenario_id}: {len(rows)} statt {len(smard.timestamp_ms)} Stunden."
                )
            profile = np.zeros(len(rows), dtype=float)
            seen: set[int] = set()
            for timestamp, value in rows:
                timestamp = int(timestamp)
                if timestamp not in timestamp_index or timestamp in seen:
                    raise RuntimeError(f"{scenario_id}: Zeitachse passt nicht zu SMARD.")
                seen.add(timestamp)
                profile[timestamp_index[timestamp]] = float(value)
            if np.any(~np.isfinite(profile)) or np.any(profile < 0):
                raise RuntimeError(f"{scenario_id}: ungültige Stundenwerte.")
            if float(profile.max()) > 1.000001:
                raise RuntimeError(
                    f"{scenario_id}: normiertes Profil überschreitet 1 MW/MW "
                    f"({float(profile.max()):.6f})."
                )
            energy = float(profile.sum())
            summary_energy = float(summary[0])
            target_energy = float(summary[5])
            if abs(energy - summary_energy) > max(0.1, summary_energy * 0.001):
                raise RuntimeError(
                    f"{scenario_id}: Stunden- und Summenertrag widersprechen sich "
                    f"({energy:.3f} vs. {summary_energy:.3f} MWh/MW)."
                )
            if abs(summary_energy - target_energy) > max(0.1, target_energy * 0.001):
                raise RuntimeError(
                    f"{scenario_id}: Literaturziel nicht erreicht "
                    f"({summary_energy:.3f} vs. {target_energy:.3f} MWh/MW)."
                )
            market_revenue = float(np.dot(profile, smard.price_eur_mwh))
            displaced = float(np.dot(profile, smard.fossil_factor_t_mwh))
            if displaced <= 0:
                raise RuntimeError(f"{scenario_id}: THG-Verdrängung ist nicht positiv.")

            # Kontrollrechnung mit dem nationalen SMARD-Profil desselben
            # Energieträgers, auf exakt denselben Jahresertrag normiert. Sie
            # quantifiziert, wie stark Marktwert und THG-Ergebnis von der
            # modellierten zeitlichen Profilform abhängen.
            control_raw = np.asarray(smard.generation[carrier], dtype=float)
            control_total = float(control_raw.sum())
            if control_total <= 0:
                raise RuntimeError(f"{scenario_id}: SMARD-Kontrollprofil ist leer.")
            control_profile = control_raw / control_total * energy
            control_market = float(np.dot(control_profile, smard.price_eur_mwh))
            control_displaced = float(
                np.dot(control_profile, smard.fossil_factor_t_mwh)
            )
            market_value = market_revenue / energy
            control_market_value = control_market / energy
            market_profile_delta = (
                (market_value / control_market_value - 1.0) * 100.0
                if control_market_value else float("nan")
            )
            thg_profile_delta = (
                (displaced / control_displaced - 1.0) * 100.0
                if control_displaced else float("nan")
            )
            if not math.isfinite(thg_profile_delta) or abs(thg_profile_delta) > 10.0:
                raise RuntimeError(
                    f"{scenario_id}: THG-Abweichung zum ertragsgleichen "
                    f"SMARD-Kontrollprofil {thg_profile_delta:+.2f} % "
                    "überschreitet 10 %."
                )
            if not math.isfinite(market_profile_delta) or abs(market_profile_delta) > 20.0:
                raise RuntimeError(
                    f"{scenario_id}: Marktwert-Abweichung zum ertragsgleichen "
                    f"SMARD-Kontrollprofil {market_profile_delta:+.2f} % "
                    "überschreitet 20 %. Profilmodell prüfen."
                )
            raw_energy = float(summary[8])
            normalization_factor = float(summary[9])
            correlation = float(summary[10])
            monthly_mae = float(summary[11])
            if not math.isfinite(correlation) or correlation < 0.60:
                raise RuntimeError(
                    f"{scenario_id}: Stundenkorrelation zum SMARD-Profil "
                    f"ist mit {correlation:.3f} zu gering."
                )
            if not math.isfinite(monthly_mae) or monthly_mae > 2.5:
                raise RuntimeError(
                    f"{scenario_id}: monatlicher Profilfehler {monthly_mae:.2f} pp "
                    "ist zu groß."
                )
            source = str(summary[3] or parameters.get("target_source", ""))
            source_url = str(parameters.get("target_url", ""))
            capacity_basis = str(
                parameters.get(
                    "capacity_basis", "MWp DC" if carrier == "Solar" else "MW Nennleistung"
                )
            )
            normalization_mode = str(
                parameters.get("normalization_mode", "unknown")
            )
            if normalization_mode == "wind_speed_scale":
                if 0.85 <= normalization_factor <= 1.20:
                    status = "LITERATURKALIBRIERT · WINDGESCHWINDIGKEIT"
                elif 0.70 <= normalization_factor <= 1.50:
                    status = "LITERATURKALIBRIERT · DEUTLICHE WINDKALIBRIERUNG"
                else:
                    status = "LITERATURKALIBRIERT · STARKE WINDKALIBRIERUNG"
            elif 0.80 <= normalization_factor <= 1.25:
                status = "LITERATURNORMIERT"
            elif 0.67 <= normalization_factor <= 1.50:
                status = "LITERATURNORMIERT · DEUTLICHE NORMIERUNG"
            else:
                status = "LITERATURNORMIERT · STARKE NORMIERUNG"
            if abs(market_profile_delta) > 10.0:
                status += " · MARKTWERT-PROFIL SENSITIV"
            original_status = str(summary[2] or "UNBEKANNT")
            if original_status != "OK":
                status += f" · {original_status}"
            cases.append(
                Case(
                    case_id=scenario_id,
                    carrier=carrier,
                    label=label,
                    short_label=short_label,
                    is_reference=False,
                    capacity_basis=capacity_basis,
                    energy_mwh_per_mw=energy,
                    market_revenue_eur_per_mw=market_revenue,
                    displaced_thg_t_co2e_per_mw=displaced,
                    displaced_thg_t_co2e_per_mwh=displaced / energy,
                    method=(
                        f"{summary[4]}; Artikelwert aus normiertem Stundenprofil "
                        "mal stündlichem fossilen SMARD-Restmix neu berechnet"
                    ),
                    source=source,
                    source_url=source_url,
                    validation_status=status,
                    raw_energy_mwh_per_mw=raw_energy,
                    normalization_factor=normalization_factor,
                    smard_hourly_correlation=correlation,
                    smard_monthly_share_mae_pp=monthly_mae,
                    normalization_mode=normalization_mode,
                    smard_shape_market_value_eur_per_mwh=control_market_value,
                    market_value_profile_delta_pct=market_profile_delta,
                    smard_shape_displaced_thg_t_co2e_per_mw=control_displaced,
                    thg_profile_delta_pct=thg_profile_delta,
                )
            )
        return cases, site_id
    finally:
        con.close()


def normalize_carrier(value: object) -> str:
    key = str(value or "").strip().replace(".0", "")
    return {
        "1": "Wasser",
        "5": "Biomasse",
        "7": "Wind an Land",
        "8": "Wind auf See",
        "9": "Solar",
        "Wasser": "Wasser",
        "Biomasse": "Biomasse",
        "Solar": "Solar",
        "Solarenergie": "Solar",
        "Wind an Land": "Wind an Land",
        "Windenergie an Land": "Wind an Land",
        "Wind auf See": "Wind auf See",
        "Windenergie auf See": "Wind auf See",
    }.get(key, key)


def load_eeg_stats(path: Path) -> tuple[dict[str, EegStats], str]:
    """Liest EEG-Jahreskategorien ohne Mengenfilter.

    Die sichtbare Min-Max-Spanne verwendet alle nichtnegativen, über das
    Gesamtjahr und die Vergütungskategorie aggregierten Sätze. Negative
    Marktprämienzeilen sind laut EEG keine negative gesetzliche Marktprämie:
    Die Marktprämie wird bei null gekappt; Netztransparenz weist rechnerisch
    negative Abrechnungszeilen aus und gleicht sie über zusätzliche Kategorien
    aus. Sie bleiben deshalb im aggregierten Zahlungs-Mittelwert und in der CSV
    erhalten, werden aber nicht als negative Tarifuntergrenze gezeichnet.
    """
    sqlite_integrity(path, "EEG-Datenbank")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "eeg_data" not in tables:
            raise RuntimeError(
                "EEG-Datenbank benötigt die verdichtete Tabelle 'eeg_data'. "
                "Bitte mit netztransparenz_daten_import.py erzeugen."
            )
        metadata = read_metadata(con)
        eeg_year = metadata.get("year", "unbekannt")
        query = (
            "SELECT carrier,category,SUM(quantity_kwh),SUM(payment_eur),"
            "MIN(payment_ct_kwh),MAX(payment_ct_kwh) FROM eeg_data "
            "WHERE CAST(sale_form AS TEXT)=? AND quantity_kwh>0 "
            "AND payment_eur IS NOT NULL GROUP BY carrier,category "
            "HAVING SUM(quantity_kwh)>0"
        )
        full_rows = con.execute(query, ("1",)).fetchall()
        premium_rows = con.execute(query, ("2",)).fetchall()
    finally:
        con.close()

    def group_rows(rows):
        grouped: dict[str, list[tuple[str, float, float, float, float]]] = {}
        for carrier, category, quantity, payment, raw_min, raw_max in rows:
            normalized = normalize_carrier(carrier)
            if normalized not in CARRIER_ORDER:
                continue
            grouped.setdefault(normalized, []).append(
                (
                    str(category),
                    float(quantity),
                    float(payment),
                    float(raw_min) if raw_min is not None else float("nan"),
                    float(raw_max) if raw_max is not None else float("nan"),
                )
            )
        return grouped

    def band(categories, carrier: str, label: str):
        if not categories:
            raise RuntimeError(f"Keine EEG-{label}daten für {carrier}.")
        valid: list[tuple[float, float, float]] = []
        raw_mins = [row[3] for row in categories if math.isfinite(row[3])]
        raw_maxs = [row[4] for row in categories if math.isfinite(row[4])]
        for _category, quantity, payment, _raw_min, _raw_max in categories:
            rate = payment / quantity * 100.0
            if math.isfinite(rate):
                valid.append((rate, quantity, payment))
        if not valid:
            raise RuntimeError(f"Keine numerischen EEG-{label}kategorien für {carrier}.")

        nonnegative = [row for row in valid if row[0] >= 0.0]
        negative = [row for row in valid if row[0] < 0.0]
        if not nonnegative:
            raise RuntimeError(
                f"Keine nichtnegative EEG-{label}kategorie für {carrier}."
            )
        all_quantity = sum(row[1] for row in valid)
        all_payment = sum(row[2] for row in valid)
        visible_rates = np.asarray([row[0] for row in nonnegative], dtype=float)
        return {
            "minimum": float(visible_rates.min()),
            "maximum": float(visible_rates.max()),
            # Der Mittelwert bildet die gesamte beobachtete Jahresabrechnung ab,
            # einschließlich negativer und positiver Ausgleichskategorien.
            "mean": float(all_payment / all_quantity * 100.0),
            "quantity": float(all_quantity),
            "included": len(nonnegative),
            "excluded": len(negative),
            "zero": sum(abs(row[0]) < 1e-12 for row in nonnegative),
            "negative_quantity": float(sum(row[1] for row in negative)),
            "negative_payment": float(sum(row[2] for row in negative)),
            "raw_min": min(raw_mins) if raw_mins else float("nan"),
            "raw_max": max(raw_maxs) if raw_maxs else float("nan"),
        }

    full_by_carrier = group_rows(full_rows)
    premium_by_carrier = group_rows(premium_rows)
    result: dict[str, EegStats] = {}
    for carrier in CARRIER_ORDER:
        full = band(full_by_carrier.get(carrier, []), carrier, "Vollvergütungs")
        premium = band(premium_by_carrier.get(carrier, []), carrier, "Marktprämien")
        result[carrier] = EegStats(
            carrier=carrier,
            full_min_ct_kwh=full["minimum"],
            full_max_ct_kwh=full["maximum"],
            full_mean_ct_kwh=full["mean"],
            premium_min_ct_kwh=premium["minimum"],
            premium_max_ct_kwh=premium["maximum"],
            premium_mean_ct_kwh=premium["mean"],
            full_quantity_kwh=full["quantity"],
            premium_quantity_kwh=premium["quantity"],
            included_full_categories=full["included"],
            excluded_full_categories=full["excluded"],
            included_premium_categories=premium["included"],
            excluded_premium_categories=premium["excluded"],
            zero_full_categories=full["zero"],
            zero_premium_categories=premium["zero"],
            negative_full_quantity_kwh=full["negative_quantity"],
            negative_premium_quantity_kwh=premium["negative_quantity"],
            negative_full_payment_eur=full["negative_payment"],
            negative_premium_payment_eur=premium["negative_payment"],
            raw_full_min_ct_kwh=full["raw_min"],
            raw_full_max_ct_kwh=full["raw_max"],
            raw_premium_min_ct_kwh=premium["raw_min"],
            raw_premium_max_ct_kwh=premium["raw_max"],
        )
    return result, eeg_year

def ordered_cases(references: list[Case], scenarios: list[Case]) -> list[Case]:
    reference_by_carrier = {case.carrier: case for case in references}
    scenario_by_id = {case.case_id: case for case in scenarios}
    # Bestand links, danach die literaturnormierten Neufälle. Die Reihenfolge
    # gilt auch für CSV/Methodik; einzelne Fälle können im Plot ausgeblendet
    # werden, ohne aus der Berechnung zu verschwinden.
    order = [
        "pv_reference",
        "pv_sued_30",
        "pv_sued_60",
        "pv_ost_west_15",
        "pv_ost_west_30",
        "wind_onshore_reference",
        "wind_standard",
        "wind_schwachwind",
        "wind_offshore_reference",
        "biomass_reference",
        "hydro_reference",
    ]
    all_cases = {case.case_id: case for case in references}
    all_cases.update(scenario_by_id)
    missing = [case_id for case_id in order if case_id not in all_cases]
    if missing:
        raise RuntimeError("Fälle fehlen: " + ", ".join(missing))
    if set(reference_by_carrier) != set(CARRIER_ORDER):
        raise RuntimeError("Nicht alle SMARD-Bestandsreferenzen wurden erzeugt.")
    return [all_cases[case_id] for case_id in order]


def plotted_cases(cases: Iterable[Case]) -> list[Case]:
    """Für die Hauptgrafiken ausgewählte Fälle; Berechnung und CSV bleiben vollständig."""
    return [case for case in cases if case.case_id in PLOT_CASE_IDS]


def display_short_label(case: Case, year: int) -> str:
    """Kurze Fallbeschriftung; DE macht die nationale Bestandsreferenz eindeutig."""
    if case.is_reference:
        return f"Bestand DE\n{year}"
    return f"Neu\n{case.short_label}"


def setup_style() -> None:
    import matplotlib as mpl

    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.axisbelow": True,
            "axes.titleweight": "bold",
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def case_positions(cases: Iterable[Case], gap: float = 0.8):
    cases = list(cases)
    positions: list[float] = []
    group_centres: list[tuple[str, float]] = []
    separators: list[float] = []
    cursor = 0.0
    for carrier in CARRIER_ORDER:
        group = [case for case in cases if case.carrier == carrier]
        if not group:
            continue
        start = cursor
        positions.extend(cursor + index for index in range(len(group)))
        cursor += len(group)
        group_centres.append((carrier, (start + cursor - 1.0) / 2.0))
        separators.append(cursor - 0.5 + gap / 2.0)
        cursor += gap
    if separators:
        separators.pop()
    return np.asarray(positions), group_centres, separators


def save_figure(fig, path_without_suffix: Path) -> None:
    fig.savefig(path_without_suffix.with_suffix(".svg"), bbox_inches="tight")
    fig.savefig(path_without_suffix.with_suffix(".png"), dpi=220, bbox_inches="tight")


def plot_climate(out: Path, cases: list[Case], year: int) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    setup_style()
    shown = plotted_cases(cases)
    x, group_centres, separators = case_positions(shown, gap=0.9)
    values = np.asarray([case.displaced_thg_t_co2e_per_mw for case in shown])
    fig, ax = plt.subplots(figsize=(15.7, 7.6))
    fig.subplots_adjust(top=0.76, bottom=0.20, left=0.075, right=0.985)

    for xpos, case, value in zip(x, shown, values):
        color = CARRIER_COLORS[case.carrier]
        face = shade(color, 0.42) if case.is_reference else color
        edge = color if case.is_reference else "none"
        ax.bar(xpos, value, width=0.68, color=face, edgecolor=edge, linewidth=1.4)
        ax.text(
            xpos,
            value + values.max() * 0.020,
            f"{de(value)} t\n{de(case.energy_mwh_per_mw)} MWh",
            ha="center",
            va="bottom",
            fontsize=8.4,
            linespacing=1.15,
        )

    ax.set_ylabel("Rechnerisch verdrängte fossile THG in t CO₂e/(MW·a)")
    ax.set_xticks(x, [display_short_label(case, year) for case in shown], fontsize=8.5)
    ax.set_ylim(0, values.max() * 1.20)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.8)
    for separator in separators:
        ax.axvline(separator, color="#E1E1E1", linewidth=0.9)
    for carrier, centre in group_centres:
        ax.text(
            centre,
            1.018,
            carrier,
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
            color=CARRIER_COLORS[carrier],
        )

    fig.suptitle(
        "1  Jährliche fossile THG-Verdrängung je MW",
        x=0.075,
        y=0.985,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.075,
        0.927,
        f"Bestand DE {year} und literaturnormierte Neufälle × stündlicher fossiler SMARD-Mix · Jahresenergie klein unter dem THG-Wert",
        color="#555555",
        fontsize=10.2,
    )
    handles = [Patch(facecolor=CARRIER_COLORS[c], label=c) for c in CARRIER_ORDER]
    handles.append(
        Patch(
            facecolor="#EFEFEF",
            edgecolor="#666666",
            linewidth=1.2,
            label=f"Bestand DE {year}: heller Balken",
        )
    )
    fig.legend(
        handles=handles,
        frameon=False,
        ncol=6,
        loc="upper left",
        bbox_to_anchor=(0.07, 0.895),
        columnspacing=1.6,
        handlelength=1.5,
    )
    fig.text(
        0.075,
        0.028,
        f"Bestand DE = SMARD-Netzeinspeisung je installierter Bestandsleistung · Quellen/Methodik: Begleittext · © {AUTHOR_NAME} {COPYRIGHT_YEAR} · {LICENSE_LABEL}",
        fontsize=8.0,
        color="#555555",
    )
    save_figure(fig, out / "01_thg_verdraengung_pro_fall")
    plt.close(fig)


def plot_revenue(
    out: Path,
    cases: list[Case],
    eeg: dict[str, EegStats],
    smard_year: int,
    eeg_year: str,
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    setup_style()
    shown = plotted_cases(cases)
    by_carrier = {
        carrier: [case for case in shown if case.carrier == carrier]
        for carrier in CARRIER_ORDER
    }
    new_labels = {
        "pv_sued_30": "Neu\nSüd 30°",
        "pv_sued_60": "Neu\nSüd 60°",
        "pv_ost_west_15": "Neu\nO–W 15°",
        "wind_standard": "Neu\nStandard",
        "wind_schwachwind": "Neu\nSchwachwind",
    }
    items: list[tuple[str, Case]] = []
    positions: list[float] = []
    labels: list[str] = []
    group_centres: list[tuple[str, float]] = []
    separators: list[float] = []
    cursor = 0.0

    for carrier in CARRIER_ORDER:
        group = by_carrier[carrier]
        reference = next(case for case in group if case.is_reference)
        new_cases = [case for case in group if not case.is_reference]
        group_positions: list[float] = []

        for mode, label in (
            ("V_REF", "EEG\nVoll"),
            ("MP_REF", "Markt +\nPrämie"),
            ("KL_REF", "Bestand DE\nMarkt + KL"),
        ):
            positions.append(cursor)
            group_positions.append(cursor)
            items.append((mode, reference))
            labels.append(label)
            cursor += 1.0

        if new_cases:
            cursor += 0.45
        for case in new_cases:
            positions.append(cursor)
            group_positions.append(cursor)
            items.append(("KL_NEW", case))
            labels.append(new_labels.get(case.case_id, "Neu\n" + case.short_label.replace("\n", " ")))
            cursor += 1.0

        group_centres.append((carrier, (group_positions[0] + group_positions[-1]) / 2.0))
        separators.append(cursor + 0.30)
        cursor += 1.20
    if separators:
        separators.pop()
    x = np.asarray(positions)

    fig, ax = plt.subplots(figsize=(20.5, 8.7))
    fig.subplots_adjust(top=0.73, bottom=0.21, left=0.062, right=0.993)
    bar_width = 0.62
    top_values: list[float] = []
    scale = 1000.0

    def draw_mean(xpos: float, value: float, width: float, color: str) -> None:
        ax.hlines(value, xpos - width / 2, xpos + width / 2,
                  color="white", linewidth=3.0, zorder=5)
        ax.hlines(value, xpos - width / 2, xpos + width / 2,
                  color=shade(color, -0.48), linewidth=1.55, zorder=6)

    for xpos, (mode, case) in zip(x, items):
        stats = eeg[case.carrier]
        color = CARRIER_COLORS[case.carrier]
        energy = case.energy_mwh_per_mw
        market = case.market_revenue_eur_per_mw / scale

        full_low = stats.full_min_ct_kwh * 10.0 * energy / scale
        full_high = stats.full_max_ct_kwh * 10.0 * energy / scale
        full_mean = stats.full_mean_ct_kwh * 10.0 * energy / scale
        premium_low = market + stats.premium_min_ct_kwh * 10.0 * energy / scale
        premium_high = market + stats.premium_max_ct_kwh * 10.0 * energy / scale
        premium_mean = market + stats.premium_mean_ct_kwh * 10.0 * energy / scale

        if mode == "V_REF":
            ax.bar(xpos, full_low, bar_width, color=color)
            ax.bar(xpos, max(0.0, full_high - full_low), bar_width, bottom=full_low,
                   color=shade(color, 0.68))
            draw_mean(xpos, full_mean, bar_width, color)
            top_values.append(max(full_high, full_mean))
        elif mode == "MP_REF":
            ax.bar(xpos, premium_low, bar_width, color=color)
            ax.bar(xpos, max(0.0, premium_high - premium_low), bar_width,
                   bottom=premium_low, color=shade(color, 0.68))
            draw_mean(xpos, premium_mean, bar_width, color)
            top_values.append(max(premium_high, premium_mean))
        else:
            ax.bar(xpos, market, bar_width, color=shade(color, -0.16))
            block = case.displaced_thg_t_co2e_per_mw * 50.0 / scale
            for index, lightness in enumerate((0.22, 0.44, 0.66)):
                ax.bar(xpos, block, bar_width, bottom=market + index * block,
                       color=shade(color, lightness))
            top_values.append(market + 3.0 * block)

    ymax = max(top_values) * 1.15
    ax.set_ylim(0, ymax)
    ax.set_ylabel("Gesamterlös in Tsd. €/(MW·a)")
    ax.set_xticks(x, labels, fontsize=8.1)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.8)
    for separator in separators:
        ax.axvline(separator, color="#DFDFDF", linewidth=0.9)
    for carrier, centre in group_centres:
        ax.text(
            centre, 1.016, carrier, transform=ax.get_xaxis_transform(),
            ha="center", va="bottom", fontsize=10, fontweight="bold",
            color=CARRIER_COLORS[carrier],
        )

    fig.suptitle(
        "2  EEG-Förderung, Markt und Klimaleistung",
        x=0.062, y=0.985, ha="left", fontsize=17, fontweight="bold",
    )
    fig.text(
        0.062, 0.927,
        f"EEG-Bestand {eeg_year}, stündlicher SMARD-Markt {smard_year} und Markt + Klimaleistung für Bestand und ausgewählte Neufälle · 50–150 €/t CO₂e",
        color="#555555", fontsize=10.2,
    )
    component_handles = [
        Patch(facecolor="#555555", label="dunkel: Untergrenze bzw. Marktwert"),
        Patch(facecolor="#BFBFBF", label="hell: EEG-Spanne bzw. je +50 €/t"),
        Line2D([0], [0], color="#555555", lw=2.0,
               label="farbige Querlinie: mengengewichteter EEG-Mittelwert"),
    ]
    fig.legend(
        handles=component_handles, frameon=False, ncol=3, loc="upper left",
        bbox_to_anchor=(0.057, 0.892), columnspacing=1.55, handlelength=1.65,
        fontsize=9.0,
    )
    fig.text(
        0.062, 0.028,
        f"Quellen und Methodik: Begleittext zur Grafik · © {AUTHOR_NAME} {COPYRIGHT_YEAR} · {LICENSE_LABEL}",
        fontsize=8.0, color="#555555",
    )
    save_figure(fig, out / "02_eeg_markt_und_klimaleistung")
    plt.close(fig)


def write_cases_csv(path: Path, cases: list[Case], year: int, site_id: str) -> None:
    fields = [
        "smard_year",
        "site_id",
        "case_id",
        "carrier",
        "label",
        "is_reference",
        "capacity_basis",
        "energy_mwh_per_mw_a",
        "raw_energy_mwh_per_mw_a",
        "normalization_factor",
        "market_revenue_eur_per_mw_a",
        "market_value_eur_per_mwh",
        "displaced_thg_t_co2e_per_mw_a",
        "displaced_thg_t_co2e_per_mwh",
        "smard_hourly_correlation",
        "smard_monthly_share_mae_pp",
        "normalization_mode",
        "smard_shape_market_value_eur_per_mwh",
        "market_value_profile_delta_pct",
        "smard_shape_displaced_thg_t_co2e_per_mw_a",
        "thg_profile_delta_pct",
        "validation_status",
        "method",
        "source",
        "source_url",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    "smard_year": year,
                    "site_id": site_id if not case.is_reference else "SMARD Deutschland",
                    "case_id": case.case_id,
                    "carrier": case.carrier,
                    "label": case.label,
                    "is_reference": int(case.is_reference),
                    "capacity_basis": case.capacity_basis,
                    "energy_mwh_per_mw_a": case.energy_mwh_per_mw,
                    "raw_energy_mwh_per_mw_a": case.raw_energy_mwh_per_mw,
                    "normalization_factor": case.normalization_factor,
                    "market_revenue_eur_per_mw_a": case.market_revenue_eur_per_mw,
                    "market_value_eur_per_mwh": (
                        case.market_revenue_eur_per_mw / case.energy_mwh_per_mw
                    ),
                    "displaced_thg_t_co2e_per_mw_a": case.displaced_thg_t_co2e_per_mw,
                    "displaced_thg_t_co2e_per_mwh": case.displaced_thg_t_co2e_per_mwh,
                    "smard_hourly_correlation": case.smard_hourly_correlation,
                    "smard_monthly_share_mae_pp": case.smard_monthly_share_mae_pp,
                    "normalization_mode": case.normalization_mode,
                    "smard_shape_market_value_eur_per_mwh": case.smard_shape_market_value_eur_per_mwh,
                    "market_value_profile_delta_pct": case.market_value_profile_delta_pct,
                    "smard_shape_displaced_thg_t_co2e_per_mw_a": case.smard_shape_displaced_thg_t_co2e_per_mw,
                    "thg_profile_delta_pct": case.thg_profile_delta_pct,
                    "validation_status": case.validation_status,
                    "method": case.method,
                    "source": case.source,
                    "source_url": case.source_url,
                }
            )


def write_eeg_csv(path: Path, eeg: dict[str, EegStats], eeg_year: str) -> None:
    fields = [
        "eeg_year",
        "carrier",
        "display_rule",
        "full_min_ct_kwh",
        "full_max_ct_kwh",
        "full_weighted_mean_all_categories_ct_kwh",
        "premium_min_nonnegative_ct_kwh",
        "premium_max_nonnegative_ct_kwh",
        "premium_weighted_mean_all_categories_ct_kwh",
        "full_quantity_kwh",
        "premium_quantity_kwh",
        "displayed_full_categories",
        "negative_full_categories_not_in_band",
        "displayed_premium_categories",
        "negative_premium_categories_not_in_band",
        "zero_full_categories",
        "zero_premium_categories",
        "negative_full_quantity_kwh",
        "negative_premium_quantity_kwh",
        "negative_full_payment_eur",
        "negative_premium_payment_eur",
        "raw_monthly_full_min_ct_kwh",
        "raw_monthly_full_max_ct_kwh",
        "raw_monthly_premium_min_ct_kwh",
        "raw_monthly_premium_max_ct_kwh",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for carrier in CARRIER_ORDER:
            stats = eeg[carrier]
            writer.writerow(
                {
                    "eeg_year": eeg_year,
                    "carrier": carrier,
                    "display_rule": (
                        "all annual category rates >= 0; no quantity threshold; "
                        "negative settlement categories retained in total mean"
                    ),
                    "full_min_ct_kwh": stats.full_min_ct_kwh,
                    "full_max_ct_kwh": stats.full_max_ct_kwh,
                    "full_weighted_mean_all_categories_ct_kwh": stats.full_mean_ct_kwh,
                    "premium_min_nonnegative_ct_kwh": stats.premium_min_ct_kwh,
                    "premium_max_nonnegative_ct_kwh": stats.premium_max_ct_kwh,
                    "premium_weighted_mean_all_categories_ct_kwh": stats.premium_mean_ct_kwh,
                    "full_quantity_kwh": stats.full_quantity_kwh,
                    "premium_quantity_kwh": stats.premium_quantity_kwh,
                    "displayed_full_categories": stats.included_full_categories,
                    "negative_full_categories_not_in_band": stats.excluded_full_categories,
                    "displayed_premium_categories": stats.included_premium_categories,
                    "negative_premium_categories_not_in_band": stats.excluded_premium_categories,
                    "zero_full_categories": stats.zero_full_categories,
                    "zero_premium_categories": stats.zero_premium_categories,
                    "negative_full_quantity_kwh": stats.negative_full_quantity_kwh,
                    "negative_premium_quantity_kwh": stats.negative_premium_quantity_kwh,
                    "negative_full_payment_eur": stats.negative_full_payment_eur,
                    "negative_premium_payment_eur": stats.negative_premium_payment_eur,
                    "raw_monthly_full_min_ct_kwh": stats.raw_full_min_ct_kwh,
                    "raw_monthly_full_max_ct_kwh": stats.raw_full_max_ct_kwh,
                    "raw_monthly_premium_min_ct_kwh": stats.raw_premium_min_ct_kwh,
                    "raw_monthly_premium_max_ct_kwh": stats.raw_premium_max_ct_kwh,
                }
            )

def write_thresholds_csv(path: Path, cases: list[Case], eeg: dict[str, EegStats]) -> None:
    fields = [
        "case_id",
        "carrier",
        "label",
        "climate_price_to_match_market_plus_premium_min_eur_t",
        "climate_price_to_match_market_plus_premium_mean_eur_t",
        "climate_price_to_match_market_plus_premium_max_eur_t",
        "climate_price_to_match_full_min_eur_t",
        "climate_price_to_match_full_max_eur_t",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            stats = eeg[case.carrier]
            energy = case.energy_mwh_per_mw
            market = case.market_revenue_eur_per_mw
            thg = case.displaced_thg_t_co2e_per_mw
            full_min = stats.full_min_ct_kwh * 10.0 * energy
            full_max = stats.full_max_ct_kwh * 10.0 * energy
            writer.writerow(
                {
                    "case_id": case.case_id,
                    "carrier": case.carrier,
                    "label": case.label,
                    "climate_price_to_match_market_plus_premium_min_eur_t": (
                        stats.premium_min_ct_kwh * 10.0 * energy / thg
                    ),
                    "climate_price_to_match_market_plus_premium_mean_eur_t": (
                        stats.premium_mean_ct_kwh * 10.0 * energy / thg
                    ),
                    "climate_price_to_match_market_plus_premium_max_eur_t": (
                        stats.premium_max_ct_kwh * 10.0 * energy / thg
                    ),
                    "climate_price_to_match_full_min_eur_t": max(
                        0.0, (full_min - market) / thg
                    ),
                    "climate_price_to_match_full_max_eur_t": max(
                        0.0, (full_max - market) / thg
                    ),
                }
            )


def write_fossil_emissions_csv(path: Path) -> None:
    """Dokumentiert direkte Emissionen, Vorketten-Aufschlag und Gesamtansatz."""
    rows = []
    specs = {
        "lignite": (
            "Braunkohle",
            "UNECE-Lebenszyklusmittel 1,093 t/MWh minus direkter UBA-Kraftwerkswert",
            UNECE_LCA_URL,
        ),
        "hard_coal": (
            "Steinkohle",
            "UBA: höchster regulärer Lieferlandwert 11,4 g CO2e/MJ (Russland), auf Strom umgerechnet",
            UBA_UPSTREAM_URL,
        ),
        "gas": (
            "Erdgas",
            "UBA: US-LNG inklusive Verteilung 22,4 g CO2e/MJ, auf Strom umgerechnet",
            UBA_UPSTREAM_URL,
        ),
        "other_conventional": (
            "Sonstige Konventionelle",
            "JEC WTT v5: Ölproduktbereitstellung 18,9 g CO2e/MJ als konservativer Proxy",
            JEC_WTT_URL,
        ),
    }
    for key, (label, method, source_url) in specs.items():
        rows.append({
            "energietraeger": label,
            "direct_t_co2e_mwh": DIRECT_FOSSIL_EMISSIONS_T_CO2E_MWH[key],
            "upstream_surcharge_t_co2e_mwh": UPSTREAM_SURCHARGE_T_CO2E_MWH[key],
            "total_t_co2e_mwh": FOSSIL_EMISSIONS_T_CO2E_MWH[key],
            "method": method,
            "source_url": source_url,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_methodology(
    path: Path,
    smard_path: Path,
    scenario_path: Path,
    eeg_path: Path,
    year: int,
    eeg_year: str,
    site_id: str,
    cases: list[Case],
    eeg: dict[str, EegStats],
) -> None:
    strong = [
        f"{case.label} (Faktor {case.normalization_factor:.2f})"
        for case in cases
        if case.normalization_factor is not None
        and "STARKE NORMIERUNG" in case.validation_status
    ]
    clear = [
        f"{case.label} (Faktor {case.normalization_factor:.2f})"
        for case in cases
        if case.normalization_factor is not None
        and "DEUTLICHE NORMIERUNG" in case.validation_status
    ]
    factors = FOSSIL_EMISSIONS_T_CO2E_MWH
    negative_premium_categories = sum(
        stats.excluded_premium_categories for stats in eeg.values()
    )
    lines = [
        "# Methodik und wissenschaftliche Einordnung der Artikelgrafiken",
        "",
        f"Skriptversion: {VERSION}",
        f"SMARD- und Marktjahr: {year}",
        f"EEG-Bestandsjahr: {eeg_year}",
        f"Szenario-Standort: {site_id}",
        "",
        "## Eingaben",
        "",
        f"- SMARD-SQLite: `{smard_path}`",
        f"- Szenario-SQLite: `{scenario_path}`",
        f"- EEG-SQLite: `{eeg_path}`",
        "",
        "## Einheitlicher Rechenkern",
        "",
        "Für jeden Fall wird eine stündliche Einspeisereihe je MW gebildet. "
        "Der Markterlös ist die Summe aus Stundenenergie und gleichzeitigem "
        "deutschem Day-ahead-Preis. Die Klimaleistung ist die Summe aus "
        "Stundenenergie und dem gleichzeitig erzeugungsgewichteten fossilen "
        "SMARD-Mix.",
        "",
        "Direkte kraftwerksseitige Emissionen und Vorketten werden getrennt "
        "angesetzt. Die Vorkette erscheint ausdrücklich als Aufschlag je MWh "
        "Strom; erst beide Bestandteile zusammen gehen in den stündlichen "
        "fossilen Mix ein.",
        "",
        "| Energieträger | direkt t CO₂e/MWh | Vorketten-Aufschlag t CO₂e/MWh | gesamt t CO₂e/MWh |",
        "|---|---:|---:|---:|",
        *[
            f"| {label} | {de(DIRECT_FOSSIL_EMISSIONS_T_CO2E_MWH[key], 3)} | "
            f"{de(UPSTREAM_SURCHARGE_T_CO2E_MWH[key], 3)} | {de(factors[key], 3)} |"
            for key, label in (
                ("lignite", "Braunkohle"),
                ("hard_coal", "Steinkohle"),
                ("gas", "Erdgas"),
                ("other_conventional", "Sonstige Konventionelle"),
            )
        ],
        "",
        "Die Aufschläge sind konservative obere, aber regulär dokumentierte "
        "Ansätze: UNECE-Lebenszyklusmittel für Braunkohle; höchster regulärer "
        "UBA-Lieferlandwert für Steinkohle; US-LNG einschließlich Verteilung "
        "für Erdgas; JEC-WTT-Ölproduktbereitstellung als Proxy für Sonstige. "
        "Die vom UBA selbst als hoch unsicher bezeichnete US-LNG-Sensitivität "
        "von 30,0 g CO₂e/MJ wird nicht als Hauptwert verwendet. Sonstige "
        "Konventionelle bleiben wegen der heterogenen SMARD-Sammelkategorie "
        "die größte Unsicherheit.",
        "",
        "Die Klimaleistung ist definitionsgemäß eine rechnerische fossile "
        "Brutto-Verdrängung. Herstellungs-, Bau- und Rückbauemissionen werden "
        "nicht pauschal abgezogen; sie gehören in eine getrennte, projektspezifische "
        "Anlagenbilanz. Die Kennzahl ist kein kausaler Grenzkraftwerksnachweis.",
        "",
        "## Neu und Bestand",
        "",
        "Die literaturnormierten PV- und Onshore-Windfälle sind als `Neu` "
        "gekennzeichnet. Der jeweils helle Referenzfall ist der beobachtete "
        f"Bestand {year}: reale SMARD-Netzeinspeisung geteilt durch eine zwischen "
        f"den UBA/AGEE-Stat-Jahresendbeständen {year-1}/{year} interpolierte "
        "Bestandsleistung. Er wird weder auf Bruttostromerzeugung hochgerechnet "
        "noch auf einen Literaturertrag normiert. Bei PV ist dies Netzeinspeisung "
        "je gesamtem Bestands-MWp; Eigenverbrauch ist nicht enthalten. Biomasse "
        "und Wasser sind wegen unterschiedlicher SMARD-Datenabdeckung nur "
        "eingeschränkte Bestandsreferenzen.",
        "",
        "## PV- und Wind-Literaturfälle",
        "",
        "Die Stundenform stammt aus dem Wetter- und Anlagenmodell am Standort "
        "Kassel. Die Jahressumme wird auf dokumentierte Erträge normiert: PVGIS "
        "5.3/SARAH3 für PV und Deutsche WindGuard 2026, Region Mitte, für Wind. "
        "Das sind Szenarien für Tendenzen und Größenordnungen, keine "
        "projektspezifischen Ertragsgutachten. Rohwerte und Profilprüfungen stehen "
        "in `artikelgrafik_faelle.csv`.",
        "",
        "## EEG-Spannen",
        "",
        "Es gibt keine Mengenschwelle mehr. Aus jeder Veräußerungsform werden "
        "alle über das Gesamtjahr und die Vergütungskategorie aggregierten Sätze "
        "ausgewertet. Nullwerte bleiben enthalten. Für die sichtbare Min-Max-Spanne "
        "werden nichtnegative Kategoriesätze verwendet. Rechnerisch negative "
        "Marktprämien-Abrechnungszeilen werden nicht als negative gesetzliche "
        "Tarifuntergrenze gezeichnet: Anlage 1 EEG setzt die Marktprämie bei null "
        "fest; Netztransparenz beschreibt negative Bewegungszeilen als rechnerische "
        "Werte, die über zusätzliche Ausgleichskategorien ausgeglichen werden. "
        f"In den fünf dargestellten Energieträgern betrifft dies {negative_premium_categories} "
        "Jahreskategorien. Sie bleiben vollständig in `eeg_bandbreiten.csv` und im "
        "mengengewichteten Gesamtmittel erhalten.",
        "",
        "## Vergleich in Grafik 2",
        "",
        "Je Energieträger stehen zuerst drei Bestandsbalken: EEG-Vollvergütung, "
        "stündlicher Marktwert plus beobachtete Marktprämie und Bestands-Marktwert "
        "plus Klimaleistung in Schritten von 50, 100 und 150 €/t. Danach folgen "
        "die ausgewählten Neufälle als ihr jeweiliger stündlicher Profilmarktwert "
        "plus Klimaleistung. In den beiden EEG-Balken markiert die farbige "
        "Querlinie den mengengewichteten Mittelwert; seitliche Vergleichsmarken "
        "werden nicht verwendet.",
        "",
        "## Wissenschaftliche Belastbarkeit",
        "",
        "- Geeignet: reproduzierbarer Szenariovergleich und Größenordnungsprüfung.",
        "- Nicht geeignet: exakter Grenzkraftwerksnachweis oder projektspezifische "
        "Ertrags- und Erlösgarantie.",
        "- EEG 2024: heterogene historische Bestandskohorten, keine einheitliche "
        "Neubauvergütung.",
        "- Biomasse: nur das Einspeiseprofil wird gegen den fossilen Mix bewertet; "
        "Brennstoff- und KWK-spezifische THG-Bilanzen sind nicht enthalten.",
    ]
    if clear:
        lines.append("- Deutlich normierte Fälle: " + ", ".join(clear) + ".")
    if strong:
        lines.append("- Stark normierte Fälle: " + ", ".join(strong) + ".")
    lines.extend([
        "",
        "## Verifikationswerte der Fälle",
        "",
        "| Fall | Typ | Ziel MWh/MW | Rohwert | Kalibrierung | Faktor | Korrelation | Monatsfehler pp | Marktwert Δ | THG Δ | Status |",
        "|---|---|---:|---:|---|---:|---:|---:|---:|---:|---|",
    ])
    for case in cases:
        corr = "–" if case.smard_hourly_correlation is None else f"{case.smard_hourly_correlation:.3f}"
        mae = "–" if case.smard_monthly_share_mae_pp is None else f"{case.smard_monthly_share_mae_pp:.3f}"
        raw = case.raw_energy_mwh_per_mw if case.raw_energy_mwh_per_mw is not None else case.energy_mwh_per_mw
        factor = case.normalization_factor if case.normalization_factor is not None else 1.0
        market_delta = "–" if case.market_value_profile_delta_pct is None else f"{case.market_value_profile_delta_pct:+.1f} %"
        thg_delta = "–" if case.thg_profile_delta_pct is None else f"{case.thg_profile_delta_pct:+.1f} %"
        case_type = f"Bestand {year}" if case.is_reference else "Neu"
        lines.append(
            f"| {case.label} | {case_type} | {case.energy_mwh_per_mw:.1f} | {raw:.1f} | "
            f"{case.normalization_mode} | {factor:.3f} | {corr} | {mae} | "
            f"{market_delta} | {thg_delta} | {case.validation_status} |"
        )
    lines.extend([
        "",
        "## Quellen",
        "",
        f"- UBA/AGEE-Stat Kapazitäten: {UBA_CAPACITY_URL}",
        f"- UBA direkte fossile Emissionsansätze: {UBA_EMISSIONS_URL}",
        f"- UBA Vorketten Erdgas und Steinkohle: {UBA_UPSTREAM_URL}",
        f"- UNECE Lebenszykluswert Braunkohle: {UNECE_LCA_URL}",
        f"- JEC WTT v5 Ölproduktbereitstellung: {JEC_WTT_URL}",
        f"- SMARD Marktdaten: {SMARD_URL}",
        f"- Netztransparenz EEG-Bewegungsdaten: {NETZTRANSPARENZ_EEG_URL}",
        f"- EEG Anlage 1, Marktprämie mindestens null: {EEG_MARKET_PREMIUM_LAW_URL}",
        "- PVGIS: https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/using-pvgis-5/api-non-interactive-service_en",
        "- Deutsche WindGuard 2026: https://www.windguard.de/veroeffentlichungen.html?file=files%2Fcto_layout%2Fimg%2Funternehmen%2Fveroeffentlichungen%2F2026%2FVolllaststunden+von+Windenergieanlagen+an+Land.pdf",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_graphic_explanations(
    out: Path, year: int, eeg_year: str, site_id: str, cases: list[Case],
    eeg: dict[str, EegStats],
) -> None:
    factors = FOSSIL_EMISSIONS_T_CO2E_MWH
    pv_url = next((case.source_url for case in cases if case.carrier == "Solar" and not case.is_reference and case.source_url), "")
    wind_url = next((case.source_url for case in cases if case.carrier == "Wind an Land" and not case.is_reference and case.source_url), "")
    graph1 = [
        "# Erklärtext zu Grafik 1 – Jährliche fossile THG-Verdrängung je MW",
        "",
        "## Aussage und Rechenregel",
        "",
        "Die Grafik vergleicht die rechnerische Klimaleistung von einem MW installierter Leistung. Klimaleistung ist hier definitionsgemäß die stündlich zugerechnete fossile Brutto-Verdrängung: Die Einspeisung jedes Falls wird stundenweise mit dem gleichzeitig veröffentlichten, erzeugungsgewichteten fossilen SMARD-Mix multipliziert und über das Kalenderjahr summiert.",
        "",
        "Die fossilen Ansätze bestehen aus direkter Kraftwerksemission plus "
        "explizitem Vorketten-Aufschlag. Direkt / Aufschlag / Gesamt in "
        "t CO₂e/MWh: "
        + "; ".join(
            f"{label} {de(DIRECT_FOSSIL_EMISSIONS_T_CO2E_MWH[key], 3)} / "
            f"{de(UPSTREAM_SURCHARGE_T_CO2E_MWH[key], 3)} / {de(factors[key], 3)}"
            for key, label in (
                ("lignite", "Braunkohle"),
                ("hard_coal", "Steinkohle"),
                ("gas", "Erdgas"),
                ("other_conventional", "Sonstige"),
            )
        )
        + ". Die Vorkettenwerte sind konservative obere, regulär dokumentierte "
        "Ansätze; die heterogene Sammelkategorie Sonstige bleibt ein Proxy.",
        "",
        "## Bestand und Neufälle",
        "",
        f"Der jeweils links stehende helle Balken `Bestand DE {year}` ist ein nationaler Bestandsdurchschnitt: reale SMARD-Netzeinspeisung geteilt durch die stündlich interpolierte installierte Bestandsleistung. Es erfolgt keine Ertragsnormierung. Bei PV ist Eigenverbrauch deshalb nicht enthalten; bei Biomasse und Wasser ist die SMARD-Datenabdeckung eingeschränkt.",
        "",
        f"Die als `Neu` bezeichneten PV- und Onshore-Windfälle verwenden eine modellierte Stundenform am Standort `{site_id}`. Ihre Jahressummen sind auf Literaturwerte normiert: PVGIS 5.3/SARAH3 für Photovoltaik und Deutsche WindGuard 2026, Region Mitte, für Wind an Land. Gezeigt werden Süd 30°, Süd 60° und Ost–West 15°. Ost–West 30° bleibt vollständig in `artikelgrafik_faelle.csv` dokumentiert, wird aber wegen seiner geringen zusätzlichen Aussage gegenüber Ost–West 15° nicht in den Hauptgrafiken dargestellt.",
        "",
        "Die Kennzahl ist keine vollständige Anlagen-Ökobilanz und kein kausaler Grenzkraftwerksnachweis. Herstellungs-, Bau- und Rückbauemissionen gehören in eine getrennte projektspezifische Anlagenbilanz. Die Grafik verwendet bewusst eine einheitliche, stündlich mit dem fossilen Erzeugungsmix korrelierende Vergütungsregel.",
        "",
        "## Lizenz",
        "",
        f"Grafik © {AUTHOR_NAME} {COPYRIGHT_YEAR}. Freigegeben unter `{LICENSE_LABEL}`: freie Weitergabe und Bearbeitung, auch kommerziell, bei angemessener Namensnennung, Link auf die Lizenz und Kennzeichnung von Änderungen. Lizenz: {LICENSE_URL}",
        "",
        "## Quellen",
        f"- SMARD-Stundendaten und Erzeugungsreihen: {SMARD_URL}",
        f"- UBA/AGEE-Stat installierte Leistungen: {UBA_CAPACITY_URL}",
        f"- UBA direkte fossile Emissionsansätze: {UBA_EMISSIONS_URL}",
        f"- UBA Vorketten Erdgas und Steinkohle: {UBA_UPSTREAM_URL}",
        f"- UNECE Lebenszykluswert Braunkohle: {UNECE_LCA_URL}",
        f"- JEC WTT v5 Ölproduktbereitstellung: {JEC_WTT_URL}",
        f"- PVGIS 5.3/SARAH3 für PV-Jahreserträge: {pv_url}",
        f"- Deutsche WindGuard 2026 für Wind-Jahreserträge Region Mitte: {wind_url}",
        "- Detailwerte und Prüfstatus: `artikelgrafik_faelle.csv` und `METHODIK_ARTIKELGRAFIKEN.md`",
    ]

    negative_count = sum(x.excluded_premium_categories for x in eeg.values())
    negative_quantity = sum(x.negative_premium_quantity_kwh for x in eeg.values())
    graph2 = [
        "# Erklärtext zu Grafik 2 – EEG-Förderung, Markt und Klimaleistung",
        "",
        "## Aufbau",
        "",
        "Für jeden Energieträger stehen zuerst drei Bestandsvergleiche: ein Balken für die EEG-Vollvergütung, ein Balken für den exakten stündlichen Bestands-Marktwert plus beobachtete Marktprämie und ein Balken für den Bestands-Marktwert plus Klimaleistung. Danach folgen – soweit vorhanden – ausgewählte Neufälle als stündlicher Profilmarktwert plus Klimaleistung. Die drei helleren Klimaleistungsblöcke entsprechen jeweils weiteren 50 €/t CO₂e; ihre Oberkanten zeigen 50, 100 und 150 €/t.",
        "",
        "Vollvergütung und Marktprämie werden nur einmal je Energieträger aus dem beobachteten Bestand dargestellt. Die Balken zeigen Minimum bis Maximum der über das Gesamtjahr und die jeweilige Vergütungskategorie aggregierten Sätze; die farbige Querlinie markiert den mengengewichteten Mittelwert. Die Spannen beschreiben historische EEG-Bestandskohorten und keine aktuelle einheitliche Neubauvergütung.",
        "",
        "## Negative Marktprämienkategorien",
        "",
        f"Es gibt keine Mindestmengenschwelle. Nichtnegative Jahreskategorien einschließlich Nullwerten bestimmen die sichtbare Tarifspanne. Rechnerisch negative Marktprämienkategorien werden nicht als negative gesetzliche Tarifuntergrenze gezeichnet, weil die Marktprämie nach EEG rechnerisch mindestens null beträgt und negative Netztransparenz-Zeilen Abrechnungs- beziehungsweise Ausgleichseffekte abbilden. Sie werden jedoch nicht aus der Datenauswertung gelöscht: In den fünf dargestellten Energieträgern betrifft dies {negative_count} Jahreskategorien mit zusammen {de(negative_quantity / 1e9, 3)} TWh. Ihre Zahlungen bleiben im mengengewichteten Gesamtmittel und vollständig in `eeg_bandbreiten.csv` dokumentiert.",
        "",
        "Markterlöse werden für jeden dargestellten Fall als exakte Summe aus stündlicher Einspeisung und deutschem Day-ahead-Preis berechnet. Vermarktungskosten, Ausgleichsenergie und individuelle PPA-Bedingungen sind nicht enthalten.",
        "",
        "## Auswahl der PV-Fälle",
        "",
        "Gezeigt werden Süd 30° als ertragsstarker Referenzfall, Süd 60° als winterbetontere Ausrichtung und Ost–West 15° als breiteres Tagesprofil. Ost–West 30° wird weiter berechnet und in den CSV-Dateien ausgegeben, aber wegen der geringen zusätzlichen Aussage gegenüber Ost–West 15° nicht geplottet.",
        "",
        "## Lizenz",
        "",
        f"Grafik © {AUTHOR_NAME} {COPYRIGHT_YEAR}. Freigegeben unter `{LICENSE_LABEL}`: freie Weitergabe und Bearbeitung, auch kommerziell, bei angemessener Namensnennung, Link auf die Lizenz und Kennzeichnung von Änderungen. Lizenz: {LICENSE_URL}",
        "",
        "## Quellen",
        f"- Netztransparenz EEG-Bewegungsdaten: {NETZTRANSPARENZ_EEG_URL}",
        f"- EEG Anlage 1 zur Marktprämie und Null-Untergrenze: {EEG_MARKET_PREMIUM_LAW_URL}",
        f"- SMARD-Day-ahead-Preis und Erzeugungsreihen: {SMARD_URL}",
        "- Klimaleistungswerte und Profilprüfung: `artikelgrafik_faelle.csv`",
        "- EEG-Kategorien einschließlich negativer Abrechnungszeilen: `eeg_bandbreiten.csv`",
        "- Fallbezogene Schwellenpreise: `vergleichsschwellen.csv`",
    ]
    (out / "01_ERKLAERTEXT_THG_VERDRAENGUNG.md").write_text(
        "\n".join(graph1) + "\n", encoding="utf-8"
    )
    (out / "02_ERKLAERTEXT_EEG_MARKT_KLIMALEISTUNG.md").write_text(
        "\n".join(graph2) + "\n", encoding="utf-8"
    )


def run(args: argparse.Namespace) -> None:
    print(f"SMARD wird geprüft: {args.smard_db}")
    smard = load_smard(args.smard_db, args.year)
    print(f"SMARD {args.year}: {len(smard.timestamp_ms)} vollständige Stunden")
    references = build_reference_cases(smard, args.year)

    print(f"Szenarien werden geprüft: {args.scenario_db}")
    scenarios, site_id = load_scenario_cases(
        args.scenario_db, smard, args.year, args.site_id
    )
    cases = ordered_cases(references, scenarios)
    print(f"Szenarien: {len(scenarios)}; Referenzen: {len(references)}")

    print(f"EEG-Bandbreiten werden geprüft: {args.eeg_db}")
    eeg, eeg_year = load_eeg_stats(args.eeg_db)
    if eeg_year.isdigit() and int(eeg_year) != args.year:
        raise RuntimeError(
            f"Jahreskonflikt: SMARD und Szenarien werden für {args.year} "
            f"ausgewertet, die EEG-Datenbank enthält aber {eeg_year}. "
            "Für die Artikelgrafiken müssen alle drei Datenquellen dasselbe "
            "Auswertungsjahr verwenden."
        )
    args.out.mkdir(parents=True, exist_ok=True)

    old_mpl_config = os.environ.get("MPLCONFIGDIR")
    with tempfile.TemporaryDirectory(prefix="artikelgrafiken_mpl_") as mpl_tmp:
        os.environ["MPLCONFIGDIR"] = mpl_tmp
        try:
            plot_climate(args.out, cases, args.year)
            plot_revenue(args.out, cases, eeg, args.year, eeg_year)
        finally:
            if old_mpl_config is None:
                os.environ.pop("MPLCONFIGDIR", None)
            else:
                os.environ["MPLCONFIGDIR"] = old_mpl_config

    write_fossil_emissions_csv(args.out / "fossile_emissionsansaetze.csv")
    write_cases_csv(args.out / "artikelgrafik_faelle.csv", cases, args.year, site_id)
    write_eeg_csv(args.out / "eeg_bandbreiten.csv", eeg, eeg_year)
    write_thresholds_csv(args.out / "vergleichsschwellen.csv", cases, eeg)
    write_methodology(
        args.out / "METHODIK_ARTIKELGRAFIKEN.md",
        args.smard_db, args.scenario_db, args.eeg_db, args.year, eeg_year,
        site_id, cases, eeg,
    )
    write_graphic_explanations(args.out, args.year, eeg_year, site_id, cases, eeg)
    print("")
    print("Fertig.")
    print(f"  Grafik 1: {args.out / '01_thg_verdraengung_pro_fall.svg'}")
    print(f"  Erklärtext 1: {args.out / '01_ERKLAERTEXT_THG_VERDRAENGUNG.md'}")
    print(f"  Grafik 2: {args.out / '02_eeg_markt_und_klimaleistung.svg'}")
    print(f"  Erklärtext 2: {args.out / '02_ERKLAERTEXT_EEG_MARKT_KLIMALEISTUNG.md'}")
    print(f"  Daten und Methodik: {args.out}")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Erzeugt zwei Artikelgrafiken aus SMARD-, Szenario- und "
            "Netztransparenz-EEG-Datenbanken."
        )
    )
    parser.add_argument(
        "--smard-db",
        type=Path,
        default=SCRIPT_DIR / "smard_stundendaten_2021_2025.sqlite",
    )
    parser.add_argument(
        "--scenario-db",
        type=Path,
        default=SCRIPT_DIR / "wetterdaten_szenarien.sqlite",
    )
    parser.add_argument(
        "--eeg-db",
        type=Path,
        default=SCRIPT_DIR / "netztransparenz_eeg.sqlite",
    )
    parser.add_argument(
        "--out", type=Path, default=SCRIPT_DIR / "artikelgrafiken"
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2024,
        help=(
            "gemeinsames Auswertungsjahr für SMARD, Wetterszenarien und "
            "EEG-Bestandsdaten; Standard: 2024"
        ),
    )
    parser.add_argument(
        "--site-id",
        default=None,
        help="nur nötig, wenn die Szenariendatenbank mehrere Standorte enthält",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        run(args)
    except (RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
