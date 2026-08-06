# Datenquellen und Weitergabe

Diese Datei dokumentiert die konservative Weitergabepraxis des Repositoriums.
Sie ist keine Rechtsberatung.

## SMARD

Die Marktdaten von SMARD stehen ausdrücklich unter **CC BY 4.0** und dürfen
geteilt sowie bearbeitet werden. Vorgeschriebene Namensnennung:
**„Bundesnetzagentur | SMARD.de“**.

- Datennutzung: https://www.smard.de/home/datennutzung
- Download: https://www.smard.de/home/downloadcenter/download-marktdaten

Daher ist der SQLite-Snapshot `data/derived/smard_stundendaten_2021_2025.sqlite`
im Paket enthalten.

## Netztransparenz / EEG-Jahresabrechnung

Die EEG-Anlagenstamm- und Bewegungsdaten werden öffentlich zum Download
bereitgestellt. Im Impressum von Netztransparenz ist jedoch keine offene
Datenlizenz ausgewiesen; die Vervielfältigung von Seiten oder Inhalten wird
unter einen Zustimmungsvorbehalt gestellt. Zusätzlich überschreitet die lokal
erzeugte Datenbank die GitHub-Dateigrenze von 100 MB.

Daher werden weder Roh-ZIPs noch `netztransparenz_eeg.sqlite` weitergegeben.
Das Repositorium enthält nur den Importer und eine Anleitung zum manuellen
Download.

- Bewegungsdaten: https://www.netztransparenz.de/de-de/Erneuerbare-Energien-und-Umlagen/EEG/EEG-Abrechnungen/EEG-Jahresabrechnungen/EEG-Bewegungsdaten
- Anlagenstammdaten: https://www.netztransparenz.de/de-de/Erneuerbare-Energien-und-Umlagen/EEG/EEG-Abrechnungen/EEG-Jahresabrechnungen/EEG-Anlagenstammdaten
- Impressum: https://www.netztransparenz.de/de-de/Impressum

## Meteostat und Wetterdaten

Von Meteostat weiterverteilte Wetterdaten stehen grundsätzlich unter
**CC BY 4.0**. Meteostat verlangt die Nennung von Meteostat und den
meteorologischen Datenanbietern. Die Dokumentation weist zugleich darauf hin,
dass bei einem direkten Bezug über einen Wetterdienst dessen Lizenz geprüft
werden muss.

- Lizenz: https://dev.meteostat.net/license

Die Wetter-/Szenariendatenbank wird deshalb im Hauptrepository nicht als
Binärdatei mitgeliefert. Sie kann mit dem enthaltenen Skript neu erzeugt werden.
Für Veröffentlichungen ist mindestens folgende Namensnennung vorgesehen:
**„Quelle: Meteostat und seine Datenanbieter“**; soweit der konkrete Anbieter
ermittelt ist, wird er zusätzlich genannt.

## UBA, UNECE, JEC, PVGIS, WindGuard und weitere Quellen

Diese Quellen werden für einzelne Faktoren, Referenzwerte und Modellannahmen
zitiert. Ihre PDFs und Datensätze werden nicht in das Repositorium kopiert.
Die verwendeten Werte, URLs und Bilanzgrenzen sind in den Skripten und den
Methodikdateien dokumentiert.

## Eigene Ergebnisse

Die eigenen Grafiken und Methodiktexte stehen, soweit gekennzeichnet, unter
CC BY 4.0. Die zugrunde liegenden Drittdaten behalten ihre jeweiligen Rechte
und Quellenangaben.
