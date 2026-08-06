# Klimaleistung und EEG

Dieses Verzeichnis ist das erste analytische Modell im Repository
[`klimagg-tech`](https://github.com/sebapu/klimagg-tech). Es liegt unter
`models/`, weil es Annahmen und Wirkungen einer möglichen gesetzlichen
Ausgestaltung untersucht; es ist weder Gesetzestext noch produktive
Umsetzungssoftware.

Modelle, Daten und Grafiken zum Gastbeitrag **„Wer soll das EEG künftig
bezahlen?“**. Das Modellpaket reproduziert die beiden Publikationsgrafiken und
dokumentiert die Datenbasis, Annahmen und Modellgrenzen.

Grundlagen-Seite:
https://www.klimagg.de/grundlagen/modelle-und-daten/klimaleistung-eeg/

## Inhalt

- EEG-Zahlungsstruktur und rechnerischer zusätzlicher Klimaleistungserlös 2024
- Summen- und Deckungsanalyse der positiven EEG-Zahlungen 2024
- stündliches Angebots-/Nachfrageszenario für streng zugeordneten erneuerbaren
  Strom 2030
- zwei für den Gastbeitrag aufbereitete SVG-/PNG-Grafiken

## Einordnung im Gesamtrepositorium

Das Paket prüft eine konkrete Anwendung des KlimaGG-Prinzips der
**Klimaleistung** auf die Weiterentwicklung der EEG-Finanzierung. Es dient als
reproduzierbare fachliche Grundlage für Gesetzesdiskussion, Artikel und spätere
technische Spezifikationen. Produktionsreife Register-, Abrechnungs- oder
Marktsoftware gehört später in `services/` beziehungsweise `specs/`.

Alle folgenden Befehle werden aus `models/klimaleistung-eeg/` ausgeführt.

## Voraussetzungen

- Python 3.10 oder neuer
- für den Netztransparenz-Import: manuell geladene ZIP-Dateien der
  EEG-Jahresabrechnung 2024

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 1. SMARD-Datenbank

Ein geprüfter Snapshot 2021–2025 ist bereits enthalten. Quelle und Lizenz:
**Bundesnetzagentur | SMARD.de, CC BY 4.0**.

Neu erzeugen:

```bash
python scripts/klimaleistung_zeitreihenkern.py \
  --start 2021 --end 2025 --workers 6 \
  --db data/derived/smard_stundendaten_2021_2025.sqlite
```

## 2. EEG-Datenbank aus Netztransparenz

Die Rohdateien werden aus Lizenz- und Größengründen nicht mitgeliefert. Lade
alle ZIP-Dateien der **Anlagenstammdaten** und **Bewegungsdaten** 2024 manuell
herunter und lege sie in `data/raw/netztransparenz/2024/` ab. Details stehen in
dem dortigen README.

```bash
python scripts/netztransparenz_daten_import.py \
  --ordner data/raw/netztransparenz/2024 \
  --jahr 2024 \
  --db data/derived/netztransparenz_eeg.sqlite
```

## 3. Wetter- und Szenariendatenbank

Das Skript lädt Wetterdaten, speichert Roh- und Modellreihen, prüft die
Vollständigkeit und erzeugt die PV-/Wind-Szenarien für Kassel.

```bash
python scripts/wetterdaten_szenarienverifizierung.py \
  --smard-db data/derived/smard_stundendaten_2021_2025.sqlite \
  --years 2024 \
  --database data/derived/wetterdaten_szenarien.sqlite \
  --out results/generated/wetter_verifikation
```

Der Standard-Standort erhält die ID:
`kassel_51.3127_9.4797_167`.

## 4. Deckungsanalyse 2024

```bash
python scripts/eeg_klimaleistung_deckungsanalyse.py \
  --smard-db data/derived/smard_stundendaten_2021_2025.sqlite \
  --eeg-db data/derived/netztransparenz_eeg.sqlite \
  --core-script scripts/artikelgrafiken_eeg_klimaleistung.py \
  --year 2024 \
  --out results/generated/deckungsanalyse_eeg_klimaleistung_2024.res
```

## 5. Marktmodell 2030

Die Wettertabelle der Szenariendatenbank wird auch für das 2030-Modell genutzt;
eine zweite Wetterdatenbank ist nicht nötig.

```bash
python scripts/klimaleistung_marktmodell_2030.py \
  --smard-db data/derived/smard_stundendaten_2021_2025.sqlite \
  --weather-db data/derived/wetterdaten_szenarien.sqlite \
  --weather-site kassel_51.3127_9.4797_167 \
  --output-dir results/generated/marktmodell_2030
```

## 6. Die zwei finalen Artikelgrafiken

```bash
python scripts/artikelgrafiken_neue_energie.py \
  --smard-db data/derived/smard_stundendaten_2021_2025.sqlite \
  --scenario-db data/derived/wetterdaten_szenarien.sqlite \
  --site-id kassel_51.3127_9.4797_167 \
  --eeg-db data/derived/netztransparenz_eeg.sqlite \
  --weather-db data/derived/wetterdaten_szenarien.sqlite \
  --weather-site kassel_51.3127_9.4797_167 \
  --out results/generated/artikelgrafiken
```

Erzeugt werden:

- `01_eeg_zahlungen_und_klimaleistung.svg/.png`
- `02_stuendlicher_klimaleistungsmarkt_2030.svg/.png`
- `BILDTEXTE_UND_METHODIK.md`

Die aktuell im Artikel verwendeten Ausgaben liegen unter
`results/article_figures/`.

## Prüfungen

```bash
python -m py_compile scripts/*.py
sha256sum -c CHECKSUMS.sha256
```

Jedes Importskript prüft Vollständigkeit und SQLite-Integrität. Die
Szenarien- und Auswertungsskripte brechen bei fehlenden Stunden, fehlenden
Spalten oder widersprüchlichen Jahren ab.

## Daten, Lizenzen und Grenzen

- `docs/DATENQUELLEN_UND_LIZENZEN.md`
- `docs/REPRODUZIERBARKEIT.md`
- `docs/METHODIK_ARTIKELGRAFIKEN.md`
- `docs/METHODIK_MARKTMODELL_2030.md`

Der Quellcode steht unter **Apache-2.0**. Eigene Grafiken, Dokumentation und
autorseitig erzeugte Ergebnisdateien stehen, soweit nicht anders angegeben,
unter **CC BY 4.0**. Beide Lizenzen erlauben Nutzung, Bearbeitung und
Weitergabe; Copyright- und Namensnennungen sind beizubehalten. Details:
[`LICENSES.md`](LICENSES.md).
