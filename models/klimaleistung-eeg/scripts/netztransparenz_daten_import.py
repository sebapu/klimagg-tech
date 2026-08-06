#!/usr/bin/env python3
# Copyright (c) 2026 Sebastian Putzke
# SPDX-License-Identifier: Apache-2.0
"""Lokale Netztransparenz-ZIP-Dateien prüfen und kompakt in SQLite speichern.

Kein Download, keine Grafiken, keine CSV-Zwischendateien.
"""
from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import io
import os
import re
import sqlite3
import sys
import zipfile
from collections import Counter
from pathlib import Path

VERSION = "1.1.1"


def norm(value: object) -> str:
    text = str(value or "").strip().lower()
    text = text.translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


ALIASES = {
    "key": ("eeg_anlagenschluessel", "eeg_anlagen_schluessel", "anlagenschluessel"),
    "mastr": ("eeg_mastr_nr", "mastr_nr", "mastrnummer", "einheitmastrnummer"),
    "carrier": ("energietraeger", "energietraeger_code"),
    "category": ("verguetungskategorie", "eeg_verguetungskategorie", "foerderkategorie"),
    "sale_form": ("veraeusserungsform", "vermarktungsform"),
    "month": ("monat", "abrechnungsmonat"),
    "quantity": ("strommenge", "strommenge_kwh", "arbeit", "eeg_strommenge"),
    "payment": ("eeg_zahlung", "eeg_zahlungen", "zahlung"),
    "revenue": ("eeg_einnahmen", "eeg_einnahme", "einnahmen", "markterloes"),
    "power": ("installierte_leistung", "installierte_leistung_kw", "leistung", "nennleistung"),
}
ALIASES = {key: tuple(norm(x) for x in values) for key, values in ALIASES.items()}


def column_map(header: list[str]) -> dict[str, int | None]:
    available = {norm(name): index for index, name in enumerate(header)}
    return {
        role: next((available[name] for name in names if name in available), None)
        for role, names in ALIASES.items()
    }


def parse_number(value: object) -> float | None:
    text = str(value or "").strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def get(row: list[str], columns: dict[str, int | None], role: str) -> str:
    index = columns.get(role)
    return row[index].strip() if index is not None and index < len(row) else ""


def get_number(row: list[str], columns: dict[str, int | None], role: str) -> float | None:
    return parse_number(get(row, columns, role))


def member_decodes(archive: zipfile.ZipFile, item: zipfile.ZipInfo, encoding: str) -> bool:
    """Die komplette Datei prüfen, ohne sie vollständig in den Speicher zu laden."""
    decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    try:
        with archive.open(item) as handle:
            while chunk := handle.read(1024 * 1024):
                decoder.decode(chunk, final=False)
            decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return False
    return True


def csv_format(archive: zipfile.ZipFile, item: zipfile.ZipInfo) -> tuple[str, str]:
    """Kodierung vollständig validieren und Trennzeichen aus einer Probe erkennen."""
    with archive.open(item) as handle:
        sample = handle.read(65536)

    if sample.startswith(codecs.BOM_UTF8):
        candidates = ("utf-8-sig", "cp1252", "latin-1")
    else:
        candidates = ("utf-8", "cp1252", "latin-1")

    encoding = next(
        (candidate for candidate in candidates if member_decodes(archive, item, candidate)),
        None,
    )
    if encoding is None:
        raise UnicodeError(
            f"{item.filename}: weder UTF-8 noch Windows-1252/ISO-8859-1 lesbar"
        )
    try:
        delimiter = csv.Sniffer().sniff(sample.decode(encoding), delimiters=";,\t|").delimiter
    except (csv.Error, UnicodeDecodeError):
        delimiter = ";"
    return encoding, delimiter


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=NORMAL;
        PRAGMA temp_store=MEMORY;
        CREATE TABLE master (
            eeg_key TEXT, mastr TEXT, carrier TEXT, power_kw REAL
        );
        CREATE TABLE movement (
            eeg_key TEXT, mastr TEXT, category TEXT, sale_form TEXT, month TEXT,
            quantity_kwh REAL, payment_eur REAL, revenue_eur REAL, carrier_direct TEXT
        );
        CREATE TABLE source_files (
            id INTEGER PRIMARY KEY, archive TEXT NOT NULL, member TEXT NOT NULL,
            kind TEXT NOT NULL, sha256 TEXT NOT NULL, archive_bytes INTEGER NOT NULL,
            rows INTEGER NOT NULL, columns TEXT NOT NULL, encoding TEXT NOT NULL,
            delimiter TEXT NOT NULL, status TEXT NOT NULL
        );
        CREATE TABLE validation (
            check_name TEXT PRIMARY KEY, value TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('ok','warning','error')), note TEXT NOT NULL
        );
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)


