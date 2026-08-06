# Stündlicher Wert THG-freien Stroms 2030

## Aussage der Grafik

Die Grafik ist **keine Marktpreisprognose**. Sie zeigt einen ersten, transparenten Modelllauf dafür, warum nachweislich THG-freier Strom trotz ausreichender Jahreserzeugung einen stündlich unterschiedlichen Wert besitzt.

**Feld A** sortiert die 8.760 Jahresstunden nach der anbieterseitigen Preisuntergrenze. Diese wird aus den für 2030 prognostizierten EEG-Förderlücken der jeweils zuletzt benötigten Angebotsstufe abgeleitet und anschließend mit dem stündlichen fossilen Restmix in Euro je Tonne CO₂e umgerechnet. Die gelbe Linie markiert beispielhaft einen staatlichen Mindestpreis von **74 €/t CO₂e**. Der gelbe Bereich darunter ist ein möglicher Aufstockungsbereich, nicht bereits eine berechnete Haushaltsausgabe.

In den schraffierten Knappheitsstunden reicht das modellierte THG-freie Angebot nicht aus. Dort kann aus den vorhandenen Angeboten kein Preis bestimmt werden; dafür wären Speicher, gesicherte THG-freie Erzeugung, Importe oder Lastverschiebung nötig.

**Feld B** sortiert dieselben Stunden separat nach `THG-freies Angebot − strenge 24/7-Nachfrage`. Positive Werte zeigen Überschuss, negative Werte Unterdeckung. Weil beide Felder unterschiedlich sortiert sind, dürfen ihre Punkte nicht horizontal miteinander verbunden werden.

## Optimistische Nachfrageannahme 2030

Das Szenario ist bewusst optimistisch. Es soll prüfen, ob auch bei einem starken Markthochlauf noch stündliche Knappheit und damit ein eigenständiger Wert der Klimaleistung bestehen.

| Nachfragegruppe | 2030 [TWh] | Annahme |
|---|---:|---|
| RFNBO-Elektrolyse | 40,000 | 10 GW × 4.000 Volllaststunden; hohes Zielerreichungsszenario |
| Rechenzentren / Cloud / KI | 15,500 | 31 TWh Gesamtverbrauch 2030 × 50 % strenger Nachweis |
| Öffentliche Hand | 18,000 | 18 TWh geschätzter öffentlicher Stromverbrauch × 100 % |
| DB-Traktionsstrom / öffentliche Beteiligung | 5,738 | 7,172 TWh Traktionsstrom × 80 % erneuerbarer Bahnstrom 2030 |
| 25 % heutige Haushalts-Ökostrommenge | 18,500 | 74,0 TWh Ökostrom 2024 × 25 % Umstieg |
| 25 % heutige Ökostrommenge weiterer Letztverbraucher | 15,625 | 62,5 TWh Ökostrom 2024 × 25 % Umstieg |
| **Summe ohne Fernwärme** | **113,363** | |
| Fernwärme-Großwärmepumpen | 20,658 | 30 % von 156 TWh Fernwärmeerzeugung; temperaturabhängiger COP bei 90 °C Vorlauf |
| **Gesamte strenge Nachfrage** | **134,021** | optimistisches Markthochlauf-Szenario |

Die Annahme von **25 % Ökostromkunden** wird als 25 % der 2024 gelieferten Ökostrommenge modelliert: 18,5 TWh Haushalte und 15,625 TWh weitere Letztverbraucher. Unterstellt wird, dass der zusätzliche Aufpreis für einen stündlichen Nachweis moderat genug ist, um diesen hohen Umstieg bis 2030 zu tragen. Das ist eine transparente Annahme, keine beobachtete Prognose.

Die Ökostromstatistik trennt die weiteren Letztverbraucher nicht nach privaten Unternehmen, öffentlicher Hand, DB oder Rechenzentren. Das Bruttoszenario kann deshalb Doppelzählungen enthalten. In einer ersten Überschneidungssensitivität werden 25 % der separat erfassten Rechenzentrums-, öffentlichen und DB-Last abgezogen. Die Nachfrage sinkt dann auf **124,211 TWh**, die Unterdeckung auf **578 Stunden beziehungsweise 1,768 TWh**.

## Ergebnis des Modelllaufs

