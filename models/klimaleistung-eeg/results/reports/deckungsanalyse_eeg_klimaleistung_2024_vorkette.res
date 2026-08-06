EEG-/KLIMALEISTUNGS-DECKUNGSANALYSE
RESULTATDATEI (.res)
==============================================================================
Erstellt: 2026-08-05T12:04:32+00:00
Skriptversion: 1.1.0
Artikelgrafik-Kern: Version 7.3.0 · /mnt/data/artikelgrafiken_eeg_klimaleistung.py
Auswertungsjahr: 2024
SMARD-Datenbank: /mnt/data/smard_stundendaten_2021_2025.sqlite
EEG-Datenbank: /mnt/data/netztransparenz_eeg.sqlite

1. ZENTRALE ERGEBNISSE
------------------------------------------------------------------------------

Die folgenden Werte sind reproduzierbare Modellwerte unter den Markt-,
Erzeugungs-, Emissions- und Vergütungsbedingungen des Jahres 2024.
Sie sind keine garantierte Haushaltsprognose.

€/t CO2e | KL-Wert Mrd. € | EEG-Zahlung abgedeckt Mrd. € | Anteil EEG-Zahlung | Förderlücke ersetzt Mrd. € | Anteil Förderlücke | Restförderbedarf Mrd. €
---------+----------------+------------------------------+--------------------+----------------------------+--------------------+------------------------
50       | 9,10           | 8,48                         | 44,6 %             | 6,65                       | 38,7 %             | 10,54                  
100      | 18,21          | 12,08                        | 63,5 %             | 10,24                      | 59,6 %             | 6,95                   
150      | 27,31          | 14,65                        | 77,0 %             | 12,82                      | 74,6 %             | 4,37                   

Begriffe:
- KL-Wert: ungekappter monetärer Wert der Klimaleistung auf der positiven
  EEG-Strommenge im Modellumfang.
- EEG-Zahlung abgedeckt: Einspeisevergütung wird durch Bestands-Marktwert
  plus Klimaleistung, Marktprämie durch Klimaleistung allein ersetzt; pro
  Kategorie höchstens bis zur positiven beobachteten EEG-Zahlung.
- Förderlücke ersetzt: zusätzlicher Beitrag der Klimaleistung nach Abzug
  des ohnehin vorhandenen Marktwerts bei Einspeisevergütung. Dieser Wert
  ist die geeignetere Obergrenze für eine mögliche staatliche Entlastung
  bei vollständig privater Abnahme der Klimaleistung.

2. DATENBASIS UND ANALYSEUMFANG
------------------------------------------------------------------------------

Nettozahlung der vollständigen EEG-Datenbank: 19,299 Mrd. €
Positive Einzelzeilen der Datenbank:          19,561 Mrd. €
Negative Einzelzeilen der Datenbank:          -0,262 Mrd. €
Jährlich aggregierte positive Kategorien:     19,235 Mrd. €
Modellumfang positive Kategorien:             19,025 Mrd. €
Anteil am aggregierten positiven Bestand:     98,91 %
Modellumfang Strommenge:                       202,779 TWh
Negative Kategorien im Modellumfang:           68 Kategorien, 2,889 TWh, -28,23 Mio. €

Modelliert werden die fünf Hauptenergieträger Solar, Wind an Land, Wind
auf See, Biomasse und Wasser sowie die Veräußerungsformen 1
(Einspeisevergütung) und 2 (Marktprämie). Andere Energieträger und
Veräußerungsformen werden als außerhalb des Modellumfangs ausgewiesen.

3. BESTANDSREFERENZEN 2024
------------------------------------------------------------------------------

Energieträger | MWh/MW  | Marktwert €/MWh | t CO2e/MWh | ct/kWh @50 | ct/kWh @100 | ct/kWh @150
--------------+---------+-----------------+------------+------------+-------------+------------
Solar         | 680,4   | 46,03           | 0,9122     | 4,561      | 9,122       | 13,683     
Wind an Land  | 1.810,4 | 64,44           | 0,8907     | 4,454      | 8,907       | 13,361     
Wind auf See  | 2.911,5 | 71,15           | 0,8947     | 4,474      | 8,947       | 13,421     
Biomasse      | 3.431,3 | 80,42           | 0,8973     | 4,487      | 8,973       | 13,460     
Wasser        | 3.160,9 | 80,64           | 0,8996     | 4,498      | 8,996       | 13,493     

4. ERGEBNISSE NACH ENERGIETRÄGER
------------------------------------------------------------------------------

