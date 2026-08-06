#!/usr/bin/env python3
# Copyright (c) 2026 Sebastian Putzke
# SPDX-License-Identifier: Apache-2.0
"""Erzeugt die zwei für den Gastbeitrag benötigten Publikationsgrafiken.

Die Berechnung wird nicht neu implementiert, sondern aus den drei geprüften
Modulen übernommen:

* ``netztransparenz_grafiken.py``: EEG-Zahlungsstruktur 2024,
* ``artikelgrafiken_eeg_klimaleistung.py``: Marktwert und Klimaleistung,
* ``klimaleistung_marktmodell_2030.py``: stündliches Angebots-/Nachfragemodell.

Ausgaben:

1. ``01_eeg_zahlungen_und_klimaleistung.svg/.png``
   A: EEG-Zahlungsstruktur 2024
   B: Marktwert und Klimaleistung nach Energieträger

2. ``02_stuendlicher_klimaleistungsmarkt_2030.svg/.png``
   A: anbieterseitige Preisuntergrenze
   B: stündliche Differenz von Angebot und strenger 24/7-Nachfrage

Zusätzlich wird ``BILDTEXTE_UND_METHODIK.md`` mit Bildunterschriften,
Annahmen, Quellen und Modellgrenzen geschrieben.
"""

from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
VERSION = "1.0.1"
AUTHOR_NAME = "Sebastian Putzke"
COPYRIGHT_YEAR = datetime.now().year
LICENSE_LABEL = "CC BY 4.0"

# Lokale Rechenmodule müssen neben diesem Skript liegen.
sys.path.insert(0, str(SCRIPT_DIR))
try:
    import artikelgrafiken_eeg_klimaleistung as kl
    import klimaleistung_marktmodell_2030 as market
    import netztransparenz_grafiken as nt
except ImportError as exc:  # pragma: no cover - verständliche CLI-Meldung
    raise SystemExit(
        "Die Module artikelgrafiken_eeg_klimaleistung.py, "
        "klimaleistung_marktmodell_2030.py und netztransparenz_grafiken.py "
        "müssen im selben Verzeichnis liegen."
    ) from exc


# Einheitliche Artikelpalette. Wind an Land bleibt hellblau, Offshore marine.
CARRIER_COLORS = {
    "Solar": "#F2C230",
    "Solarenergie": "#F2C230",
    "Wind an Land": "#72B6E1",
    "Windenergie an Land": "#72B6E1",
    "Wind auf See": "#174A7E",
    "Windenergie auf See": "#174A7E",
    "Biomasse": "#4F8A4C",
    "Wasser": "#15979F",
    "Sonstige": "#777777",
    "nicht zugeordnet": "#B8B8B8",
}

PAYMENT_CARRIER_ORDER = [
    "Solarenergie",
    "Windenergie an Land",
    "Windenergie auf See",
    "Biomasse",
    "Wasser",
    "Sonstige",
    "nicht zugeordnet",
]


def de(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smard-db",
        type=Path,
        default=SCRIPT_DIR / "smard_stundendaten_2021_2025.sqlite",
    )
    default_scenario_db = (
        SCRIPT_DIR / "wetterdaten_szenarien_2024_v22.sqlite"
        if (SCRIPT_DIR / "wetterdaten_szenarien_2024_v22.sqlite").is_file()
        else SCRIPT_DIR / "wetterdaten_szenarien.sqlite"
    )
    parser.add_argument(
        "--scenario-db",
        type=Path,
        default=default_scenario_db,
    )
    parser.add_argument(
        "--eeg-db",
        type=Path,
        default=SCRIPT_DIR / "netztransparenz_eeg.sqlite",
    )
    parser.add_argument(
        "--weather-db",
        type=Path,
        default=SCRIPT_DIR / "wetter_und_referenzdaten.sqlite",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=SCRIPT_DIR / "artikelgrafiken_neue_energie",
    )
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument(
        "--site-id",
        default=None,
        help="Nur nötig, wenn die Szenariendatenbank mehrere Standorte enthält.",
    )
    parser.add_argument("--weather-year", type=int, default=2024)
    parser.add_argument("--weather-site", default="kassel_mitte")
    parser.add_argument("--climate-floor-eur-t", type=float, default=74.0)
    parser.add_argument("--scarcity-premium-eur-mwh", type=float, default=200.0)
    parser.add_argument("--bin-width", type=float, default=0.5)
    parser.add_argument("--min-payment-ct-kwh", type=float, default=0.0)
    parser.add_argument("--max-payment-ct-kwh", type=float, default=60.0)
    return parser.parse_args()


