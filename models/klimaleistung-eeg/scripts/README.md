# Skripte und Abhängigkeiten

## Datenbanken erzeugen

1. `klimaleistung_zeitreihenkern.py` → `smard_stundendaten_2021_2025.sqlite`
2. `netztransparenz_daten_import.py` → `netztransparenz_eeg.sqlite`
3. `wetterdaten_szenarienverifizierung.py` → `wetterdaten_szenarien.sqlite`

## Auswertung

- `artikelgrafiken_eeg_klimaleistung.py`: 2024-Referenzfälle, Marktwert,
  Klimaleistung und EEG-Bandbreiten.
- `eeg_klimaleistung_deckungsanalyse.py`: Summen- und Deckungsanalyse als
  `.res`-Bericht.
- `klimaleistung_marktmodell_2030.py`: stündliches Angebots-/Nachfragemodell
  2030.
- `netztransparenz_grafiken.py`: EEG-Zahlungsstruktur und Hilfsfunktionen.
- `artikelgrafiken_neue_energie.py`: erzeugt die zwei finalen
  Publikationsgrafiken und importiert die drei vorgenannten Rechenmodule.

Alle vier Rechenmodule müssen für die finale Publikationsgrafik im selben
Verzeichnis liegen. Das ist in dieser Struktur erfüllt.
