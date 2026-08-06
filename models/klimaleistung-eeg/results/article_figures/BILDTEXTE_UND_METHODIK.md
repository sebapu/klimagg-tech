# Bildtexte und Methodik – Gastbeitrag Klimaleistung

Erzeugt mit `artikelgrafiken_neue_energie.py` Version 1.0.1.

## Abbildung 1 – EEG-Zahlungen und Klimaleistung

**Kurzbildtext**

Die bestehende EEG-Förderung verteilt sehr unterschiedliche Zahlungen auf die geförderten Strommengen. Die zweite Teilgrafik stellt diesen historischen Erlösen den stündlichen Marktwert und eine zusätzliche Klimaleistung bei 50, 100 und 150 Euro je Tonne CO₂e gegenüber.

**Methodischer Hinweis**

- Teil A zeigt 240,3 TWh mit nichtnegativen EEG-Zahlungen zwischen 0 und unter 60 ct/kWh.
- Die Balkenbreite entspricht der Strommenge; bei der Marktprämie ist der Strommarkterlös nicht enthalten.
- Teil B verwendet die EEG-Bandbreiten 2024, den stündlichen SMARD-Markt 2024 und die Klimaleistungsrechnung einschließlich separat ausgewiesener fossiler Vorkettenemissionen.
- Die Querlinien markieren mengengewichtete EEG-Mittelwerte. Die hellen Klimaleistungsblöcke entsprechen jeweils weiteren 50 €/t CO₂e.
- Standort der Wetterszenarien: `kassel_51.3127_9.4797_167`.

**Quellen**

Netztransparenz EEG-Jahresabrechnung und Bewegungsdaten 2024; Bundesnetzagentur/SMARD 2024; Wetter- und Anlagenszenarien sowie Emissionsansätze gemäß der Methodik des Rechenskripts `artikelgrafiken_eeg_klimaleistung.py`.

## Abbildung 2 – Stündlicher Markt für THG-freien Strom 2030

**Kurzbildtext**

Im optimistischen Szenario stehen 134 TWh streng stündlich zugeordneter Nachfrage 464,5 TWh THG-freiem Jahresangebot gegenüber. Trotzdem verbleiben 668 Unterdeckungsstunden mit zusammen 2,43 TWh. Ein Jahresüberschuss beseitigt stündliche Knappheit daher nicht.

**Methodischer Hinweis**

- Die obere Teilgrafik zeigt die aus den 2030er EEG-Vermarktungsstufen abgeleitete anbieterseitige Preisuntergrenze, nicht einen prognostizierten Marktpreis.
- In Unterdeckungsstunden ist aus dem modellierten Angebot kein Preis bestimmbar; dort wird kein künstlicher Knappheitspreis eingezeichnet.
- Die untere Teilgrafik zeigt die Dauerlinie von Angebot, Nachfrage und ihrer Differenz. Die Stunden sind nach der Differenz sortiert und deshalb keine chronologische Jahreslinie.
- Die Nachfrage ist ein transparent optimistisches Markthochlauf-Szenario: RFNBO-Elektrolyse, Rechenzentren, öffentliche Hand, DB-Traktionsstrom, 25 % der heutigen Ökostrommengen und Fernwärme-Großwärmepumpen.
- Erzeugungsprofile und Wetter stammen aus 2024; der 29. Februar wird entfernt und alle Reihen werden auf 8.760 Stunden und die Mengen 2030 normiert.
- Beispielhafte Garantie: 74 €/t CO₂e.
- Bestimmbare anbieterseitige Preise: 0,0 bis 192,3 €/t CO₂e.

**Quellen**

EEG-Mittelfristprognose 2026–2030; Bundesnetzagentur/SMARD; BNetzA-Monitoringbericht Energie 2025; Deutsche Bahn; Bundeswirtschaftsministerium; Umweltbundesamt; Wärmeplanungsgesetz; Agora Energiewende/Fraunhofer IEG. Detaillierte Herleitungen stehen im Rechenskript `klimaleistung_marktmodell_2030.py`.

## Lizenz

© Sebastian Putzke 2026. Grafiken: CC BY 4.0.