def ensure_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} nicht gefunden: {path}")


def setup_style() -> None:
    import matplotlib as mpl

    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "axes.edgecolor": "#444444",
            "axes.linewidth": 0.8,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 8.5,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "svg.fonttype": "none",
        }
    )


def save_figure(fig, path_without_suffix: Path) -> None:
    fig.savefig(path_without_suffix.with_suffix(".svg"), bbox_inches="tight")
    fig.savefig(path_without_suffix.with_suffix(".png"), dpi=260, bbox_inches="tight")


def load_2024_article_data(args: argparse.Namespace):
    ensure_file(args.smard_db, "SMARD-Datenbank")
    ensure_file(args.scenario_db, "Szenariendatenbank")
    ensure_file(args.eeg_db, "EEG-Datenbank")

    smard = kl.load_smard(args.smard_db, args.year)
    references = kl.build_reference_cases(smard, args.year)
    scenarios, site_id = kl.load_scenario_cases(
        args.scenario_db, smard, args.year, args.site_id
    )
    cases = kl.ordered_cases(references, scenarios)
    eeg, eeg_year = kl.load_eeg_stats(args.eeg_db)
    if eeg_year.isdigit() and int(eeg_year) != args.year:
        raise ValueError(
            f"Jahreskonflikt: SMARD/Szenarien {args.year}, EEG-Datenbank {eeg_year}."
        )

    con = sqlite3.connect(args.eeg_db)
    try:
        nt.check_database(con)
        payment_rows = nt.rate_bins(
            con,
            args.bin_width,
            args.min_payment_ct_kwh,
            args.max_payment_ct_kwh,
        )
    finally:
        con.close()
    return cases, eeg, eeg_year, site_id, payment_rows


