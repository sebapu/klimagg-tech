#!/usr/bin/env python3
# Copyright (c) 2026 Sebastian Putzke
# SPDX-License-Identifier: Apache-2.0
"""Erzeugt EEG-Grafiken ausschließlich aus eeg_auswertung.sqlite.

Aufruf im Verzeichnis mit der Datenbank:
    python3 eeg_grafiken_aus_datenbank.py

Optional:
    python3 eeg_grafiken_aus_datenbank.py --db /pfad/eeg_auswertung.sqlite
    python3 eeg_grafiken_aus_datenbank.py --klassenbreite 0.5

Ausgaben im Unterordner ``grafiken``:
    01_strommenge_nach_verguetungshoehe.svg/.csv
    02_eeg_zahlung_nach_energietraeger.svg/.csv
    03_nominale_restfoerderung_nach_verguetungshoehe.svg/.csv

Die Vergütungsgrafik zeigt ausschließlich nichtnegative Preisbänder absteigend
von links nach rechts.
Die Höhe eines Balkens entspricht der EEG-Zahlung in ct/kWh, seine Breite
der Strommenge in der Klasse. Bei Marktprämien ist die dargestellte Zahlung
nur die EEG-Prämie; der Markterlös ist nicht enthalten.
"""

from __future__ import annotations

import argparse
import csv
import math
import sqlite3
from pathlib import Path
from xml.sax.saxutils import escape


VERSION = "5.0.0"
DEFAULT_DB = "netztransparenz_eeg.sqlite"
DEFAULT_OUTDIR = "grafiken_netztransparenz"

ENERGIETRAEGER = {
    "1": "Wasser",
    "2": "Deponiegas",
    "3": "Klärgas",
    "4": "Grubengas",
    "5": "Biomasse",
    "6": "Geothermie",
    "7": "Wind an Land",
    "8": "Wind auf See",
    "9": "Solar",
}

COLORS = {
    "Wasser": "#15979F",
    "Biomasse": "#4F8A4C",
    "Windenergie an Land": "#72B6E1",
    "Windenergie auf See": "#174A7E",
    "Solarenergie": "#F2C230",
    "Sonstige": "#777777",
    "nicht zugeordnet": "#B8B8B8",
}

ENERGIETRAEGER_REIHENFOLGE = [
    "Solarenergie", "Windenergie an Land", "Windenergie auf See",
    "Biomasse", "Wasser", "Sonstige", "nicht zugeordnet",
]


def de(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def export_csv(path: Path, header, rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)


def check_database(con: sqlite3.Connection) -> None:
    objects = {row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
    )}
    if "eeg_data" not in objects:
        raise SystemExit(
            "Die Datenbank enthält keine Tabelle 'eeg_data'. "
            "Bitte zuerst netztransparenz_daten_import.py ausführen."
        )
    columns = {row[1] for row in con.execute("PRAGMA table_info(eeg_data)")}
    required = {"carrier", "quantity_kwh", "payment_eur", "payment_ct_kwh"}
    missing = required - columns
    if missing:
        raise SystemExit("In 'eeg_data' fehlen Spalten: " + ", ".join(sorted(missing)))


def carrier_name(code) -> str:
    clean_code = str(code or "").strip()
    if clean_code.endswith(".0") and clean_code[:-2].isdigit():
        clean_code = clean_code[:-2]
    if clean_code in {"2", "3", "4", "6"}:
        return "Sonstige"
    name = ENERGIETRAEGER.get(clean_code, clean_code or "nicht zugeordnet")
    return {
        "Solar": "Solarenergie",
        "Wind an Land": "Windenergie an Land",
        "Wind auf See": "Windenergie auf See",
    }.get(name, name)


