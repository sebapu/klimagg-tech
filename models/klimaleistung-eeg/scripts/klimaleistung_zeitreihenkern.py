#!/usr/bin/env python3
# Copyright (c) 2026 Sebastian Putzke
# SPDX-License-Identifier: Apache-2.0
"""SMARD-Stundenreihen neu laden, prüfen und in genau eine SQLite schreiben.

Keine Grafiken, Modellannahmen, Emissionsfaktoren, Referenzfälle oder Cache-Dateien.
Python 3.10+, Standardbibliothek. Beispiel:
  python3 klimaleistung_zeitreihenkern.py --start 2021 --end 2025
"""
from __future__ import annotations

import argparse, json, math, os, sqlite3, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "2.0.0"
BASE = "https://www.smard.de/app/chart_data"
REGION, RESOLUTION = "DE", "hour"
SERIES = {
    "load_mwh": ("410", "Realisierter Stromverbrauch"),
    "price_eur_mwh": ("4169", "Day-Ahead-Preis Deutschland/Luxemburg"),
    "lignite_mwh": ("1223", "Braunkohle"), "nuclear_mwh": ("1224", "Kernenergie"),
    "wind_offshore_mwh": ("1225", "Wind Offshore"), "hydro_mwh": ("1226", "Wasserkraft"),
    "other_conventional_mwh": ("1227", "Sonstige Konventionelle"),
    "other_renewable_mwh": ("1228", "Sonstige Erneuerbare"),
    "biomass_mwh": ("4066", "Biomasse"), "wind_onshore_mwh": ("4067", "Wind Onshore"),
    "pv_mwh": ("4068", "Photovoltaik"), "hard_coal_mwh": ("4069", "Steinkohle"),
    "pumped_storage_generation_mwh": ("4070", "Pumpspeicher-Erzeugung"),
    "gas_mwh": ("4071", "Erdgas"),
}
NUCLEAR_ZERO_FROM_MS = int(datetime(2023, 4, 16, tzinfo=timezone.utc).timestamp() * 1000)

def get_json(url, attempts=6):
    last = None
    for n in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"smard-sqlite/{VERSION}"})
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc; time.sleep(min(10, .5 * 2**n))
    raise RuntimeError(f"Abruf fehlgeschlagen: {url}\n{last}")

def package_stamps(filter_id, start_ms, end_ms):
    data = get_json(f"{BASE}/{filter_id}/{REGION}/index_{RESOLUTION}.json")
    stamps = data.get("timestamps")
    if not isinstance(stamps, list): raise RuntimeError(f"Ungültiger SMARD-Index für Filter {filter_id}")
    margin = 8 * 24 * 3600_000
    return [int(x) for x in stamps if start_ms - margin <= int(x) < end_ms]

def fetch_package(filter_id, stamp):
    url = f"{BASE}/{filter_id}/{REGION}/{filter_id}_{REGION}_{RESOLUTION}_{stamp}.json"
    rows = get_json(url).get("series")
    if not isinstance(rows, list): raise RuntimeError(f"Ungültiges SMARD-Paket: {url}")
    return rows

def download(start_ms, end_ms, workers):
    tasks = []
    for name, (fid, _) in SERIES.items():
        for stamp in package_stamps(fid, start_ms, end_ms): tasks.append((name, fid, stamp))
    values = {name: {} for name in SERIES}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(fetch_package, fid, stamp): name for name, fid, stamp in tasks}
        for done, future in enumerate(as_completed(pending), 1):
            name = pending[future]
            for item in future.result():
                if not isinstance(item, list) or len(item) < 2: continue
                ts, value = int(item[0]), item[1]
                if start_ms <= ts < end_ms:
                    if ts in values[name]: raise RuntimeError(f"Doppelter Zeitstempel in {name}: {ts}")
                    values[name][ts] = None if value is None else float(value)
            if done % 250 == 0 or done == len(tasks): print(f"Wochenpakete {done:4d} / {len(tasks)}", flush=True)
    return values, len(tasks)

