# Netztransparenz-Rohdaten 2024

Die Rohdateien und die daraus erzeugte Datenbank werden in diesem Repositorium
nicht weitergegeben. Lade die ZIP-Dateien der EEG-Anlagenstammdaten und
EEG-Bewegungsdaten 2024 manuell von Netztransparenz herunter und lege sie direkt
in diesem Ordner ab.

Quellen:

- https://www.netztransparenz.de/de-de/Erneuerbare-Energien-und-Umlagen/EEG/EEG-Abrechnungen/EEG-Jahresabrechnungen/EEG-Anlagenstammdaten
- https://www.netztransparenz.de/de-de/Erneuerbare-Energien-und-Umlagen/EEG/EEG-Abrechnungen/EEG-Jahresabrechnungen/EEG-Bewegungsdaten

Danach:

```bash
python scripts/netztransparenz_daten_import.py \
  --ordner data/raw/netztransparenz/2024 \
  --jahr 2024 \
  --db data/derived/netztransparenz_eeg.sqlite
```