def rate_bins(con, bin_width: float, min_rate: float, max_rate: float):
    raw = con.execute(
        """
        SELECT CAST(FLOOR(payment_ct_kwh / ?) AS INTEGER) * ? AS lower_rate,
               CAST(carrier AS TEXT) AS carrier,
               SUM(quantity_kwh) / 1e9 AS quantity_twh,
               SUM(payment_eur) / 1e9 AS payment_billion_eur,
               SUM(source_rows) AS row_count
        FROM eeg_data
        WHERE quantity_kwh > 0
          AND payment_eur IS NOT NULL
          AND payment_ct_kwh >= ?
          AND payment_ct_kwh < ?
        GROUP BY 1, 2
        ORDER BY 1 DESC, 2
        """,
        (bin_width, bin_width, min_rate, max_rate),
    )
    return [(rate, carrier_name(carrier), quantity, payment, count)
            for rate, carrier, quantity, payment, count in raw]


def carrier_rows(con):
    raw = con.execute(
        """
        SELECT CAST(carrier AS TEXT),
               SUM(payment_eur) / 1e9,
               SUM(quantity_kwh) / 1e9
        FROM eeg_data
        GROUP BY CAST(carrier AS TEXT)
        ORDER BY SUM(payment_eur) DESC
        """
    )
    grouped = {}
    for code, payment, quantity in raw:
        clean_code = (code or "").strip()
        if clean_code.endswith(".0") and clean_code[:-2].isdigit():
            clean_code = clean_code[:-2]
        name = carrier_name(clean_code)
        item = grouped.setdefault(name, [0.0, 0.0, []])
        item[0] += payment or 0.0
        item[1] += quantity or 0.0
        item[2].append(clean_code)
    rows = [(name, values[0], values[1], "+".join(values[2]))
            for name, values in grouped.items()]
    return sorted(rows, key=lambda row: row[1], reverse=True)