Klimaleistungspreis: 50 €/t CO2e

Energieträger | positive Zahlung Mrd. € | abgedeckt Mrd. € | Deckung | Förderlücke Mrd. € | KL-Entlastung Mrd. € | Entlastungsanteil
--------------+-------------------------+------------------+---------+--------------------+----------------------+------------------
Solar         | 10,176                  | 3,592            | 35,3 %  | 8,637              | 2,053                | 23,8 %           
Wind an Land  | 2,174                   | 2,174            | 100,0 % | 2,116              | 2,116                | 100,0 %          
Wind auf See  | 2,094                   | 0,901            | 43,0 %  | 2,075              | 0,882                | 42,5 %           
Biomasse      | 4,373                   | 1,611            | 36,8 %  | 4,233              | 1,470                | 34,7 %           
Wasser        | 0,207                   | 0,203            | 97,9 %  | 0,131              | 0,127                | 96,7 %           

Klimaleistungspreis: 100 €/t CO2e

Energieträger | positive Zahlung Mrd. € | abgedeckt Mrd. € | Deckung | Förderlücke Mrd. € | KL-Entlastung Mrd. € | Entlastungsanteil
--------------+-------------------------+------------------+---------+--------------------+----------------------+------------------
Solar         | 10,176                  | 5,001            | 49,1 %  | 8,637              | 3,461                | 40,1 %           
Wind an Land  | 2,174                   | 2,174            | 100,0 % | 2,116              | 2,116                | 100,0 %          
Wind auf See  | 2,094                   | 1,747            | 83,4 %  | 2,075              | 1,728                | 83,3 %           
Biomasse      | 4,373                   | 2,947            | 67,4 %  | 4,233              | 2,806                | 66,3 %           
Wasser        | 0,207                   | 0,207            | 100,0 % | 0,131              | 0,131                | 100,0 %          

Klimaleistungspreis: 150 €/t CO2e

Energieträger | positive Zahlung Mrd. € | abgedeckt Mrd. € | Deckung | Förderlücke Mrd. € | KL-Entlastung Mrd. € | Entlastungsanteil
--------------+-------------------------+------------------+---------+--------------------+----------------------+------------------
Solar         | 10,176                  | 6,215            | 61,1 %  | 8,637              | 4,675                | 54,1 %           
Wind an Land  | 2,174                   | 2,174            | 100,0 % | 2,116              | 2,116                | 100,0 %          
Wind auf See  | 2,094                   | 2,094            | 100,0 % | 2,075              | 2,075                | 100,0 %          
Biomasse      | 4,373                   | 3,961            | 90,6 %  | 4,233              | 3,821                | 90,3 %           
Wasser        | 0,207                   | 0,207            | 100,0 % | 0,131              | 0,131                | 100,0 %          

5. PRIVATE ABNAHME UND MÖGLICHE STAATLICHE ENTLASTUNG
------------------------------------------------------------------------------

Die Tabelle unterstellt, dass der angegebene Anteil der Klimaleistung
gleichmäßig privat abgenommen wird. Die Entlastung wird pro Kategorie auf
die nach Marktwert verbleibende positive Förderlücke begrenzt.

€/t CO2e | private Abnahme | mögliche Entlastung Mrd. € | Anteil Förderlücke | verbleibend Mrd. €
---------+-----------------+----------------------------+--------------------+-------------------
50       | 25 %            | 2,17                       | 12,6 %             | 15,02             
50       | 50 %            | 4,03                       | 23,4 %             | 13,16             
50       | 100 %           | 6,65                       | 38,7 %             | 10,54             
100      | 25 %            | 4,03                       | 23,4 %             | 13,16             
100      | 50 %            | 6,65                       | 38,7 %             | 10,54             
100      | 100 %           | 10,24                      | 59,6 %             | 6,95              
150      | 25 %            | 5,53                       | 32,1 %             | 11,67             
150      | 50 %            | 8,54                       | 49,7 %             | 8,65              
150      | 100 %           | 12,82                      | 74,6 %             | 4,37              

6. NOMINALE RESTFÖRDERUNG
------------------------------------------------------------------------------

Positive Jahreszahlungen im Modellumfang:       19,025 Mrd. €
Davon mit plausibler Jahreskennung:             18,683 Mrd. € (98,20 %)
Nominale Restzahlung im Modellumfang:           134,772 Mrd. €
Nominale Rest-Förderlücke nach Marktwert:       117,989 Mrd. €
Vergleich: bestehende Restförderungsgrafik, alle positiven Zeilen und alle Energieträger/Veräußerungsformen: 135,725 Mrd. €