- THG-freies Angebot: **464,50 TWh**.
- Strenge 24/7-Nachfrage: **134,02 TWh**.
- Unterdeckung: **668 Stunden beziehungsweise 2,427 TWh**.
- Maximale stündliche Unterdeckung: **11,358 GW**.
- Stunden mit bestimmbarer Preisuntergrenze unter 74 €/t: **7619**.
- Stunden mit bestimmbarer Preisuntergrenze mindestens auf Mindestpreishöhe: **473**.

## Methodische Grenzen

Die Preislinie bildet nur die **Angebotsseite** ab. Ein tatsächlicher Marktpreis benötigt reale Käufergebote. Die Erzeugungsprofile stammen aus dem Wetter- und Einspeisejahr 2024, der 29. Februar wurde entfernt und die Profile wurden auf die für 2030 angenommenen Jahresmengen skaliert. Die Umrechnung in Euro je Tonne nutzt den stündlichen fossilen Restmix 2024 einschließlich der im Klimaleistungsmodell dokumentierten Vorkettenaufschläge. Ein eigener fossiler Restmix 2030, mehrere Wetterjahre, Speicher, Importe und reale Lastflexibilität sind noch nicht enthalten.

## Quellen

- **EEG-Mittelfristprognose 2026–2030, Trendszenario**: Erzeugungsmengen, Veräußerungsformen, Basepreis und Marktwertfaktoren 2030. IE Leipzig, r2b und Übertragungsnetzbetreiber.  https://www.netztransparenz.de/xspproxy/api/staticfiles/ntp-relaunch/dokumente/erneuerbare%20energien%20und%20umlagen/eeg/eeg%20finanzierung/mittelfristprognose/2026-2030/20251015_endbericht%20ie%20leipzig.pdf
- **SMARD-Stundendaten 2024**: relative Einspeiseprofile und fossiler Restmix; lokale SQLite-Datenbank des Projekts. Datenquelle: Bundesnetzagentur/SMARD. https://www.smard.de/
- **Monitoringbericht Energie 2025**: 74,0 TWh Ökostrom an Haushalte und 62,5 TWh an weitere Letztverbraucher im Jahr 2024. Bundesnetzagentur und Bundeskartellamt.  https://data.bundesnetzagentur.de/Bundesnetzagentur/SharedDocs/Mediathek/Monitoringberichte/MonitoringberichtEnergie2025.pdf
- **Deutsche Bahn, Integrierter Bericht 2024**: 7.172 GWh Traktionsstrom; Ziel von 80 % erneuerbarem Bahnstrom bis 2030.  https://ibir.deutschebahn.com/2024/de/zusammengefasster-lagebericht/entwicklung-der-geschaeftsfelder/geschaeftsfeld-db-energie/entwicklung-im-berichtsjahr/
- **Rechenzentren in Deutschland**: prognostizierter Strombedarf von 31 TWh im Jahr 2030. Bundeswirtschaftsministerium.  https://www.bundeswirtschaftsministerium.de/Redaktion/DE/Publikationen/Technologie/stand-und-entwicklung-des-rechenzentrumsstandorts-deutschland.pdf?__blob=publicationFile&v=1
- **Delegierte Verordnung (EU) 2023/1184**: zeitliche Korrelation für RFNBO-Strom ab 2030.  https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32023R1184
- **Fernwärme und Großwärmepumpen**: UBA-Potenzialanalyse, Wärmeplanungsgesetz § 29 sowie Agora Energiewende/Fraunhofer IEG zur Auslegung großer Wärmepumpen.  https://www.umweltbundesamt.de/system/files/medien/1410/publikationen/2021-08-05_cc_54-2021_effiziente_waerme-kaelteversorgung.pdf  
https://www.gesetze-im-internet.de/wpg/__29.html  
https://www.agora-energiewende.de/fileadmin/Projekte/2022/2022-11_DE_Large_Scale_Heatpumps/A-EW_293_Rollout_Grosswaermepumpen_WEB.pdf

## Urheberrecht und Lizenz

Grafik © Sebastian Putzke 2026. Freigegeben unter **CC BY 4.0**: freie Weitergabe und Bearbeitung, auch kommerziell, bei angemessener Namensnennung, Link auf die Lizenz und Kennzeichnung von Änderungen. Lizenz: https://creativecommons.org/licenses/by/4.0/