def svg_rate_structure(path: Path, rows, bin_width: float, min_rate: float, max_rate: float) -> None:
    width, height = 1420, 790
    left, right, top, bottom = 100, 55, 138, 95
    plot_w, plot_h = width - left - right, height - top - bottom
    total_twh = sum(row[2] for row in rows)
    if total_twh <= 0:
        raise SystemExit("Keine positive Strommenge im gewählten Vergütungsbereich gefunden.")

    y_min = 0.0
    y_max = max_rate
    y_span = y_max - y_min

    def py(value):
        return top + (y_max - value) / y_span * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{left}" y="38" font-family="sans-serif" font-size="25" font-weight="700">Strommenge nach Höhe der EEG-Zahlung 2024</text>',
        f'<text x="{left}" y="68" font-family="sans-serif" font-size="15" fill="#444">Absteigend nach Zahlungshöhe; Klassen à {de(bin_width)} ct/kWh; Balkenbreite = Strommenge ({de(total_twh)} TWh).</text>',
    ]

    used = {row[1] for row in rows}
    legend_names = [name for name in ENERGIETRAEGER_REIHENFOLGE if name in used]
    legend_names += sorted(used - set(legend_names))
    legend_x = left
    for name in legend_names:
        color = COLORS.get(name, "#777777")
        parts.extend([
            f'<rect x="{legend_x}" y="91" width="13" height="13" fill="{color}"/>',
            f'<text x="{legend_x + 18}" y="102" font-family="sans-serif" font-size="11">{escape(name)}</text>',
        ])
        legend_x += 32 + max(65, len(name) * 6.4)

    tick_step = 5 if y_span <= 70 else 10
    first_tick = math.ceil(y_min / tick_step) * tick_step
    tick = first_tick
    while tick <= y_max + 1e-9:
        y = py(tick)
        stroke = "#777" if abs(tick) < 1e-9 else "#dddddd"
        parts.extend([
            f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" stroke="{stroke}"/>',
            f'<text x="{left - 12}" y="{y + 4:.2f}" text-anchor="end" font-family="sans-serif" font-size="12">{de(tick, 0)}</text>',
        ])
        tick += tick_step

    grouped = {}
    for lower_rate, name, quantity_twh, payment_billion, count in rows:
        grouped.setdefault(lower_rate, []).append((name, quantity_twh, payment_billion, count))

    cursor_twh = 0.0
    for lower_rate in sorted(grouped, reverse=True):
        segments = grouped[lower_rate]
        class_quantity = sum(item[1] for item in segments)
        class_payment = sum(item[2] for item in segments)
        # Mengengewichteter tatsächlicher Preis innerhalb der Klasse.
        rate = class_payment / class_quantity * 100 if class_quantity else lower_rate
        zero_y = py(0.0)
        rate_y = py(rate)
        rect_y = min(zero_y, rate_y)
        rect_h = max(0.8, abs(zero_y - rate_y))
        segment_order = {name: i for i, name in enumerate(ENERGIETRAEGER_REIHENFOLGE)}
        for name, quantity_twh, _payment, _count in sorted(
            segments, key=lambda item: segment_order.get(item[0], 999)
        ):
            bar_x = left + cursor_twh / total_twh * plot_w
            bar_w = quantity_twh / total_twh * plot_w
            fill = COLORS.get(name, "#777777")
            # Keine künstliche Mindestbreite: Sie würde kleine Segmente vergrößern
            # und mit dem folgenden Segment überlappen lassen.
            parts.append(
                f'<rect x="{bar_x:.6f}" y="{rect_y:.3f}" width="{bar_w:.6f}" '
                f'height="{rect_h:.3f}" fill="{fill}">'
                f'<title>{escape(name)} · {de(lower_rate)} bis {de(lower_rate + bin_width)} ct/kWh: {de(quantity_twh, 3)} TWh</title></rect>'
            )
            cursor_twh += quantity_twh

    x_step = 25 if total_twh <= 300 else 50
    tick = 0
    while tick <= total_twh + 1e-9:
        x = left + tick / total_twh * plot_w
        parts.extend([
            f'<line x1="{x:.2f}" y1="{top + plot_h}" x2="{x:.2f}" y2="{top + plot_h + 6}" stroke="#222"/>',
            f'<text x="{x:.2f}" y="{top + plot_h + 25}" text-anchor="middle" font-family="sans-serif" font-size="12">{de(tick, 0)}</text>',
        ])
        tick += x_step

    parts.extend([
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#222"/>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#222"/>',
        f'<text x="{left + plot_w / 2}" y="{height - 27}" text-anchor="middle" font-family="sans-serif" font-size="14">Strommenge, geordnet von hoher zu niedriger EEG-Zahlung, in TWh</text>',
        f'<text transform="translate(25 {top + plot_h / 2}) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="14">EEG-Zahlung in ct/kWh</text>',
        f'<text x="{left}" y="{height - 6}" font-family="sans-serif" font-size="11" fill="#555">Quelle: eigene Auswertung der EEG-Jahresabrechnung 2024, Netztransparenz.de. Bei Marktprämien ohne Markterlös.</text>',
        '</svg>',
    ])
    path.write_text("\n".join(parts), encoding="utf-8")