def plot_payment_structure_panel(
    ax,
    rows: Iterable[tuple[float, str, float, float, int]],
    bin_width: float,
    max_rate: float,
) -> float:
    """Zeichnet die Zahlungsstruktur auf eine bestehende Matplotlib-Achse."""
    from matplotlib.patches import Rectangle

    rows = list(rows)
    total_twh = float(sum(row[2] for row in rows))
    if total_twh <= 0:
        raise ValueError("Keine Strommenge im gewählten EEG-Zahlungsbereich.")

    grouped: dict[float, list[tuple[str, float, float, int]]] = defaultdict(list)
    for lower_rate, carrier, quantity_twh, payment_billion, count in rows:
        grouped[float(lower_rate)].append(
            (str(carrier), float(quantity_twh), float(payment_billion), int(count))
        )

    order_index = {name: i for i, name in enumerate(PAYMENT_CARRIER_ORDER)}
    cursor = 0.0
    for lower_rate in sorted(grouped, reverse=True):
        segments = grouped[lower_rate]
        class_quantity = sum(item[1] for item in segments)
        class_payment = sum(item[2] for item in segments)
        actual_rate = class_payment / class_quantity * 100.0 if class_quantity else lower_rate
        for carrier, quantity_twh, _payment, _count in sorted(
            segments, key=lambda item: order_index.get(item[0], 999)
        ):
            ax.add_patch(
                Rectangle(
                    (cursor, 0.0),
                    quantity_twh,
                    max(actual_rate, 0.0),
                    facecolor=CARRIER_COLORS.get(carrier, "#777777"),
                    edgecolor="none",
                    linewidth=0.0,
                )
            )
            cursor += quantity_twh

    ax.set_xlim(0.0, total_twh)
    ax.set_ylim(0.0, max_rate)
    ax.set_xlabel("Kumulierte Strommenge [TWh]")
    ax.set_ylabel("EEG-Zahlung [ct/kWh]")
    ax.set_title("A · EEG-Zahlungsstruktur 2024", loc="left", fontweight="bold", pad=8)
    ax.grid(True, axis="y", color="#D9D9D9", linewidth=0.7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(
        0.995,
        0.96,
        f"{de(total_twh, 1)} TWh · nichtnegative Zahlungsklassen 0–{de(max_rate, 0)} ct/kWh",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=8.6,
        color="#4A4A4A",
    )
    return total_twh


def build_revenue_layout(cases):
    shown = kl.plotted_cases(cases)
    by_carrier = {
        carrier: [case for case in shown if case.carrier == carrier]
        for carrier in kl.CARRIER_ORDER
    }
    new_labels = {
        "pv_sued_30": "Neu\nSüd 30°",
        "pv_sued_60": "Neu\nSüd 60°",
        "pv_ost_west_15": "Neu\nO–W 15°",
        "wind_standard": "Neu\nStandard",
        "wind_schwachwind": "Neu\nSchwachwind",
    }
    items = []
    positions = []
    labels = []
    group_centres = []
    separators = []
    cursor = 0.0

    for carrier in kl.CARRIER_ORDER:
        group = by_carrier[carrier]
        reference = next(case for case in group if case.is_reference)
        new_cases = [case for case in group if not case.is_reference]
        group_positions = []
        for mode, label in (
            ("V_REF", "EEG\nVoll"),
            ("MP_REF", "Markt +\nPrämie"),
            ("KL_REF", "Bestand\nMarkt + KL"),
        ):
            positions.append(cursor)
            group_positions.append(cursor)
            items.append((mode, reference))
            labels.append(label)
            cursor += 1.0
        if new_cases:
            cursor += 0.40
        for case in new_cases:
            positions.append(cursor)
            group_positions.append(cursor)
            items.append(("KL_NEW", case))
            labels.append(new_labels.get(case.case_id, "Neu\n" + case.short_label))
            cursor += 1.0
        group_centres.append((carrier, (group_positions[0] + group_positions[-1]) / 2.0))
        separators.append(cursor + 0.25)
        cursor += 1.10
    if separators:
        separators.pop()
    return np.asarray(positions), items, labels, group_centres, separators


def plot_revenue_panel(ax, cases, eeg, smard_year: int) -> None:
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    x, items, labels, group_centres, separators = build_revenue_layout(cases)
    bar_width = 0.62
    top_values = []
    scale = 1000.0

    def draw_mean(xpos: float, value: float, color: str) -> None:
        ax.hlines(value, xpos - bar_width / 2, xpos + bar_width / 2,
                  color="white", linewidth=3.0, zorder=5)
        ax.hlines(value, xpos - bar_width / 2, xpos + bar_width / 2,
                  color=kl.shade(color, -0.48), linewidth=1.45, zorder=6)

    for xpos, (mode, case) in zip(x, items):
        stats = eeg[case.carrier]
        color = CARRIER_COLORS[case.carrier]
        energy = case.energy_mwh_per_mw
        market_revenue = case.market_revenue_eur_per_mw / scale

        full_low = stats.full_min_ct_kwh * 10.0 * energy / scale
        full_high = stats.full_max_ct_kwh * 10.0 * energy / scale
        full_mean = stats.full_mean_ct_kwh * 10.0 * energy / scale
        premium_low = market_revenue + stats.premium_min_ct_kwh * 10.0 * energy / scale
        premium_high = market_revenue + stats.premium_max_ct_kwh * 10.0 * energy / scale
        premium_mean = market_revenue + stats.premium_mean_ct_kwh * 10.0 * energy / scale

        if mode == "V_REF":
            ax.bar(xpos, full_low, bar_width, color=color)
            ax.bar(
                xpos,
                max(0.0, full_high - full_low),
                bar_width,
                bottom=full_low,
                color=kl.shade(color, 0.68),
            )
            draw_mean(xpos, full_mean, color)
            top_values.append(max(full_high, full_mean))
        elif mode == "MP_REF":
            ax.bar(xpos, premium_low, bar_width, color=color)
            ax.bar(
                xpos,
                max(0.0, premium_high - premium_low),
                bar_width,
                bottom=premium_low,
                color=kl.shade(color, 0.68),
            )
            draw_mean(xpos, premium_mean, color)
            top_values.append(max(premium_high, premium_mean))
        else:
            ax.bar(xpos, market_revenue, bar_width, color=kl.shade(color, -0.16))
            block = case.displaced_thg_t_co2e_per_mw * 50.0 / scale
            for index, lightness in enumerate((0.22, 0.44, 0.66)):
                ax.bar(
                    xpos,
                    block,
                    bar_width,
                    bottom=market_revenue + index * block,
                    color=kl.shade(color, lightness),
                )
            top_values.append(market_revenue + 3.0 * block)

    ax.set_ylim(0.0, max(top_values) * 1.14)
    ax.set_ylabel("Jahreserlös [Tsd. €/(MW·a)]")
    ax.set_xticks(x, labels, fontsize=7.4)
    ax.grid(True, axis="y", color="#D9D9D9", linewidth=0.7)
    ax.spines[["top", "right"]].set_visible(False)
    for separator in separators:
        ax.axvline(separator, color="#E1E1E1", linewidth=0.8)
    for carrier, centre in group_centres:
        ax.text(
            centre,
            1.012,
            carrier,
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="bottom",
            fontsize=9.2,
            fontweight="bold",
            color=CARRIER_COLORS[carrier],
        )

    ax.set_title(
        "B · Marktwert und Klimaleistung nach Energieträger",
        loc="left",
        fontweight="bold",
        pad=24,
    )

    component_handles = [
        Patch(facecolor="#555555", label="dunkel: Untergrenze oder Marktwert"),
        Patch(facecolor="#BFBFBF", label="hell: EEG-Spanne oder je +50 €/t"),
        Line2D([0], [0], color="#555555", lw=1.8,
               label="Querlinie: mengengewichteter EEG-Mittelwert"),
    ]
    ax.legend(
        handles=component_handles,
        frameon=False,
        loc="upper right",
        fontsize=7.5,
        borderaxespad=0.0,
        handlelength=1.5,
    )


def create_eeg_and_climate_figure(
    out: Path,
    cases,
    eeg,
    eeg_year: str,
    payment_rows,
    args: argparse.Namespace,
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    fig = plt.figure(figsize=(17.2, 11.4))
    grid = fig.add_gridspec(2, 1, height_ratios=[0.76, 1.48], hspace=0.35)
    ax_payment = fig.add_subplot(grid[0])
    ax_revenue = fig.add_subplot(grid[1])

    fig.suptitle(
        "EEG-Zahlungen und Klimaleistung",
        x=0.06,
        y=0.982,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.06,
        0.951,
        "Historische Zahlungsstruktur 2024 und rechnerische Wirkung eines zusätzlichen Klimaleistungserlöses",
        ha="left",
        fontsize=10.2,
        color="#4A4A4A",
    )

    plot_payment_structure_panel(
        ax_payment,
        payment_rows,
        args.bin_width,
        args.max_payment_ct_kwh,
    )
    plot_revenue_panel(ax_revenue, cases, eeg, args.year)

    used_carriers = [
        name for name in PAYMENT_CARRIER_ORDER
        if any(row[1] == name for row in payment_rows)
    ]
    carrier_handles = [
        Patch(facecolor=CARRIER_COLORS[name], label=name) for name in used_carriers
    ]
    fig.legend(
        handles=carrier_handles,
        frameon=False,
        ncol=min(len(carrier_handles), 7),
        loc="upper left",
        bbox_to_anchor=(0.055, 0.922),
        fontsize=8.2,
        handlelength=1.4,
        columnspacing=1.2,
    )

    fig.text(
        0.06,
        0.015,
        "Quellen: EEG-Jahresabrechnung Netztransparenz 2024; SMARD 2024; Wetter-/Anlagenszenarien siehe Methodik",
        ha="left",
        fontsize=7.8,
        color="#4A4A4A",
    )
    fig.text(
        0.94,
        0.015,
        f"© {AUTHOR_NAME} {COPYRIGHT_YEAR} · {LICENSE_LABEL}",
        ha="right",
        fontsize=7.8,
        color="#4A4A4A",
    )
    fig.subplots_adjust(left=0.065, right=0.985, top=0.88, bottom=0.095)
    save_figure(fig, out / "01_eeg_zahlungen_und_klimaleistung")
    plt.close(fig)


def load_market_data(args: argparse.Namespace):
    ensure_file(args.smard_db, "SMARD-Datenbank")
    ensure_file(args.weather_db, "Wetterdatenbank")

    inputs = market.load_hourly_inputs(
        args.smard_db,
        args.weather_db,
        args.weather_year,
        args.weather_site,
    )
    supply = market.build_supply(inputs)
    strict_demand = market.build_strict_demand(inputs)
    district_heat = market.build_district_heat_hp(inputs)
    fossil_intensity = market.build_fossil_intensity(inputs)

    total_supply = np.sum(np.vstack(list(supply.values())), axis=0)
    demand_without_heat = np.sum(np.vstack(list(strict_demand.values())), axis=0)
    hp_electricity = np.asarray(district_heat["hp_electricity_mwh"], dtype=float)
    total_demand = demand_without_heat + hp_electricity
    net_balance = total_supply - total_demand

    tranches = market.offer_tranches()
    tranche_profiles = market.build_tranche_profiles(supply, tranches)
    clearing = market.clear_market(
        total_demand,
        tranche_profiles,
        args.scarcity_premium_eur_mwh,
    )
    price_eur_t = clearing["price_eur_mwh"] / fossil_intensity
    return price_eur_t, net_balance, total_supply, total_demand


def create_market_figure(
    out: Path,
    price_eur_t: np.ndarray,
    net_balance_mwh: np.ndarray,
    total_supply_mwh: np.ndarray,
    total_demand_mwh: np.ndarray,
    floor_eur_t: float,
) -> None:
    import matplotlib.pyplot as plt

    n_hours = len(price_eur_t)
    hours = np.arange(1, n_hours + 1)
    shortage_mask = net_balance_mwh < -1e-9
    known_mask = ~shortage_mask
    shortage_hours = int(shortage_mask.sum())

    known_prices = np.sort(price_eur_t[known_mask])[::-1]
    known_x = np.arange(shortage_hours + 1, n_hours + 1)

    supply_twh = float(total_supply_mwh.sum() / 1e6)
    demand_twh = float(total_demand_mwh.sum() / 1e6)
    shortage_twh = float(np.maximum(-net_balance_mwh, 0.0).sum() / 1e6)
    max_shortage_gw = float(np.maximum(-net_balance_mwh, 0.0).max() / 1000.0)

    fig, (ax_price, ax_balance) = plt.subplots(
        2,
        1,
        figsize=(13.3, 9.1),
        gridspec_kw={"height_ratios": [1.0, 1.05], "hspace": 0.32},
    )
    fig.suptitle(
        "Stündlicher Markt für THG-freien Strom 2030",
        x=0.075,
        y=0.982,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.075,
        0.947,
        f"Optimistisches Szenario: {demand_twh:.0f} TWh strenge 24/7-Nachfrage · {supply_twh:.0f} TWh THG-freies Jahresangebot",
        ha="left",
        fontsize=10.1,
        color="#4A4A4A",
    )

    if shortage_hours:
        ax_price.axvspan(
            0.5,
            shortage_hours + 0.5,
            facecolor="#F4E8E8",
            hatch="////",
            edgecolor="#A33A3A",
            linewidth=0.7,
            alpha=0.95,
        )
        ax_price.text(
            max(1.0, shortage_hours * 0.53),
            max(floor_eur_t * 1.25, float(np.nanpercentile(known_prices, 99)) * 0.72),
            f"{shortage_hours} Stunden ohne\nvollständige Deckung:\nPreis offen",
            ha="center",
            va="center",
            fontsize=8.8,
            color="#7A1F1F",
        )

    ax_price.plot(
        known_x,
        known_prices,
        linewidth=1.9,
        color="#174A7E",
        label="anbieterseitige Preisuntergrenze",
    )
    ax_price.axhline(
        floor_eur_t,
        linestyle="--",
        linewidth=1.45,
        color="#B38800",
        label=f"beispielhafte Garantie: {floor_eur_t:g} €/t",
    )
    below = known_prices < floor_eur_t
    if np.any(below):
        ax_price.fill_between(
            known_x,
            known_prices,
            floor_eur_t,
            where=below,
            color="#F2C230",
            alpha=0.18,
            label="möglicher Aufstockungsbereich",
        )
    ax_price.set_xlim(1, n_hours)
    ax_price.set_ylim(bottom=0)
    ax_price.set_ylabel("Klimaleistungspreis [€/t CO₂e]")
    ax_price.set_xlabel("Jahresstunden, nach Preis absteigend sortiert")
    ax_price.set_title(
        "A · Anbieterseitige Preisuntergrenze",
        loc="left",
        fontweight="bold",
        pad=8,
    )
    ax_price.grid(True, axis="y", color="#D9D9D9", linewidth=0.7)
    ax_price.spines[["top", "right"]].set_visible(False)
    ax_price.legend(loc="upper right", frameon=False, fontsize=8.5)

    balance_order = np.argsort(net_balance_mwh)
    sorted_supply = total_supply_mwh[balance_order] / 1000.0
    sorted_demand = total_demand_mwh[balance_order] / 1000.0
    sorted_balance = net_balance_mwh[balance_order] / 1000.0

    # Angebot und Nachfrage bleiben als dünne Orientierungslinien sichtbar;
    # die farblich hervorgehobene Hauptaussage ist ihre Differenz.
    ax_balance.plot(
        hours,
        sorted_supply,
        linewidth=1.05,
        color="#72B6E1",
        alpha=0.70,
        label="THG-freies Angebot",
    )
    ax_balance.plot(
        hours,
        sorted_demand,
        linewidth=1.05,
        color="#444444",
        alpha=0.75,
        label="strenge 24/7-Nachfrage",
    )
    ax_balance.plot(
        hours,
        sorted_balance,
        linewidth=1.45,
        color="#174A7E",
        label="Angebot − Nachfrage",
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
    ax_balance.axhline(0.0, linestyle=":", linewidth=0.9, color="#555555")
    ax_balance.set_xlim(1, n_hours)
    ax_balance.set_xlabel("Jahresstunden, nach Angebot − Nachfrage aufsteigend sortiert")
    ax_balance.set_ylabel("Leistung [GW]")
    ax_balance.set_title(
        "B · Stündliche Deckung von Angebot und Nachfrage",
        loc="left",
        fontweight="bold",
        pad=8,
    )
    ax_balance.grid(True, axis="y", color="#D9D9D9", linewidth=0.7)
    ax_balance.spines[["top", "right"]].set_visible(False)
    ax_balance.legend(loc="upper left", ncol=3, frameon=False, fontsize=8.2)
    ax_balance.text(
        0.985,
        0.055,
        f"Unterdeckung: {shortage_hours} h · {de(shortage_twh, 2)} TWh\nMaximum: {de(max_shortage_gw, 1)} GW",
        transform=ax_balance.transAxes,
        ha="right",
        va="bottom",
        fontsize=8.7,
        color="#7A1F1F",
    )

    fig.text(
        0.075,
        0.029,
        "Modellrechnung, keine Marktpreisprognose. Profile 2024 auf Mengen 2030 skaliert; Nachfrageszenario und Grenzen im Begleittext.",
        ha="left",
        fontsize=7.8,
        color="#4A4A4A",
    )
    fig.text(
        0.075,
        0.011,
        "Quellen: EEG-Mittelfristprognose 2030; SMARD 2024; BNetzA-Monitoring 2025; weitere Quellen siehe Methodik",
        ha="left",
        fontsize=7.8,
        color="#4A4A4A",
    )
    fig.text(
        0.925,
        0.011,
        f"© {AUTHOR_NAME} {COPYRIGHT_YEAR} · {LICENSE_LABEL}",
        ha="right",
        fontsize=7.8,
        color="#4A4A4A",
    )
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.105, top=0.90)
    save_figure(fig, out / "02_stuendlicher_klimaleistungsmarkt_2030")
    plt.close(fig)


def write_explanations(
    path: Path,
    args: argparse.Namespace,
    eeg_year: str,
    site_id: str,
    payment_rows,
    price_eur_t: np.ndarray,
    net_balance_mwh: np.ndarray,
    total_supply_mwh: np.ndarray,
    total_demand_mwh: np.ndarray,
) -> None:
    total_payment_twh = sum(row[2] for row in payment_rows)
    shortage = np.maximum(-net_balance_mwh, 0.0)
    shortage_hours = int(np.count_nonzero(shortage > 1e-9))
    shortage_twh = float(shortage.sum() / 1e6)
    supply_twh = float(total_supply_mwh.sum() / 1e6)
    demand_twh = float(total_demand_mwh.sum() / 1e6)
    known_prices = price_eur_t[shortage <= 1e-9]

    text = f"""# Bildtexte und Methodik – Gastbeitrag Klimaleistung

Erzeugt mit `artikelgrafiken_neue_energie.py` Version {VERSION}.

## Abbildung 1 – EEG-Zahlungen und Klimaleistung

**Kurzbildtext**

Die bestehende EEG-Förderung verteilt sehr unterschiedliche Zahlungen auf die geförderten Strommengen. Die zweite Teilgrafik stellt diesen historischen Erlösen den stündlichen Marktwert und eine zusätzliche Klimaleistung bei 50, 100 und 150 Euro je Tonne CO₂e gegenüber.

**Methodischer Hinweis**

- Teil A zeigt {de(total_payment_twh, 1)} TWh mit nichtnegativen EEG-Zahlungen zwischen {de(args.min_payment_ct_kwh, 0)} und unter {de(args.max_payment_ct_kwh, 0)} ct/kWh.
- Die Balkenbreite entspricht der Strommenge; bei der Marktprämie ist der Strommarkterlös nicht enthalten.
- Teil B verwendet die EEG-Bandbreiten {eeg_year}, den stündlichen SMARD-Markt {args.year} und die Klimaleistungsrechnung einschließlich separat ausgewiesener fossiler Vorkettenemissionen.
- Die Querlinien markieren mengengewichtete EEG-Mittelwerte. Die hellen Klimaleistungsblöcke entsprechen jeweils weiteren 50 €/t CO₂e.
- Standort der Wetterszenarien: `{site_id}`.

**Quellen**

Netztransparenz EEG-Jahresabrechnung und Bewegungsdaten {eeg_year}; Bundesnetzagentur/SMARD {args.year}; Wetter- und Anlagenszenarien sowie Emissionsansätze gemäß der Methodik des Rechenskripts `artikelgrafiken_eeg_klimaleistung.py`.

## Abbildung 2 – Stündlicher Markt für THG-freien Strom 2030

**Kurzbildtext**

Im optimistischen Szenario stehen {de(demand_twh, 0)} TWh streng stündlich zugeordneter Nachfrage {de(supply_twh, 1)} TWh THG-freiem Jahresangebot gegenüber. Trotzdem verbleiben {shortage_hours} Unterdeckungsstunden mit zusammen {de(shortage_twh, 2)} TWh. Ein Jahresüberschuss beseitigt stündliche Knappheit daher nicht.

**Methodischer Hinweis**

- Die obere Teilgrafik zeigt die aus den 2030er EEG-Vermarktungsstufen abgeleitete anbieterseitige Preisuntergrenze, nicht einen prognostizierten Marktpreis.
- In Unterdeckungsstunden ist aus dem modellierten Angebot kein Preis bestimmbar; dort wird kein künstlicher Knappheitspreis eingezeichnet.
- Die untere Teilgrafik zeigt die Dauerlinie von Angebot, Nachfrage und ihrer Differenz. Die Stunden sind nach der Differenz sortiert und deshalb keine chronologische Jahreslinie.
- Die Nachfrage ist ein transparent optimistisches Markthochlauf-Szenario: RFNBO-Elektrolyse, Rechenzentren, öffentliche Hand, DB-Traktionsstrom, 25 % der heutigen Ökostrommengen und Fernwärme-Großwärmepumpen.
- Erzeugungsprofile und Wetter stammen aus {args.weather_year}; der 29. Februar wird entfernt und alle Reihen werden auf 8.760 Stunden und die Mengen 2030 normiert.
- Beispielhafte Garantie: {de(args.climate_floor_eur_t, 0)} €/t CO₂e.
- Bestimmbare anbieterseitige Preise: {de(float(np.nanmin(known_prices)), 1)} bis {de(float(np.nanmax(known_prices)), 1)} €/t CO₂e.

**Quellen**

EEG-Mittelfristprognose 2026–2030; Bundesnetzagentur/SMARD; BNetzA-Monitoringbericht Energie 2025; Deutsche Bahn; Bundeswirtschaftsministerium; Umweltbundesamt; Wärmeplanungsgesetz; Agora Energiewende/Fraunhofer IEG. Detaillierte Herleitungen stehen im Rechenskript `klimaleistung_marktmodell_2030.py`.

## Lizenz

© {AUTHOR_NAME} {COPYRIGHT_YEAR}. Grafiken: {LICENSE_LABEL}.
"""
    path.write_text(text, encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    args.out.mkdir(parents=True, exist_ok=True)
    setup_style()

    print("2024-Auswertung wird geladen …")
    cases, eeg, eeg_year, site_id, payment_rows = load_2024_article_data(args)

    print("2030-Marktmodell wird berechnet …")
    price_eur_t, net_balance, total_supply, total_demand = load_market_data(args)

    old_mpl_config = os.environ.get("MPLCONFIGDIR")
    with tempfile.TemporaryDirectory(prefix="artikelgrafiken_ne_mpl_") as mpl_tmp:
        os.environ["MPLCONFIGDIR"] = mpl_tmp
        try:
            print("Abbildung 1 wird gezeichnet …")
            create_eeg_and_climate_figure(
                args.out,
                cases,
                eeg,
                eeg_year,
                payment_rows,
                args,
            )
            print("Abbildung 2 wird gezeichnet …")
            create_market_figure(
                args.out,
                price_eur_t,
                net_balance,
                total_supply,
                total_demand,
                args.climate_floor_eur_t,
            )
        finally:
            if old_mpl_config is None:
                os.environ.pop("MPLCONFIGDIR", None)
            else:
                os.environ["MPLCONFIGDIR"] = old_mpl_config

    write_explanations(
        args.out / "BILDTEXTE_UND_METHODIK.md",
        args,
        eeg_year,
        site_id,
        payment_rows,
        price_eur_t,
        net_balance,
        total_supply,
        total_demand,
    )

    print("\nFertig.")
    print(f"  {args.out / '01_eeg_zahlungen_und_klimaleistung.svg'}")
    print(f"  {args.out / '02_stuendlicher_klimaleistungsmarkt_2030.svg'}")
    print(f"  {args.out / 'BILDTEXTE_UND_METHODIK.md'}")


def main() -> None:
    args = parse_args()
    try:
        run(args)
    except (FileNotFoundError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