Der Vergleichswert der bestehenden Grafik ist größer, weil er alle
Energieträger und Veräußerungsformen sowie positive Einzelzeilen umfasst.
Die Deckungsanalyse verwendet dagegen jährlich aggregierte Kategorien im
klar definierten Modellumfang, damit negative Korrekturen nicht zugleich
als separate positive Restverpflichtung fortgeschrieben werden.

Die nominale Rechnung unterstellt konstante Jahresmenge, konstante
EEG-Zahlung, Marktwerte und THG-Wirkung auf dem Niveau 2024. Sie ist keine
Barwertrechnung und keine Prognose. Kategorien ohne plausibel lesbare
Jahreskennung werden nicht hochgerechnet.

€/t CO2e | nominal ersetzbare Rest-Förderlücke Mrd. € | Anteil | nominal verbleibend Mrd. €
---------+--------------------------------------------+--------+---------------------------
50       | 54,31                                      | 46,0 % | 63,68                     
100      | 80,90                                      | 68,6 % | 37,09                     
150      | 97,72                                      | 82,8 % | 20,27                     

7. METHODIK
------------------------------------------------------------------------------

7.1 Zeitliche Referenz
SMARD-Erzeugung und Day-ahead-Preis werden stündlich für 2024 ausgewertet.
Die Bestands-Netzeinspeisung jedes Energieträgers wird durch eine linear
zwischen den UBA/AGEE-Stat-Jahresendbeständen interpolierte installierte
Leistung geteilt. Daraus entstehen Marktwert und Klimaleistung je MWh.

7.2 Klimaleistung
Klimaleistung ist die Summe aus stündlicher Energie und dem gleichzeitig
erzeugungsgewichteten fossilen SMARD-Mix aus Braunkohle, Steinkohle,
Erdgas und Sonstigen Konventionellen.
Direkte Kraftwerksemission und Vorkette werden getrennt geführt; die Vorkette wird als expliziter Aufschlag ausgewiesen und erst danach zum Gesamtansatz addiert:

  - Braunkohle: direkt 1,030 + Vorketten-Aufschlag 0,063 = gesamt 1,093 t CO2e/MWh
  - Steinkohle: direkt 0,877 + Vorketten-Aufschlag 0,094 = gesamt 0,971 t CO2e/MWh
  - Erdgas: direkt 0,438 + Vorketten-Aufschlag 0,142 = gesamt 0,580 t CO2e/MWh
  - Sonstige Konventionelle: direkt 0,816 + Vorketten-Aufschlag 0,178 = gesamt 0,994 t CO2e/MWh

Die Aufschläge und ihre Quellen werden im Kernskript sowie in fossile_emissionsansaetze.csv dokumentiert. Sonstige Konventionelle bleiben wegen der heterogenen SMARD-Sammelkategorie ein Ölprodukt-Proxy.
Es handelt sich definitionsgemäß um rechnerische fossile Brutto-
Verdrängung, nicht um eine vollständige LCA oder einen kausalen
Grenzkraftwerksnachweis.

7.3 EEG-Kategorien
Die Daten werden über das Gesamtjahr je Energieträger, Veräußerungsform
und Vergütungskategorie aggregiert. Nur Kategorien mit positiver
Jahresstrommenge können als ct/kWh- beziehungsweise Deckungsfall verwendet
werden. Positive Zahlungen bilden den ersetzbaren Bestand. Negative
Jahreskategorien werden protokolliert, aber nicht als positive Förderung
oder negative gesetzliche Marktprämie behandelt.

7.4 Deckungslogik
Einspeisevergütung: min(positive EEG-Zahlung, Marktwert + Klimaleistung).
Marktprämie: min(positive Prämienzahlung, Klimaleistung).
Förderlücke: Einspeisevergütung minus Marktwert beziehungsweise positive
Marktprämie. Die zusätzliche Entlastung ist die Klimaleistung, jeweils auf
diese Förderlücke begrenzt.

7.5 Restförderung
Das Inbetriebnahmejahr wird konservativ aus den letzten zwei Ziffern des
Kategoriecodes gelesen. Restjahre = max(0, Inbetriebnahmejahr + 20 -
2024). Diese Näherung folgt der vorhandenen Netztransparenz-
Restförderungsgrafik; Sonderlaufzeiten und nicht codierte Kategorien
bleiben unberücksichtigt.

8. UNSICHERHEITEN UND BILANZGRENZEN
------------------------------------------------------------------------------