def svg_carriers(path: Path, rows) -> None:
    width = 1450
    left, right, top, bottom = 210, 300, 108, 70
    row_h = 54
    height = top + bottom + row_h * len(rows)
    plot_w = width - left - right
    max_payment = max((row[1] for row in rows), default=1.0) or 1.0
    total_payment = sum(row[1] for row in rows)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{left}" y="38" font-family="sans-serif" font-size="25" font-weight="700">EEG-Zahlung nach Energieträger 2024</text>',
        f'<text x="{left}" y="68" font-family="sans-serif" font-size="15" fill="#444">Zahlungen gemäß EEG-Bewegungsdaten; insgesamt {de(total_payment, 2)} Mrd. €.</text>',
    ]

    for index, (name, payment, quantity, _code) in enumerate(rows):
        y = top + index * row_h
        bar_w = payment / max_payment * plot_w
        color = COLORS.get(name, "#777777")
        share = payment / total_payment * 100 if total_payment else 0
        parts.extend([
            f'<text x="{left - 14}" y="{y + 32}" text-anchor="end" font-family="sans-serif" font-size="14">{escape(name)}</text>',
            f'<rect x="{left}" y="{y + 8}" width="{bar_w:.2f}" height="32" fill="{color}"/>',
            f'<text x="{left + bar_w + 9:.2f}" y="{y + 29}" font-family="sans-serif" font-size="13">{de(payment, 3)} Mrd. € · {de(share)} % · {de(quantity)} TWh</text>',
        ])

    parts.extend([
        f'<text x="{left + plot_w / 2}" y="{height - 34}" text-anchor="middle" font-family="sans-serif" font-size="14">EEG-Zahlung in Mrd. €</text>',
        f'<text x="{left}" y="{height - 9}" font-family="sans-serif" font-size="11" fill="#555">Quelle: eigene Auswertung der EEG-Jahresabrechnung 2024, Netztransparenz.de.</text>',
        '</svg>',
    ])
    path.write_text("\n".join(parts), encoding="utf-8")


def remove_obsolete_cumulative_files(outdir: Path) -> None:
    for name in (
        "02_kumulative_strommenge_nach_verguetungshoehe.svg",
        "02_kumulative_strommenge_nach_verguetungshoehe.csv",
    ):
        path = outdir / name
        if path.is_file():
            path.unlink()


def inferred_commissioning_year(category: str):
    """Liest die zweistellige Jahreskennung am Ende eines EEG-Kategoriecodes.

    Die Auswertung ist absichtlich konservativ auf plausible EEG-Jahre begrenzt.
    Kategorien ohne solche Kennung bleiben unzugeordnet.
    """
    text = str(category or "").strip()
    if len(text) < 2 or not text[-2:].isdigit():
        return None
    yy = int(text[-2:])
    year = 2000 + yy
    return year if 2000 <= year <= 2024 else None


def remaining_support_rows(con, bin_width: float, base_year: int):
    """Nominales Basisszenario aus 2024-Zahlung und Regelförderrestlaufzeit.

    Förderjahre nach dem Abrechnungsjahr = Inbetriebnahmejahr + 20 - base_year.
    Negative/Nullzahlungen und nichtpositive Mengen werden ausgeschlossen.
    """
    raw = con.execute(
        """
        SELECT category, carrier, quantity_kwh, payment_eur, payment_ct_kwh
        FROM eeg_data
        WHERE quantity_kwh > 0 AND payment_eur > 0 AND payment_ct_kwh >= 0
        """
    )
    grouped = {}
    total_payment = covered_payment = 0.0
    for category, carrier, quantity, payment, rate in raw:
        total_payment += payment or 0.0
        year = inferred_commissioning_year(category)
        if year is None:
            continue
        covered_payment += payment or 0.0
        remaining_years = max(0, year + 20 - base_year)
        lower = math.floor(rate / bin_width) * bin_width
        key = round(lower, 10)
        item = grouped.setdefault(key, {
            "quantity": 0.0, "payment": 0.0, "remaining": 0.0,
            "weighted_years": 0.0, "years": set(), "carriers": {},
        })
        item["quantity"] += quantity
        item["payment"] += payment
        item["remaining"] += payment * remaining_years
        item["weighted_years"] += payment * remaining_years
        item["years"].add(year)
        name = carrier_name(carrier)
        item["carriers"][name] = item["carriers"].get(name, 0.0) + payment * remaining_years

    rows = []
    for lower, item in grouped.items():
        avg_years = item["weighted_years"] / item["payment"] if item["payment"] else 0.0
        rows.append({
            "lower": lower,
            "upper": lower + bin_width,
            "quantity_twh": item["quantity"] / 1e9,
            "payment_billion": item["payment"] / 1e9,
            "remaining_billion": item["remaining"] / 1e9,
            "avg_years": avg_years,
            "year_min": min(item["years"]),
            "year_max": max(item["years"]),
            "carriers": item["carriers"],
        })
    rows.sort(key=lambda row: row["remaining_billion"], reverse=True)
    coverage = covered_payment / total_payment * 100 if total_payment else 0.0
    return rows, coverage


