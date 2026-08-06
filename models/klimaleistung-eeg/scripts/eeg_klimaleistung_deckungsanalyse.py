#!/usr/bin/env python3
# Copyright (c) 2026 Sebastian Putzke
# SPDX-License-Identifier: Apache-2.0
"""Summen- und Deckungsanalyse zu EEG-Zahlungen und Klimaleistung.

Das Skript verbindet:

* Netztransparenz-EEG-Jahresabrechnung,
* stündliche SMARD-Erzeugung und Day-ahead-Preise,
* die Bestandsreferenzen und fossilen Faktoren des aktuellen
  ``artikelgrafiken_eeg_klimaleistung.py``.

Es erzeugt eine menschenlesbare ``.res``-Datei mit Ergebnissen, Quellen,
Methodik, Bilanzgrenzen und Unsicherheiten. Es erzeugt keine Grafik und lädt
keine Daten aus dem Internet.

Beispiel:

    python eeg_klimaleistung_deckungsanalyse.py \\
      --smard-db smard_stundendaten_2021_2025.sqlite \\
      --eeg-db netztransparenz_eeg.sqlite \\
      --core-script artikelgrafiken_eeg_klimaleistung.py \\
      --year 2024

Primäre Auswertungslogik:

* Einspeisevergütung: Der alternative Betreibererlös besteht aus dem
  energieträgerspezifischen Bestands-Marktwert plus Klimaleistung.
* Marktprämie: Der Marktwert ist bereits Betreibererlös; Klimaleistung wird
  deshalb nur mit der positiven Prämienzahlung verglichen.
* Zahlungen und Mengen werden zunächst über das Gesamtjahr je Energieträger,
  Veräußerungsform und Vergütungskategorie aggregiert.
* Kategorien mit nichtpositiver Jahreszahlung werden nicht als zu ersetzende
  positive Förderung behandelt, aber separat protokolliert.
* Die nominale Restförderung verwendet dieselbe konservative Jahreskennung
  wie die vorhandene Netztransparenz-Grafik: Inbetriebnahmejahr aus den letzten
  zwei Ziffern des Kategoriecodes und reguläre Laufzeit von 20 Jahren.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

VERSION = "1.1.0"
DEFAULT_CLIMATE_PRICES = (50.0, 100.0, 150.0)
DEFAULT_PRIVATE_SHARES = (0.25, 0.50, 1.00)
MODELED_SALE_FORMS = {"1": "Einspeisevergütung", "2": "Marktprämie"}
MODELED_CARRIERS = {
    "1": "Wasser",
    "5": "Biomasse",
    "7": "Wind an Land",
    "8": "Wind auf See",
    "9": "Solar",
}
CARRIER_ORDER = ["Solar", "Wind an Land", "Wind auf See", "Biomasse", "Wasser"]


@dataclass(frozen=True)
class Category:
    carrier_code: str
    carrier: str
    sale_form: str
    category: str
    quantity_kwh: float
    payment_eur: float


@dataclass(frozen=True)
class Reference:
    carrier: str
    energy_mwh_per_mw: float
    market_value_eur_mwh: float
    climate_t_mwh: float


@dataclass
class Aggregate:
    payment_eur: float = 0.0
    quantity_kwh: float = 0.0
    market_eur: float = 0.0
    climate_eur: float = 0.0
    operator_payment_covered_eur: float = 0.0
    support_requirement_eur: float = 0.0
    climate_support_relief_eur: float = 0.0
    remaining_payment_eur: float = 0.0
    remaining_support_eur: float = 0.0
    remaining_relief_eur: float = 0.0


def de(value: float, digits: int = 2) -> str:
    """Deutsche Zahlendarstellung."""
    return f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(value: float, digits: int = 1) -> str:
    return f"{de(value * 100.0, digits)} %"


def parse_floats(text: str, *, lower: float | None = None, upper: float | None = None) -> tuple[float, ...]:
    values: list[float] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        value = float(token)
        if not math.isfinite(value):
            raise ValueError(f"Nichtendlicher Zahlenwert: {token}")
        if lower is not None and value < lower:
            raise ValueError(f"Wert {value} liegt unter {lower}")
        if upper is not None and value > upper:
            raise ValueError(f"Wert {value} liegt über {upper}")
        values.append(value)
    if not values:
        raise ValueError("Keine Zahlenwerte angegeben")
    return tuple(sorted(set(values)))


def load_core(path: Path):
    if not path.is_file():
        raise RuntimeError(f"Artikelgrafik-Kernskript fehlt: {path}")
    spec = importlib.util.spec_from_file_location("artikelgrafik_core", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kernskript kann nicht geladen werden: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    required = {
        "load_smard",
        "build_reference_cases",
        "DIRECT_FOSSIL_EMISSIONS_T_CO2E_MWH",
        "UPSTREAM_SURCHARGE_T_CO2E_MWH",
        "FOSSIL_EMISSIONS_T_CO2E_MWH",
        "SMARD_URL",
        "NETZTRANSPARENZ_EEG_URL",
        "UBA_CAPACITY_URL",
        "UBA_EMISSIONS_URL",
        "UBA_UPSTREAM_URL",
        "UNECE_LCA_URL",
        "JEC_WTT_URL",
        "VERSION",
    }
    missing = sorted(name for name in required if not hasattr(module, name))
    if missing:
        raise RuntimeError("Im Kernskript fehlen: " + ", ".join(missing))
    return module


def sqlite_integrity(path: Path, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{label} fehlt: {path}")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    if result != "ok":
        raise RuntimeError(f"{label} beschädigt: {result}")


def metadata(con: sqlite3.Connection) -> dict[str, str]:
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "metadata" not in tables:
        return {}
    return {str(key): str(value) for key, value in con.execute("SELECT key,value FROM metadata")}


def load_categories(path: Path, year: int) -> tuple[list[Category], dict[str, float | str]]:
    sqlite_integrity(path, "EEG-Datenbank")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "eeg_data" not in tables:
            raise RuntimeError("EEG-Datenbank enthält keine Tabelle 'eeg_data'.")
        meta = metadata(con)
        db_year = meta.get("year", "unbekannt")
        if db_year.isdigit() and int(db_year) != year:
            raise RuntimeError(f"EEG-Datenbank enthält {db_year}, angefordert ist {year}.")

        raw = con.execute(
            "SELECT COALESCE(SUM(payment_eur),0),"
            "COALESCE(SUM(CASE WHEN payment_eur>0 THEN payment_eur ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN payment_eur<0 THEN payment_eur ELSE 0 END),0),"
            "COALESCE(SUM(quantity_kwh),0) FROM eeg_data"
        ).fetchone()
        rows = con.execute(
            "SELECT CAST(carrier AS TEXT),CAST(sale_form AS TEXT),category,"
            "SUM(quantity_kwh),SUM(payment_eur) FROM eeg_data "
            "WHERE quantity_kwh>0 AND payment_eur IS NOT NULL "
            "GROUP BY 1,2,3 HAVING SUM(quantity_kwh)>0"
        ).fetchall()
        legacy_rows = con.execute(
            "SELECT category,payment_eur FROM eeg_data "
            "WHERE quantity_kwh>0 AND payment_eur>0 AND payment_ct_kwh>=0"
        ).fetchall()
    finally:
        con.close()

    categories: list[Category] = []
    for carrier_code, sale_form, category, quantity, payment in rows:
        categories.append(
            Category(
                carrier_code=str(carrier_code),
                carrier=MODELED_CARRIERS.get(str(carrier_code), f"Code {carrier_code}"),
                sale_form=str(sale_form),
                category=str(category or ""),
                quantity_kwh=float(quantity),
                payment_eur=float(payment),
            )
        )
    annual_net = sum(row.payment_eur for row in categories)
    annual_positive = sum(max(0.0, row.payment_eur) for row in categories)
    annual_negative = sum(min(0.0, row.payment_eur) for row in categories)
    legacy_rest_payment = 0.0
    legacy_covered_payment = 0.0
    legacy_total_positive = sum(float(payment) for _category, payment in legacy_rows)
    for category, payment in legacy_rows:
        text = str(category or "").strip()
        if len(text) < 2 or not text[-2:].isdigit():
            continue
        commissioning_year = 2000 + int(text[-2:])
        if not 2000 <= commissioning_year <= year:
            continue
        legacy_covered_payment += float(payment)
        legacy_rest_payment += float(payment) * max(0, commissioning_year + 20 - year)

    info: dict[str, float | str] = {
        "database_year": db_year,
        "database_source": meta.get("source", "nicht dokumentiert"),
        "raw_net_payment_eur": float(raw[0]),
        "raw_positive_payment_eur": float(raw[1]),
        "raw_negative_payment_eur": float(raw[2]),
        "raw_quantity_kwh": float(raw[3]),
        "annual_category_net_payment_eur": annual_net,
        "annual_category_positive_payment_eur": annual_positive,
        "annual_category_negative_payment_eur": annual_negative,
        "annual_category_quantity_kwh": sum(row.quantity_kwh for row in categories),
        "annual_category_count": float(len(categories)),
        "legacy_positive_payment_eur": legacy_total_positive,
        "legacy_year_covered_payment_eur": legacy_covered_payment,
        "legacy_nominal_rest_payment_eur": legacy_rest_payment,
    }
    return categories, info


def references_from_core(core, smard_path: Path, year: int) -> dict[str, Reference]:
    smard = core.load_smard(smard_path, year)
    cases = core.build_reference_cases(smard, year)
    result: dict[str, Reference] = {}
    for case in cases:
        if case.energy_mwh_per_mw <= 0:
            raise RuntimeError(f"Nichtpositiver Referenzertrag für {case.carrier}")
        result[case.carrier] = Reference(
            carrier=case.carrier,
            energy_mwh_per_mw=float(case.energy_mwh_per_mw),
            market_value_eur_mwh=float(case.market_revenue_eur_per_mw / case.energy_mwh_per_mw),
            climate_t_mwh=float(case.displaced_thg_t_co2e_per_mwh),
        )
    missing = sorted(set(CARRIER_ORDER) - set(result))
    if missing:
        raise RuntimeError("Bestandsreferenzen fehlen: " + ", ".join(missing))
    return result


def inferred_commissioning_year(category: str, base_year: int) -> int | None:
    """Konservative Jahreskennung analog zur vorhandenen Restförderungsgrafik."""
    text = str(category or "").strip()
    if len(text) < 2 or not text[-2:].isdigit():
        return None
    year = 2000 + int(text[-2:])
    return year if 2000 <= year <= base_year else None


def remaining_years(category: str, base_year: int) -> int | None:
    year = inferred_commissioning_year(category, base_year)
    if year is None:
        return None
    return max(0, year + 20 - base_year)


def modeled_scope(categories: Iterable[Category]) -> list[Category]:
    return [
        row for row in categories
        if row.carrier_code in MODELED_CARRIERS and row.sale_form in MODELED_SALE_FORMS
    ]


def category_values(row: Category, reference: Reference, climate_price: float, private_share: float = 1.0):
    quantity_mwh = row.quantity_kwh / 1000.0
    market = quantity_mwh * reference.market_value_eur_mwh
    climate = quantity_mwh * reference.climate_t_mwh * climate_price * private_share
    positive_payment = max(0.0, row.payment_eur)

    if row.sale_form == "1":
        operator_covered = min(positive_payment, max(0.0, market + climate))
        support_requirement = max(0.0, positive_payment - market)
        climate_relief = min(climate, support_requirement)
    elif row.sale_form == "2":
        # Der Marktwert ist bereits Betreibererlös und nicht Teil der EEG-Prämie.
        operator_covered = min(positive_payment, max(0.0, climate))
        support_requirement = positive_payment
        climate_relief = min(climate, support_requirement)
    else:  # durch modeled_scope ausgeschlossen
        raise RuntimeError(f"Nicht modellierte Veräußerungsform: {row.sale_form}")
    return positive_payment, market, climate, operator_covered, support_requirement, climate_relief


def aggregate_for_price(
    categories: Iterable[Category],
    references: dict[str, Reference],
    climate_price: float,
    private_share: float = 1.0,
    base_year: int = 2024,
) -> tuple[Aggregate, dict[str, Aggregate]]:
    total = Aggregate()
    by_carrier: dict[str, Aggregate] = defaultdict(Aggregate)
    for row in categories:
        if row.payment_eur <= 0:
            continue
        reference = references[row.carrier]
        payment, market, climate, covered, support, relief = category_values(
            row, reference, climate_price, private_share
        )
        years = remaining_years(row.category, base_year)
        for target in (total, by_carrier[row.carrier]):
            target.payment_eur += payment
            target.quantity_kwh += row.quantity_kwh
            target.market_eur += market if row.sale_form == "1" else 0.0
            target.climate_eur += climate
            target.operator_payment_covered_eur += covered
            target.support_requirement_eur += support
            target.climate_support_relief_eur += relief
            if years is not None:
                target.remaining_payment_eur += payment * years
                target.remaining_support_eur += support * years
                target.remaining_relief_eur += relief * years
    return total, dict(by_carrier)


def scope_summary(categories: list[Category], references: dict[str, Reference], base_year: int):
    scope = modeled_scope(categories)
    positive = [row for row in scope if row.payment_eur > 0]
    negative = [row for row in scope if row.payment_eur < 0]
    zero = [row for row in scope if abs(row.payment_eur) < 1e-12]

    base_payment = sum(row.payment_eur for row in positive)
    base_quantity = sum(row.quantity_kwh for row in positive)
    base_support = 0.0
    full_market = 0.0
    identified_payment = 0.0
    identified_support = 0.0
    nominal_payment = 0.0
    nominal_support = 0.0
    for row in positive:
        ref = references[row.carrier]
        quantity_mwh = row.quantity_kwh / 1000.0
        market = quantity_mwh * ref.market_value_eur_mwh
        support = max(0.0, row.payment_eur - market) if row.sale_form == "1" else row.payment_eur
        base_support += support
        if row.sale_form == "1":
            full_market += market
        years = remaining_years(row.category, base_year)
        if years is not None:
            identified_payment += row.payment_eur
            identified_support += support
            nominal_payment += row.payment_eur * years
            nominal_support += support * years
    return {
        "scope": scope,
        "positive": positive,
        "negative": negative,
        "zero": zero,
        "positive_payment_eur": base_payment,
        "positive_quantity_kwh": base_quantity,
        "support_requirement_eur": base_support,
        "full_market_eur": full_market,
        "identified_payment_eur": identified_payment,
        "identified_support_eur": identified_support,
        "nominal_payment_eur": nominal_payment,
        "nominal_support_eur": nominal_support,
    }


def table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    def format_row(row: list[str]) -> str:
        return " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))
    result = [format_row(headers), "-+-".join("-" * width for width in widths)]
    result.extend(format_row(row) for row in rows)
    return result


def build_report(
    *,
    core,
    core_path: Path,
    smard_path: Path,
    eeg_path: Path,
    year: int,
    prices: tuple[float, ...],
    private_shares: tuple[float, ...],
    categories: list[Category],
    db_info: dict[str, float | str],
    references: dict[str, Reference],
) -> str:
    scope = scope_summary(categories, references, year)
    eligible_positive = float(db_info["annual_category_positive_payment_eur"])
    scope_positive = float(scope["positive_payment_eur"])
    support_base = float(scope["support_requirement_eur"])
    nominal_support = float(scope["nominal_support_eur"])

    result_by_price: dict[float, tuple[Aggregate, dict[str, Aggregate]]] = {}
    for price in prices:
        result_by_price[price] = aggregate_for_price(scope["scope"], references, price, 1.0, year)

    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    lines: list[str] = [
        "EEG-/KLIMALEISTUNGS-DECKUNGSANALYSE",
        "RESULTATDATEI (.res)",
        "=" * 78,
        f"Erstellt: {now}",
        f"Skriptversion: {VERSION}",
        f"Artikelgrafik-Kern: Version {getattr(core, 'VERSION', 'unbekannt')} · {core_path}",
        f"Auswertungsjahr: {year}",
        f"SMARD-Datenbank: {smard_path}",
        f"EEG-Datenbank: {eeg_path}",
        "",
        "1. ZENTRALE ERGEBNISSE",
        "-" * 78,
        "",
        "Die folgenden Werte sind reproduzierbare Modellwerte unter den Markt-,",
        f"Erzeugungs-, Emissions- und Vergütungsbedingungen des Jahres {year}.",
        "Sie sind keine garantierte Haushaltsprognose.",
        "",
    ]

    central_rows: list[list[str]] = []
    for price in prices:
        total, _ = result_by_price[price]
        central_rows.append([
            de(price, 0),
            de(total.climate_eur / 1e9, 2),
            de(total.operator_payment_covered_eur / 1e9, 2),
            pct(total.operator_payment_covered_eur / scope_positive),
            de(total.climate_support_relief_eur / 1e9, 2),
            pct(total.climate_support_relief_eur / support_base),
            de((support_base - total.climate_support_relief_eur) / 1e9, 2),
        ])
    lines.extend(table(
        [
            "€/t CO2e",
            "KL-Wert Mrd. €",
            "EEG-Zahlung abgedeckt Mrd. €",
            "Anteil EEG-Zahlung",
            "Förderlücke ersetzt Mrd. €",
            "Anteil Förderlücke",
            "Restförderbedarf Mrd. €",
        ],
        central_rows,
    ))
    lines.extend([
        "",
        "Begriffe:",
        "- KL-Wert: ungekappter monetärer Wert der Klimaleistung auf der positiven",
        "  EEG-Strommenge im Modellumfang.",
        "- EEG-Zahlung abgedeckt: Einspeisevergütung wird durch Bestands-Marktwert",
        "  plus Klimaleistung, Marktprämie durch Klimaleistung allein ersetzt; pro",
        "  Kategorie höchstens bis zur positiven beobachteten EEG-Zahlung.",
        "- Förderlücke ersetzt: zusätzlicher Beitrag der Klimaleistung nach Abzug",
        "  des ohnehin vorhandenen Marktwerts bei Einspeisevergütung. Dieser Wert",
        "  ist die geeignetere Obergrenze für eine mögliche staatliche Entlastung",
        "  bei vollständig privater Abnahme der Klimaleistung.",
        "",
        "2. DATENBASIS UND ANALYSEUMFANG",
        "-" * 78,
        "",
        f"Nettozahlung der vollständigen EEG-Datenbank: {de(float(db_info['raw_net_payment_eur']) / 1e9, 3)} Mrd. €",
        f"Positive Einzelzeilen der Datenbank:          {de(float(db_info['raw_positive_payment_eur']) / 1e9, 3)} Mrd. €",
        f"Negative Einzelzeilen der Datenbank:          {de(float(db_info['raw_negative_payment_eur']) / 1e9, 3)} Mrd. €",
        f"Jährlich aggregierte positive Kategorien:     {de(eligible_positive / 1e9, 3)} Mrd. €",
        f"Modellumfang positive Kategorien:             {de(scope_positive / 1e9, 3)} Mrd. €",
        f"Anteil am aggregierten positiven Bestand:     {pct(scope_positive / eligible_positive, 2)}",
        f"Modellumfang Strommenge:                       {de(float(scope['positive_quantity_kwh']) / 1e9, 3)} TWh",
        f"Negative Kategorien im Modellumfang:           {len(scope['negative'])} Kategorien, {de(sum(row.quantity_kwh for row in scope['negative']) / 1e9, 3)} TWh, {de(sum(row.payment_eur for row in scope['negative']) / 1e6, 2)} Mio. €",
        "",
        "Modelliert werden die fünf Hauptenergieträger Solar, Wind an Land, Wind",
        "auf See, Biomasse und Wasser sowie die Veräußerungsformen 1",
        "(Einspeisevergütung) und 2 (Marktprämie). Andere Energieträger und",
        "Veräußerungsformen werden als außerhalb des Modellumfangs ausgewiesen.",
        "",
        "3. BESTANDSREFERENZEN 2024",
        "-" * 78,
        "",
    ])
    ref_rows = []
    for carrier in CARRIER_ORDER:
        ref = references[carrier]
        ref_rows.append([
            carrier,
            de(ref.energy_mwh_per_mw, 1),
            de(ref.market_value_eur_mwh, 2),
            de(ref.climate_t_mwh, 4),
            de(ref.climate_t_mwh * 50 / 10, 3),
            de(ref.climate_t_mwh * 100 / 10, 3),
            de(ref.climate_t_mwh * 150 / 10, 3),
        ])
    lines.extend(table(
        ["Energieträger", "MWh/MW", "Marktwert €/MWh", "t CO2e/MWh", "ct/kWh @50", "ct/kWh @100", "ct/kWh @150"],
        ref_rows,
    ))

    lines.extend([
        "",
        "4. ERGEBNISSE NACH ENERGIETRÄGER",
        "-" * 78,
    ])
    for price in prices:
        _, by_carrier = result_by_price[price]
        rows = []
        for carrier in CARRIER_ORDER:
            item = by_carrier.get(carrier, Aggregate())
            rows.append([
                carrier,
                de(item.payment_eur / 1e9, 3),
                de(item.operator_payment_covered_eur / 1e9, 3),
                pct(item.operator_payment_covered_eur / item.payment_eur if item.payment_eur else 0.0),
                de(item.support_requirement_eur / 1e9, 3),
                de(item.climate_support_relief_eur / 1e9, 3),
                pct(item.climate_support_relief_eur / item.support_requirement_eur if item.support_requirement_eur else 0.0),
            ])
        lines.extend(["", f"Klimaleistungspreis: {de(price, 0)} €/t CO2e", ""])
        lines.extend(table(
            ["Energieträger", "positive Zahlung Mrd. €", "abgedeckt Mrd. €", "Deckung", "Förderlücke Mrd. €", "KL-Entlastung Mrd. €", "Entlastungsanteil"],
            rows,
        ))

    lines.extend([
        "",
        "5. PRIVATE ABNAHME UND MÖGLICHE STAATLICHE ENTLASTUNG",
        "-" * 78,
        "",
        "Die Tabelle unterstellt, dass der angegebene Anteil der Klimaleistung",
        "gleichmäßig privat abgenommen wird. Die Entlastung wird pro Kategorie auf",
        "die nach Marktwert verbleibende positive Förderlücke begrenzt.",
        "",
    ])
    private_rows: list[list[str]] = []
    for price in prices:
        for share in private_shares:
            total, _ = aggregate_for_price(scope["scope"], references, price, share, year)
            private_rows.append([
                de(price, 0),
                pct(share, 0),
                de(total.climate_support_relief_eur / 1e9, 2),
                pct(total.climate_support_relief_eur / support_base),
                de((support_base - total.climate_support_relief_eur) / 1e9, 2),
            ])
    lines.extend(table(
        ["€/t CO2e", "private Abnahme", "mögliche Entlastung Mrd. €", "Anteil Förderlücke", "verbleibend Mrd. €"],
        private_rows,
    ))

    lines.extend([
        "",
        "6. NOMINALE RESTFÖRDERUNG",
        "-" * 78,
        "",
        f"Positive Jahreszahlungen im Modellumfang:       {de(scope_positive / 1e9, 3)} Mrd. €",
        f"Davon mit plausibler Jahreskennung:             {de(float(scope['identified_payment_eur']) / 1e9, 3)} Mrd. € ({pct(float(scope['identified_payment_eur']) / scope_positive, 2)})",
        f"Nominale Restzahlung im Modellumfang:           {de(float(scope['nominal_payment_eur']) / 1e9, 3)} Mrd. €",
        f"Nominale Rest-Förderlücke nach Marktwert:       {de(nominal_support / 1e9, 3)} Mrd. €",
        f"Vergleich: bestehende Restförderungsgrafik, alle positiven Zeilen und alle Energieträger/Veräußerungsformen: {de(float(db_info['legacy_nominal_rest_payment_eur']) / 1e9, 3)} Mrd. €",
        "",
        "Der Vergleichswert der bestehenden Grafik ist größer, weil er alle",
        "Energieträger und Veräußerungsformen sowie positive Einzelzeilen umfasst.",
        "Die Deckungsanalyse verwendet dagegen jährlich aggregierte Kategorien im",
        "klar definierten Modellumfang, damit negative Korrekturen nicht zugleich",
        "als separate positive Restverpflichtung fortgeschrieben werden.",
        "",
        "Die nominale Rechnung unterstellt konstante Jahresmenge, konstante",
        f"EEG-Zahlung, Marktwerte und THG-Wirkung auf dem Niveau {year}. Sie ist keine",
        "Barwertrechnung und keine Prognose. Kategorien ohne plausibel lesbare",
        "Jahreskennung werden nicht hochgerechnet.",
        "",
    ])
    rest_rows = []
    for price in prices:
        total, _ = result_by_price[price]
        rest_rows.append([
            de(price, 0),
            de(total.remaining_relief_eur / 1e9, 2),
            pct(total.remaining_relief_eur / nominal_support if nominal_support else 0.0),
            de((nominal_support - total.remaining_relief_eur) / 1e9, 2),
        ])
    lines.extend(table(
        ["€/t CO2e", "nominal ersetzbare Rest-Förderlücke Mrd. €", "Anteil", "nominal verbleibend Mrd. €"],
        rest_rows,
    ))

    lines.extend([
        "",
        "7. METHODIK",
        "-" * 78,
        "",
        "7.1 Zeitliche Referenz",
        f"SMARD-Erzeugung und Day-ahead-Preis werden stündlich für {year} ausgewertet.",
        "Die Bestands-Netzeinspeisung jedes Energieträgers wird durch eine linear",
        "zwischen den UBA/AGEE-Stat-Jahresendbeständen interpolierte installierte",
        "Leistung geteilt. Daraus entstehen Marktwert und Klimaleistung je MWh.",
        "",
        "7.2 Klimaleistung",
        "Klimaleistung ist die Summe aus stündlicher Energie und dem gleichzeitig",
        "erzeugungsgewichteten fossilen SMARD-Mix aus Braunkohle, Steinkohle,",
        "Erdgas und Sonstigen Konventionellen.",
        "Direkte Kraftwerksemission und Vorkette werden getrennt geführt; "
        "die Vorkette wird als expliziter Aufschlag ausgewiesen und erst danach "
        "zum Gesamtansatz addiert:",
        "",
        *[
            f"  - {label}: direkt {de(core.DIRECT_FOSSIL_EMISSIONS_T_CO2E_MWH[key], 3)} "
            f"+ Vorketten-Aufschlag {de(core.UPSTREAM_SURCHARGE_T_CO2E_MWH[key], 3)} "
            f"= gesamt {de(core.FOSSIL_EMISSIONS_T_CO2E_MWH[key], 3)} t CO2e/MWh"
            for key, label in (
                ("lignite", "Braunkohle"),
                ("hard_coal", "Steinkohle"),
                ("gas", "Erdgas"),
                ("other_conventional", "Sonstige Konventionelle"),
            )
        ],
        "",
        "Die Aufschläge und ihre Quellen werden im Kernskript sowie in "
        "fossile_emissionsansaetze.csv dokumentiert. Sonstige Konventionelle "
        "bleiben wegen der heterogenen SMARD-Sammelkategorie ein Ölprodukt-Proxy.",
        "Es handelt sich definitionsgemäß um rechnerische fossile Brutto-",
        "Verdrängung, nicht um eine vollständige LCA oder einen kausalen",
        "Grenzkraftwerksnachweis.",
        "",
        "7.3 EEG-Kategorien",
        "Die Daten werden über das Gesamtjahr je Energieträger, Veräußerungsform",
        "und Vergütungskategorie aggregiert. Nur Kategorien mit positiver",
        "Jahresstrommenge können als ct/kWh- beziehungsweise Deckungsfall verwendet",
        "werden. Positive Zahlungen bilden den ersetzbaren Bestand. Negative",
        "Jahreskategorien werden protokolliert, aber nicht als positive Förderung",
        "oder negative gesetzliche Marktprämie behandelt.",
        "",
        "7.4 Deckungslogik",
        "Einspeisevergütung: min(positive EEG-Zahlung, Marktwert + Klimaleistung).",
        "Marktprämie: min(positive Prämienzahlung, Klimaleistung).",
        "Förderlücke: Einspeisevergütung minus Marktwert beziehungsweise positive",
        "Marktprämie. Die zusätzliche Entlastung ist die Klimaleistung, jeweils auf",
        "diese Förderlücke begrenzt.",
        "",
        "7.5 Restförderung",
        "Das Inbetriebnahmejahr wird konservativ aus den letzten zwei Ziffern des",
        "Kategoriecodes gelesen. Restjahre = max(0, Inbetriebnahmejahr + 20 -",
        f"{year}). Diese Näherung folgt der vorhandenen Netztransparenz-",
        "Restförderungsgrafik; Sonderlaufzeiten und nicht codierte Kategorien",
        "bleiben unberücksichtigt.",
        "",
        "8. UNSICHERHEITEN UND BILANZGRENZEN",
        "-" * 78,
        "",
        "- Die Werte verwenden Marktpreise, Erzeugungsprofile und fossilen Mix des",
        f"  Jahres {year}; künftige Jahre können deutlich abweichen.",
        "- Private Nachfrage nach Klimaleistung ist nicht nachgewiesen, sondern wird",
        "  als Abnahmeanteil parametrisiert.",
        "- Staatliche Entlastung entsteht nur, soweit private Zahlungen öffentliche",
        "  Förderung tatsächlich ersetzen. Zahlt der Staat die Klimaleistung selbst,",
        "  ist dies zunächst eine Umstrukturierung der Förderung.",
        "- Verwaltung, Register, Vermarktungskosten, Ausgleichsenergie, Übergangs-",
        "  regeln und Vertrauensschutz sind nicht eingerechnet.",
        "- Die nominale Restförderung hält sämtliche Jahreswerte konstant und ist",
        "  weder Barwert noch belastbare Haushaltsprognose.",
        "- Biomasse wird hier nur anhand des Einspeiseprofils bewertet; brennstoff-",
        "  und KWK-spezifische THG-Bilanzen sind nicht enthalten.",
        "",
        "9. FÜR DEN ARTIKEL GEEIGNETE FORMULIERUNG",
        "-" * 78,
        "",
        "Unter den Markt-, Erzeugungs-, Emissions- und Vergütungsbedingungen des",
        f"Jahres {year} ergibt die Modellrechnung folgende Größenordnungen:",
        "",
    ])
    for price in prices:
        total, _ = result_by_price[price]
        lines.append(
            f"- Bei {de(price, 0)} €/t CO2e werden rechnerisch "
            f"{de(total.operator_payment_covered_eur / 1e9, 2)} Mrd. € beziehungsweise "
            f"{pct(total.operator_payment_covered_eur / scope_positive)} der positiven "
            f"EEG-Zahlungen abgedeckt. Der zusätzliche Klimaleistungsbeitrag ersetzt "
            f"bis zu {de(total.climate_support_relief_eur / 1e9, 2)} Mrd. € beziehungsweise "
            f"{pct(total.climate_support_relief_eur / support_base)} der nach Marktwert "
            "verbleibenden Förderlücke, sofern die Klimaleistung vollständig privat "
            "abgenommen wird."
        )
    lines.extend([
        "",
        "Die tatsächliche Haushaltsentlastung hängt insbesondere von privater",
        "Nachfrage, künftigen Marktpreisen, dem fossilen Strommix, Übergangsregeln",
        "und den Kosten der Nachweisführung ab. Die nominale Restförderungsrechnung",
        "ist nur eine konstante Fortschreibung des Jahres 2024 und keine Prognose.",
        "",
        "10. QUELLEN",
        "-" * 78,
        "",
        f"- Netztransparenz EEG-Bewegungsdaten: {core.NETZTRANSPARENZ_EEG_URL}",
        f"- SMARD Stundendaten und Day-ahead-Preis: {core.SMARD_URL}",
        f"- UBA/AGEE-Stat installierte Leistungen: {core.UBA_CAPACITY_URL}",
        f"- UBA direkte fossile Emissionsansätze: {core.UBA_EMISSIONS_URL}",
        f"- UBA Vorketten Erdgas und Steinkohle: {core.UBA_UPSTREAM_URL}",
        f"- UNECE Lebenszykluswert Braunkohle: {core.UNECE_LCA_URL}",
        f"- JEC WTT v5 Ölproduktbereitstellung: {core.JEC_WTT_URL}",
        f"- EEG-Datenbank-Metadaten: {db_info['database_source']}",
        f"- Rechenannahmen und Referenzwerte: {core_path.name}, Version {getattr(core, 'VERSION', 'unbekannt')}",
        "",
        "ENDE DER RESULTATDATEI",
    ])
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smard-db", type=Path, default=script_dir / "smard_stundendaten_2021_2025.sqlite")
    parser.add_argument("--eeg-db", type=Path, default=script_dir / "netztransparenz_eeg.sqlite")
    parser.add_argument("--core-script", type=Path, default=script_dir / "artikelgrafiken_eeg_klimaleistung.py")
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--climate-prices", default="50,100,150", help="Kommagetrennte Preise in EUR/t CO2e")
    parser.add_argument("--private-shares", default="0.25,0.50,1.00", help="Kommagetrennte private Abnahmeanteile 0 bis 1")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Ziel-.res; Standard: artikelgrafiken/deckungsanalyse_eeg_klimaleistung_<Jahr>.res",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        prices = parse_floats(args.climate_prices, lower=0.0)
        shares = parse_floats(args.private_shares, lower=0.0, upper=1.0)
        core = load_core(args.core_script.resolve())
        categories, db_info = load_categories(args.eeg_db.resolve(), args.year)
        references = references_from_core(core, args.smard_db.resolve(), args.year)
        report = build_report(
            core=core,
            core_path=args.core_script.resolve(),
            smard_path=args.smard_db.resolve(),
            eeg_path=args.eeg_db.resolve(),
            year=args.year,
            prices=prices,
            private_shares=shares,
            categories=categories,
            db_info=db_info,
            references=references,
        )
        out = (
            args.out
            if args.out is not None
            else Path(__file__).resolve().parent / "artikelgrafiken" / f"deckungsanalyse_eeg_klimaleistung_{args.year}.res"
        ).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print("Deckungsanalyse abgeschlossen.")
        print(f"  Ergebnis: {out}")
        print(f"  Jahr: {args.year}")
        print("  Klimaleistungspreise: " + ", ".join(f"{value:g}" for value in prices) + " EUR/t CO2e")
        print("  Private Abnahmeanteile: " + ", ".join(f"{value:.0%}" for value in shares))
    except (RuntimeError, ValueError, sqlite3.Error, OSError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