def classify(columns: dict[str, int | None]) -> str:
    if columns["quantity"] is not None and columns["payment"] is not None:
        return "movement"
    if columns["carrier"] is not None and (columns["key"] is not None or columns["mastr"] is not None):
        return "master"
    return "ignored"


def import_archive(connection: sqlite3.Connection, path: Path) -> Counter:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    counts: Counter = Counter()
    with zipfile.ZipFile(path) as archive:
        members = [item for item in archive.infolist()
                   if not item.is_dir() and Path(item.filename).suffix.lower() in {".csv", ".txt", ".tsv"}]
        if not members:
            raise RuntimeError(f"Keine CSV-/TXT-Datei in {path.name}")
        for item in members:
            encoding, delimiter = csv_format(archive, item)
            with archive.open(item) as handle:
                reader = csv.reader(io.TextIOWrapper(handle, encoding=encoding, errors="strict", newline=""), delimiter=delimiter)
                try:
                    header = next(reader)
                except StopIteration:
                    header = []
                columns = column_map(header)
                kind = classify(columns)
                rows = 0
                batch: list[tuple] = []
                for row in reader:
                    if kind == "ignored" or not any(cell.strip() for cell in row):
                        continue
                    rows += 1
                    if kind == "master":
                        batch.append((get(row, columns, "key"), get(row, columns, "mastr"),
                                      get(row, columns, "carrier"), get_number(row, columns, "power")))
                    else:
                        batch.append((get(row, columns, "key"), get(row, columns, "mastr"),
                                      get(row, columns, "category"), get(row, columns, "sale_form"),
                                      get(row, columns, "month"), get_number(row, columns, "quantity"),
                                      get_number(row, columns, "payment"), get_number(row, columns, "revenue"),
                                      get(row, columns, "carrier")))
                    if len(batch) >= 50_000:
                        connection.executemany("INSERT INTO master VALUES (?,?,?,?)" if kind == "master"
                                               else "INSERT INTO movement VALUES (?,?,?,?,?,?,?,?,?)", batch)
                        batch.clear()
                if batch:
                    connection.executemany("INSERT INTO master VALUES (?,?,?,?)" if kind == "master"
                                           else "INSERT INTO movement VALUES (?,?,?,?,?,?,?,?,?)", batch)
                status = "ok" if kind != "ignored" else "ignored"
                connection.execute(
                    "INSERT INTO source_files(archive,member,kind,sha256,archive_bytes,rows,columns,encoding,delimiter,status) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (path.name, item.filename, kind, digest, path.stat().st_size, rows,
                     " | ".join(header), encoding, delimiter, status),
                )
                counts[kind] += rows
                counts[f"encoding:{encoding}"] += 1
    return counts