- Die Werte verwenden Marktpreise, Erzeugungsprofile und fossilen Mix des
  Jahres 2024; künftige Jahre können deutlich abweichen.
- Private Nachfrage nach Klimaleistung ist nicht nachgewiesen, sondern wird
  als Abnahmeanteil parametrisiert.
- Staatliche Entlastung entsteht nur, soweit private Zahlungen öffentliche
  Förderung tatsächlich ersetzen. Zahlt der Staat die Klimaleistung selbst,
  ist dies zunächst eine Umstrukturierung der Förderung.
- Verwaltung, Register, Vermarktungskosten, Ausgleichsenergie, Übergangs-
  regeln und Vertrauensschutz sind nicht eingerechnet.
- Die nominale Restförderung hält sämtliche Jahreswerte konstant und ist
  weder Barwert noch belastbare Haushaltsprognose.
- Biomasse wird hier nur anhand des Einspeiseprofils bewertet; brennstoff-
  und KWK-spezifische THG-Bilanzen sind nicht enthalten.

9. FÜR DEN ARTIKEL GEEIGNETE FORMULIERUNG
------------------------------------------------------------------------------

Unter den Markt-, Erzeugungs-, Emissions- und Vergütungsbedingungen des
Jahres 2024 ergibt die Modellrechnung folgende Größenordnungen:

- Bei 50 €/t CO2e werden rechnerisch 8,48 Mrd. € beziehungsweise 44,6 % der positiven EEG-Zahlungen abgedeckt. Der zusätzliche Klimaleistungsbeitrag ersetzt bis zu 6,65 Mrd. € beziehungsweise 38,7 % der nach Marktwert verbleibenden Förderlücke, sofern die Klimaleistung vollständig privat abgenommen wird.
- Bei 100 €/t CO2e werden rechnerisch 12,08 Mrd. € beziehungsweise 63,5 % der positiven EEG-Zahlungen abgedeckt. Der zusätzliche Klimaleistungsbeitrag ersetzt bis zu 10,24 Mrd. € beziehungsweise 59,6 % der nach Marktwert verbleibenden Förderlücke, sofern die Klimaleistung vollständig privat abgenommen wird.
- Bei 150 €/t CO2e werden rechnerisch 14,65 Mrd. € beziehungsweise 77,0 % der positiven EEG-Zahlungen abgedeckt. Der zusätzliche Klimaleistungsbeitrag ersetzt bis zu 12,82 Mrd. € beziehungsweise 74,6 % der nach Marktwert verbleibenden Förderlücke, sofern die Klimaleistung vollständig privat abgenommen wird.

Die tatsächliche Haushaltsentlastung hängt insbesondere von privater
Nachfrage, künftigen Marktpreisen, dem fossilen Strommix, Übergangsregeln
und den Kosten der Nachweisführung ab. Die nominale Restförderungsrechnung
ist nur eine konstante Fortschreibung des Jahres 2024 und keine Prognose.

10. QUELLEN
------------------------------------------------------------------------------

- Netztransparenz EEG-Bewegungsdaten: https://www.netztransparenz.de/de-de/Erneuerbare-Energien-und-Umlagen/EEG/EEG-Abrechnungen/EEG-Jahresabrechnungen/EEG-Bewegungsdaten
- SMARD Stundendaten und Day-ahead-Preis: https://www.smard.de/
- UBA/AGEE-Stat installierte Leistungen: https://www.umweltbundesamt.de/system/files/medien/479/publikationen/2026-03/UBA_Erneuerbare%20Energien%20in%20Deutschland%202025.pdf
- UBA direkte fossile Emissionsansätze: https://www.umweltbundesamt.de/system/files/medien/11850/publikationen/2026-01/11_2026_CC.pdf
- UBA Vorketten Erdgas und Steinkohle: https://www.umweltbundesamt.de/system/files/medien/1410/publikationen/cc_61-2021_emissionsfaktoren-stromerzeugung_bf.pdf
- UNECE Lebenszykluswert Braunkohle: https://unece.org/sites/default/files/2021-11/LCA_final.pdf
- JEC WTT v5 Ölproduktbereitstellung: https://doi.org/10.2760/100379
- EEG-Datenbank-Metadaten: Netztransparenz.de, lokale Jahresabrechnungs-ZIP-Dateien
- Rechenannahmen und Referenzwerte: artikelgrafiken_eeg_klimaleistung.py, Version 7.3.0

ENDE DER RESULTATDATEI