def svg_remaining_support(path: Path, rows, coverage: float, bin_width: float, max_rate: float) -> None:
    """Restfoerderung im gleichen Flaechenschema wie Grafik 1.

    y: mengengewichtete EEG-Zahlung der Klasse in ct/kWh
    x/Breite: nominaler Restbetrag in Mrd. EUR
    Farbe/Teilbreite: Energietraeger und sein Anteil am Restbetrag
    """
    shown = [r for r in rows if 0 <= r["lower"] < max_rate and r["remaining_billion"] > 0]
    shown.sort(key=lambda row: row["lower"], reverse=True)
    width, height = 1500, 840
    left, right, top, bottom = 105, 55, 145, 110
    plot_w, plot_h = width - left - right, height - top - bottom
    total_remaining = sum(r["remaining_billion"] for r in shown)
    if total_remaining <= 0:
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="260" viewBox="0 0 1200 260">\n'
            '<rect width="100%" height="100%" fill="white"/>\n'
            '<text x="80" y="70" font-family="sans-serif" font-size="25" font-weight="700">Nominale Restförderung nach EEG-Zahlungsklasse</text>\n'
            '<text x="80" y="120" font-family="sans-serif" font-size="16">Keine auswertbaren positiven Restförderungswerte im gewählten Bereich.</text>\n'
            '<text x="80" y="220" font-family="sans-serif" font-size="11" fill="#555">Quelle: eigene Auswertung der EEG-Jahresabrechnung 2024, Netztransparenz.de.</text>\n'
            '</svg>', encoding="utf-8")
        return

    def py(value):
        return top + (max_rate - value) / max_rate * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{left}" y="38" font-family="sans-serif" font-size="25" font-weight="700">Nominale Restförderung nach EEG-Zahlungsklasse</text>',
        f'<text x="{left}" y="68" font-family="sans-serif" font-size="15" fill="#444">Absteigend nach Zahlungshöhe; Balkenbreite = nominaler Restbetrag (insgesamt {de(total_remaining, 2)} Mrd. €).</text>',
        f'<text x="{left}" y="91" font-family="sans-serif" font-size="12" fill="#555">Jahreskennung deckt {de(coverage)} % der positiven Zahlungen ab; Marktprämien und Sonderlaufzeiten sind keine Festbeträge.</text>',
    ]

    used = {name for row in shown for name, value in row["carriers"].items() if value > 0}
    legend_names = [name for name in ENERGIETRAEGER_REIHENFOLGE if name in used]
    legend_names += sorted(used - set(legend_names))
    legend_x = left
    for name in legend_names:
        color = COLORS.get(name, "#777777")
        parts.extend([
            f'<rect x="{legend_x}" y="108" width="13" height="13" fill="{color}"/>',
            f'<text x="{legend_x + 18}" y="119" font-family="sans-serif" font-size="11">{escape(name)}</text>',
        ])
        legend_x += 32 + max(65, len(name) * 6.4)

    tick_step = 5 if max_rate <= 70 else 10
    tick = 0.0
    while tick <= max_rate + 1e-9:
        y = py(tick)
        stroke = "#777" if abs(tick) < 1e-9 else "#dddddd"
        parts.extend([
            f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" stroke="{stroke}"/>',
            f'<text x="{left - 12}" y="{y + 4:.2f}" text-anchor="end" font-family="sans-serif" font-size="12">{de(tick, 0)}</text>',
        ])
        tick += tick_step

    order = {name: i for i, name in enumerate(ENERGIETRAEGER_REIHENFOLGE)}
    cursor_amount = 0.0
    for row in shown:
        # Tatsächlicher Durchschnittssatz statt bloßer Klassenmitte.
        rate = row["payment_billion"] / row["quantity_twh"] * 100 if row["quantity_twh"] else row["lower"]
        rate = max(0.0, min(max_rate, rate))
        bar_y = py(rate)
        bar_h = max(0.8, py(0.0) - bar_y)
        for name, value_eur in sorted(row["carriers"].items(), key=lambda p: order.get(p[0], 999)):
            value = value_eur / 1e9
            if value <= 0:
                continue
            bar_x = left + cursor_amount / total_remaining * plot_w
            bar_w = value / total_remaining * plot_w
            title = (
                f'{name} · {de(row["lower"])}–{de(row["upper"])} ct/kWh · '
                f'Restbetrag {de(value, 3)} Mrd. € · Ø {de(row["avg_years"])} Restjahre'
            )
            parts.append(
                f'<rect x="{bar_x:.6f}" y="{bar_y:.3f}" width="{bar_w:.6f}" '
                f'height="{bar_h:.3f}" fill="{COLORS.get(name, "#777777")}">'
                f'<title>{escape(title)}</title></rect>'
            )
            cursor_amount += value

    magnitude = 10 ** math.floor(math.log10(total_remaining))
    candidates = [magnitude / 5, magnitude / 2, magnitude, magnitude * 2, magnitude * 5]
    x_step = min(candidates, key=lambda step: abs(total_remaining / step - 6))
    tick = 0.0
    while tick <= total_remaining + 1e-9:
        x = left + tick / total_remaining * plot_w
        parts.extend([
            f'<line x1="{x:.2f}" y1="{top + plot_h}" x2="{x:.2f}" y2="{top + plot_h + 6}" stroke="#222"/>',
            f'<text x="{x:.2f}" y="{top + plot_h + 25}" text-anchor="middle" font-family="sans-serif" font-size="12">{de(tick, 1)}</text>',
        ])
        tick += x_step

    parts.extend([
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#222"/>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#222"/>',
        f'<text x="{left + plot_w / 2}" y="{height - 48}" text-anchor="middle" font-family="sans-serif" font-size="14">Nominaler Restbetrag, geordnet von hoher zu niedriger EEG-Zahlung, in Mrd. €</text>',
        f'<text transform="translate(27 {top + plot_h / 2}) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="14">EEG-Zahlung 2024 in ct/kWh</text>',
        f'<text x="{left}" y="{height - 25}" font-family="sans-serif" font-size="11" fill="#555">Basisszenario: positive Zahlung 2024 × Restjahre; konstante Jahresmenge und Zahlung unterstellt.</text>',
        f'<text x="{left}" y="{height - 9}" font-family="sans-serif" font-size="11" fill="#555">Quelle: eigene Auswertung der EEG-Jahresabrechnung 2024, Netztransparenz.de.</text>',
        '</svg>',
    ])
    path.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(DEFAULT_DB), help="SQLite-Datenbank")
    parser.add_argument("--ausgabe", type=Path, default=Path(DEFAULT_OUTDIR), help="Ausgabeordner")
    parser.add_argument("--klassenbreite", type=float, default=0.5, help="Klassenbreite in ct/kWh")
    parser.add_argument("--min-rate", type=float, default=0.0, help="untere Darstellungsgrenze; negative Werte werden immer ausgeschlossen")
    parser.add_argument("--max-rate", type=float, default=60.0, help="obere Darstellungsgrenze in ct/kWh")
    parser.add_argument("--basisjahr", type=int, default=2024, help="Abrechnungsjahr der Daten")
    args = parser.parse_args()

    args.min_rate = max(0.0, args.min_rate)
    if args.klassenbreite <= 0 or args.max_rate <= args.min_rate:
        parser.error("Ungültige Klassenbreite oder Darstellungsgrenze")
    db = args.db.resolve()
    if not db.is_file():
        raise SystemExit(f"Datenbank nicht gefunden: {db}")
    outdir = args.ausgabe.resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        check_database(con)
        bins = rate_bins(con, args.klassenbreite, args.min_rate, args.max_rate)
        carriers = carrier_rows(con)
        rest_rows, year_coverage = remaining_support_rows(con, args.klassenbreite, args.basisjahr)
        below, above = con.execute(
            """
            SELECT SUM(CASE WHEN payment_ct_kwh < ? THEN quantity_kwh ELSE 0 END) / 1e9,
                   SUM(CASE WHEN payment_ct_kwh >= ? THEN quantity_kwh ELSE 0 END) / 1e9
            FROM eeg_data
            WHERE quantity_kwh > 0 AND payment_eur IS NOT NULL
            """,
            (args.min_rate, args.max_rate),
        ).fetchone()
    finally:
        con.close()

    rate_csv = [
        (lower, lower + args.klassenbreite, carrier, quantity, payment, count)
        for lower, carrier, quantity, payment, count in bins
    ]
    export_csv(
        outdir / "01_strommenge_nach_verguetungshoehe.csv",
        ["Untergrenze_ct_kWh", "Obergrenze_ct_kWh", "Energietraeger", "Strommenge_TWh", "EEG_Zahlung_Mrd_EUR", "Zeilen"],
        rate_csv,
    )
    svg_rate_structure(
        outdir / "01_strommenge_nach_verguetungshoehe.svg",
        bins,
        args.klassenbreite,
        args.min_rate,
        args.max_rate,
    )

    export_csv(
        outdir / "02_eeg_zahlung_nach_energietraeger.csv",
        ["Energietraeger", "EEG_Zahlung_Mrd_EUR", "Strommenge_TWh", "Originalcode"],
        carriers,
    )
    svg_carriers(outdir / "02_eeg_zahlung_nach_energietraeger.svg", carriers)
    rest_csv = []
    for r in rest_rows:
        for name, remaining_eur in sorted(r["carriers"].items()):
            rest_csv.append(
                (r["lower"], r["upper"], name, remaining_eur / 1e9,
                 r["quantity_twh"], r["payment_billion"], r["avg_years"],
                 r["year_min"], r["year_max"], r["remaining_billion"])
            )
    export_csv(
        outdir / "03_nominale_restfoerderung_nach_verguetungshoehe.csv",
        ["Untergrenze_ct_kWh", "Obergrenze_ct_kWh", "Energietraeger",
         "Restbetrag_Energietraeger_Mrd_EUR", "Strommenge_2024_Klasse_TWh",
         "EEG_Zahlung_2024_Klasse_Mrd_EUR", "gewichtete_Restjahre",
         "Kohorte_min", "Kohorte_max", "Restbetrag_Klasse_Mrd_EUR"],
        rest_csv,
    )
    svg_remaining_support(
        outdir / "03_nominale_restfoerderung_nach_verguetungshoehe.svg",
        rest_rows, year_coverage, args.klassenbreite, args.max_rate,
    )
    remove_obsolete_cumulative_files(outdir)

    represented = sum(row[2] for row in bins)
    print(f"EEG-Grafiken aus Datenbank · Version {VERSION}")
    print(f"Datenbank: {db}")
    print(f"Dargestellte Vergütungsmenge: {de(represented, 3)} TWh")
    print(f"Unterhalb {de(args.min_rate)} ct/kWh: {de(below or 0, 3)} TWh")
    print(f"Ab {de(args.max_rate)} ct/kWh: {de(above or 0, 3)} TWh")
    print(f"Abdeckung der Jahreskennung: {de(year_coverage, 2)} % der positiven EEG-Zahlungen")
    print(f"Ausgabe: {outdir}")
    print("Erzeugt: 3 SVG- und 3 gleichnamige CSV-Dateien")


if __name__ == "__main__":
    main()