def aggregate(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE INDEX master_key_idx ON master(eeg_key);
        CREATE INDEX master_mastr_idx ON master(mastr);
        CREATE INDEX movement_key_idx ON movement(eeg_key);
        CREATE INDEX movement_mastr_idx ON movement(mastr);
        CREATE TEMP TABLE carrier_by_key AS
          SELECT eeg_key, MIN(NULLIF(carrier,'')) AS carrier
          FROM master WHERE eeg_key <> '' GROUP BY eeg_key;
        CREATE INDEX carrier_by_key_idx ON carrier_by_key(eeg_key);
        CREATE TEMP TABLE carrier_by_mastr AS
          SELECT mastr, MIN(NULLIF(carrier,'')) AS carrier
          FROM master WHERE mastr <> '' GROUP BY mastr;
        CREATE INDEX carrier_by_mastr_idx ON carrier_by_mastr(mastr);

        CREATE TABLE eeg_data AS
        SELECT
          COALESCE(NULLIF(m.carrier_direct,''), k.carrier, r.carrier, 'nicht zugeordnet') AS carrier,
          m.category, m.sale_form, m.month,
          ROUND(m.payment_eur / NULLIF(m.quantity_kwh, 0) * 100.0, 6) AS payment_ct_kwh,
          SUM(m.quantity_kwh) AS quantity_kwh,
          SUM(m.payment_eur) AS payment_eur,
          SUM(m.revenue_eur) AS revenue_eur,
          COUNT(*) AS source_rows
        FROM movement AS m
        LEFT JOIN carrier_by_key AS k ON m.eeg_key <> '' AND m.eeg_key = k.eeg_key
        LEFT JOIN carrier_by_mastr AS r ON (m.eeg_key = '' OR k.eeg_key IS NULL) AND m.mastr <> '' AND m.mastr = r.mastr
        GROUP BY 1,2,3,4,5;

        DROP TABLE movement;
        DROP TABLE master;
        CREATE INDEX eeg_data_carrier_idx ON eeg_data(carrier);
        CREATE INDEX eeg_data_rate_idx ON eeg_data(payment_ct_kwh);
        CREATE INDEX eeg_data_category_idx ON eeg_data(category);
    """)


def format_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ordner", type=Path, default=Path.cwd(), help="Ordner mit den manuell geladenen ZIP-Dateien")
    parser.add_argument("--jahr", type=int, required=True, help="Abrechnungsjahr, z. B. 2024")
    parser.add_argument("--db", type=Path, default=Path("netztransparenz_eeg.sqlite"), help="Ziel-Datenbank")
    args = parser.parse_args()

    source_dir = args.ordner.resolve()
    archives = sorted(source_dir.glob("*.zip"))
    if not archives:
        parser.error(f"Keine ZIP-Dateien direkt in {source_dir} gefunden")
    target = args.db.resolve()
    temporary = target.with_name(target.name + ".tmp")
    temporary.unlink(missing_ok=True)

    print(f"Netztransparenz-Import {VERSION}")
    print(f"Quelle:     {source_dir}")
    print(f"ZIP-Dateien:{len(archives):>9}")
    print(f"Ziel:       {target}")
    connection = sqlite3.connect(temporary)
    totals: Counter = Counter()
    try:
        create_schema(connection)
        for index, archive in enumerate(archives, 1):
            print(f"[{index:>2}/{len(archives)}] {archive.name}", flush=True)
            totals.update(import_archive(connection, archive))
            connection.commit()
        if totals["master"] == 0 or totals["movement"] == 0:
            raise RuntimeError(f"Stamm- und Bewegungsdaten erforderlich; erkannt: {dict(totals)}")
        print("Verdichte und verknüpfe Daten …", flush=True)
        aggregate(connection)
        total_rows = int(connection.execute("SELECT COALESCE(SUM(source_rows),0) FROM eeg_data").fetchone()[0])
        unassigned = int(connection.execute(
            "SELECT COALESCE(SUM(source_rows),0) FROM eeg_data WHERE carrier='nicht zugeordnet'"
        ).fetchone()[0])
        invalid_quantity = int(connection.execute(
            "SELECT COALESCE(SUM(source_rows),0) FROM eeg_data WHERE quantity_kwh IS NULL"
        ).fetchone()[0])
        checks = [
            ("master_rows", str(totals["master"]), "ok", "eingelesene Stammdatenzeilen"),
            ("movement_rows", str(totals["movement"]), "ok", "eingelesene Bewegungsdatenzeilen"),
            ("unassigned_rows", str(unassigned), "ok" if unassigned == 0 else "warning",
             f"{unassigned / total_rows:.3%} der Bewegungszeilen" if total_rows else "keine Bewegungszeilen"),
            ("invalid_quantity_rows", str(invalid_quantity), "ok" if invalid_quantity == 0 else "warning",
             "Zeilen ohne lesbare Strommenge"),
        ]
        connection.executemany("INSERT INTO validation VALUES (?,?,?,?)", checks)
        connection.executemany("INSERT INTO metadata VALUES (?,?)", [
            ("script_version", VERSION), ("year", str(args.jahr)),
            ("source", "Netztransparenz.de, lokale Jahresabrechnungs-ZIP-Dateien"),
        ])
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite-Integritätsprüfung: {integrity}")
        connection.execute("VACUUM")
        connection.close()
        os.replace(temporary, target)
    except Exception:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise

    size_mib = target.stat().st_size / 1024**2
    print("Prüfung abgeschlossen")
    print(f"Stammzeilen:       {format_int(totals['master'])}")
    print(f"Bewegungszeilen:   {format_int(totals['movement'])}")
    print(f"Nicht zugeordnet:  {format_int(unassigned)} ({unassigned / total_rows:.3%})")
    encodings = ", ".join(
        f"{key.removeprefix('encoding:')} ({value})"
        for key, value in sorted(totals.items()) if key.startswith("encoding:")
    )
    print(f"Kodierungen:        {encodings}")
    print(f"Datenbankgröße:    {size_mib:.1f} MiB")
    print(f"Fertig: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