def validate(values, start_ms, end_ms):
    expected = list(range(start_ms, end_ms, 3600_000)); expected_set = set(expected)
    report, errors = [], []
    for name in SERIES:
        series = values[name]
        extra = set(series) - expected_set
        if extra: errors.append(f"{name}: {len(extra)} Zeitstempel außerhalb des Zeitraums")
        missing, nulls, invalid, negative = [], [], [], []
        for ts in expected:
            value = series.get(ts)
            if name == "nuclear_mwh" and ts >= NUCLEAR_ZERO_FROM_MS and value is None:
                series[ts] = 0.0; value = 0.0
            if ts not in series: missing.append(ts)
            elif value is None: nulls.append(ts)
            elif not math.isfinite(value): invalid.append(ts)
            elif name != "price_eur_mwh" and value < 0: negative.append(ts)
        status = "ok" if not (missing or nulls or invalid or negative) else "error"
        report.append((name, len(expected), len(series), len(missing), len(nulls), len(invalid), len(negative), status))
        if status == "error": errors.append(f"{name}: missing={len(missing)}, null={len(nulls)}, invalid={len(invalid)}, negative={len(negative)}")
    if errors: raise RuntimeError("SMARD-Datenprüfung fehlgeschlagen:\n- " + "\n- ".join(errors))
    return expected, report

def write_db(target, timestamps, values, report, start, end, packages):
    target = target.resolve(); target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    if temp.exists(): temp.unlink()
    con = sqlite3.connect(temp)
    try:
        cols = list(SERIES)
        con.executescript("""
          PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL;
          CREATE TABLE hourly(timestamp_ms INTEGER PRIMARY KEY, timestamp_utc TEXT NOT NULL,
            timestamp_berlin TEXT NOT NULL, local_year INTEGER NOT NULL);
          CREATE TABLE series_metadata(column_name TEXT PRIMARY KEY, smard_filter_id TEXT NOT NULL,
            label TEXT NOT NULL, unit TEXT NOT NULL);
          CREATE TABLE validation(series TEXT PRIMARY KEY, expected_hours INTEGER, stored_timestamps INTEGER,
            missing_values INTEGER, null_values INTEGER, invalid_values INTEGER, negative_values INTEGER, status TEXT);
          CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        for col in cols: con.execute(f'ALTER TABLE hourly ADD COLUMN "{col}" REAL NOT NULL')
        berlin = ZoneInfo("Europe/Berlin")
        sql = f"INSERT INTO hourly VALUES ({','.join('?' for _ in range(4+len(cols)))})"
        batch=[]
        for ts in timestamps:
            utc=datetime.fromtimestamp(ts/1000, timezone.utc); local=utc.astimezone(berlin)
            batch.append((ts, utc.isoformat(), local.isoformat(), local.year, *(values[c][ts] for c in cols)))
            if len(batch)>=5000: con.executemany(sql,batch); batch.clear()
        if batch: con.executemany(sql,batch)
        con.executemany("INSERT INTO series_metadata VALUES (?,?,?,?)", [(c,*SERIES[c],"EUR/MWh" if c=="price_eur_mwh" else "MWh") for c in cols])
        con.executemany("INSERT INTO validation VALUES (?,?,?,?,?,?,?,?)", report)
        con.executemany("INSERT INTO metadata VALUES (?,?)", [("script_version",VERSION),("period",f"{start}-{end}"),("timezone","Europe/Berlin"),("resolution","hour"),("downloaded_packages",str(packages)),("created_utc",datetime.now(timezone.utc).isoformat())])
        con.execute("CREATE INDEX hourly_local_year ON hourly(local_year)")
        con.commit(); result=con.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok": raise RuntimeError(f"SQLite integrity_check: {result}")
        con.execute("VACUUM")
    except Exception:
        con.close(); temp.unlink(missing_ok=True); raise
    else: con.close(); os.replace(temp,target)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start",type=int,default=2021); p.add_argument("--end",type=int,default=2025)
    p.add_argument("--workers",type=int,default=6); p.add_argument("--db",type=Path,default=Path("smard_stundendaten.sqlite"))
    a=p.parse_args()
    if a.start>a.end: p.error("--start darf nicht nach --end liegen")
    if not 1<=a.workers<=16: p.error("--workers muss zwischen 1 und 16 liegen")
    berlin=ZoneInfo("Europe/Berlin")
    start_ms=int(datetime(a.start,1,1,tzinfo=berlin).timestamp()*1000); end_ms=int(datetime(a.end+1,1,1,tzinfo=berlin).timestamp()*1000)
    values,packages=download(start_ms,end_ms,a.workers); timestamps,report=validate(values,start_ms,end_ms)
    for row in report: print(f"{row[0]:34s} {row[7]} ({row[1]} Stunden)")
    write_db(a.db,timestamps,values,report,a.start,a.end,packages)
    print(f"Fertig: {a.db.resolve()} ({len(timestamps)} Stunden)")

if __name__ == "__main__": main()
