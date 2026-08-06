# Methodik und wissenschaftliche Einordnung der Artikelgrafiken

Skriptversion: 7.3.0
SMARD- und Marktjahr: 2024
EEG-Bestandsjahr: 2024
Szenario-Standort: kassel_51.3127_9.4797_167

## Eingaben

- SMARD-SQLite: `/mnt/data/smard_stundendaten_2021_2025.sqlite`
- Szenario-SQLite: `/mnt/data/wetterdaten_szenarien_2024_v22.sqlite`
- EEG-SQLite: `/mnt/data/netztransparenz_eeg.sqlite`

## Einheitlicher Rechenkern

Für jeden Fall wird eine stündliche Einspeisereihe je MW gebildet. Der Markterlös ist die Summe aus Stundenenergie und gleichzeitigem deutschem Day-ahead-Preis. Die Klimaleistung ist die Summe aus Stundenenergie und dem gleichzeitig erzeugungsgewichteten fossilen SMARD-Mix.

Direkte kraftwerksseitige Emissionen und Vorketten werden getrennt angesetzt. Die Vorkette erscheint ausdrücklich als Aufschlag je MWh Strom; erst beide Bestandteile zusammen gehen in den stündlichen fossilen Mix ein.

| Energieträger | direkt t CO₂e/MWh | Vorketten-Aufschlag t CO₂e/MWh | gesamt t CO₂e/MWh |
|---|---:|---:|---:|
| Braunkohle | 1,030 | 0,063 | 1,093 |
| Steinkohle | 0,877 | 0,094 | 0,971 |
| Erdgas | 0,438 | 0,142 | 0,580 |
| Sonstige Konventionelle | 0,816 | 0,178 | 0,994 |

Die Aufschläge sind konservative obere, aber regulär dokumentierte Ansätze: UNECE-Lebenszyklusmittel für Braunkohle; höchster regulärer UBA-Lieferlandwert für Steinkohle; US-LNG einschließlich Verteilung für Erdgas; JEC-WTT-Ölproduktbereitstellung als Proxy für Sonstige. Die vom UBA selbst als hoch unsicher bezeichnete US-LNG-Sensitivität von 30,0 g CO₂e/MJ wird nicht als Hauptwert verwendet. Sonstige Konventionelle bleiben wegen der heterogenen SMARD-Sammelkategorie die größte Unsicherheit.

Die Klimaleistung ist definitionsgemäß eine rechnerische fossile Brutto-Verdrängung. Herstellungs-, Bau- und Rückbauemissionen werden nicht pauschal abgezogen; sie gehören in eine getrennte, projektspezifische Anlagenbilanz. Die Kennzahl ist kein kausaler Grenzkraftwerksnachweis.

## Neu und Bestand

Die literaturnormierten PV- und Onshore-Windfälle sind als `Neu` gekennzeichnet. Der jeweils helle Referenzfall ist der beobachtete Bestand 2024: reale SMARD-Netzeinspeisung geteilt durch eine zwischen den UBA/AGEE-Stat-Jahresendbeständen 2023/2024 interpolierte Bestandsleistung. Er wird weder auf Bruttostromerzeugung hochgerechnet noch auf einen Literaturertrag normiert. Bei PV ist dies Netzeinspeisung je gesamtem Bestands-MWp; Eigenverbrauch ist nicht enthalten. Biomasse und Wasser sind wegen unterschiedlicher SMARD-Datenabdeckung nur eingeschränkte Bestandsreferenzen.

## PV- und Wind-Literaturfälle

Die Stundenform stammt aus dem Wetter- und Anlagenmodell am Standort Kassel. Die Jahressumme wird auf dokumentierte Erträge normiert: PVGIS 5.3/SARAH3 für PV und Deutsche WindGuard 2026, Region Mitte, für Wind. Das sind Szenarien für Tendenzen und Größenordnungen, keine projektspezifischen Ertragsgutachten. Rohwerte und Profilprüfungen stehen in `artikelgrafik_faelle.csv`.

## EEG-Spannen

Es gibt keine Mengenschwelle mehr. Aus jeder Veräußerungsform werden alle über das Gesamtjahr und die Vergütungskategorie aggregierten Sätze ausgewertet. Nullwerte bleiben enthalten. Für die sichtbare Min-Max-Spanne werden nichtnegative Kategoriesätze verwendet. Rechnerisch negative Marktprämien-Abrechnungszeilen werden nicht als negative gesetzliche Tarifuntergrenze gezeichnet: Anlage 1 EEG setzt die Marktprämie bei null fest; Netztransparenz beschreibt negative Bewegungszeilen als rechnerische Werte, die über zusätzliche Ausgleichskategorien ausgeglichen werden. In den fünf dargestellten Energieträgern betrifft dies 68 Jahreskategorien. Sie bleiben vollständig in `eeg_bandbreiten.csv` und im mengengewichteten Gesamtmittel erhalten.

## Vergleich in Grafik 2

Je Energieträger stehen zuerst drei Bestandsbalken: EEG-Vollvergütung, stündlicher Marktwert plus beobachtete Marktprämie und Bestands-Marktwert plus Klimaleistung in Schritten von 50, 100 und 150 €/t. Danach folgen die ausgewählten Neufälle als ihr jeweiliger stündlicher Profilmarktwert plus Klimaleistung. In den beiden EEG-Balken markiert die farbige Querlinie den mengengewichteten Mittelwert; seitliche Vergleichsmarken werden nicht verwendet.

## Wissenschaftliche Belastbarkeit

- Geeignet: reproduzierbarer Szenariovergleich und Größenordnungsprüfung.
- Nicht geeignet: exakter Grenzkraftwerksnachweis oder projektspezifische Ertrags- und Erlösgarantie.
- EEG 2024: heterogene historische Bestandskohorten, keine einheitliche Neubauvergütung.
- Biomasse: nur das Einspeiseprofil wird gegen den fossilen Mix bewertet; Brennstoff- und KWK-spezifische THG-Bilanzen sind nicht enthalten.
- Deutlich normierte Fälle: PV Süd 30° (Faktor 1.41), PV Süd 60° (Faktor 1.49), PV Ost–West 15° (Faktor 1.25), PV Ost–West 30° (Faktor 1.27).

## Verifikationswerte der Fälle

| Fall | Typ | Ziel MWh/MW | Rohwert | Kalibrierung | Faktor | Korrelation | Monatsfehler pp | Marktwert Δ | THG Δ | Status |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---|
| PV · SMARD-Netzeinspeisung | Bestand 2024 | 680.4 | 680.4 | none | 1.000 | – | – | +0.0 % | +0.0 % | SMARD-NETZEINSPEISUNG · KEINE ERTRAGSNORMIERUNG |
| PV Süd 30° | Neu | 1009.5 | 720.9 | output_scale_with_physical_cap | 1.407 | 0.911 | 0.610 | -2.8 % | +0.0 % | LITERATURNORMIERT · DEUTLICHE NORMIERUNG |
| PV Süd 60° | Neu | 963.4 | 647.1 | output_scale_with_physical_cap | 1.495 | 0.895 | 0.642 | -3.3 % | +0.0 % | LITERATURNORMIERT · DEUTLICHE NORMIERUNG |
| PV Ost–West 15° | Neu | 847.2 | 677.5 | output_scale_with_physical_cap | 1.250 | 0.925 | 0.648 | -1.6 % | +0.0 % | LITERATURNORMIERT · DEUTLICHE NORMIERUNG |
| PV Ost–West 30° | Neu | 821.7 | 644.5 | output_scale_with_physical_cap | 1.275 | 0.927 | 0.622 | -0.6 % | +0.0 % | LITERATURNORMIERT · DEUTLICHE NORMIERUNG |
| Wind an Land · SMARD-Netzeinspeisung | Bestand 2024 | 1810.4 | 1810.4 | none | 1.000 | – | – | +0.0 % | +0.0 % | SMARD-NETZEINSPEISUNG · KEINE ERTRAGSNORMIERUNG |
| Wind Standardanlage | Neu | 2050.0 | 777.1 | wind_speed_scale | 1.452 | 0.713 | 1.012 | -11.5 % | +0.0 % | LITERATURKALIBRIERT · DEUTLICHE WINDKALIBRIERUNG · MARKTWERT-PROFIL SENSITIV |
| Wind Schwachwindanlage | Neu | 2300.0 | 1365.0 | wind_speed_scale | 1.262 | 0.698 | 1.042 | -10.5 % | +0.1 % | LITERATURKALIBRIERT · DEUTLICHE WINDKALIBRIERUNG · MARKTWERT-PROFIL SENSITIV |
| Wind auf See · SMARD-Netzeinspeisung | Bestand 2024 | 2911.5 | 2911.5 | none | 1.000 | – | – | +0.0 % | +0.0 % | SMARD-NETZEINSPEISUNG · KEINE ERTRAGSNORMIERUNG |
| Biomasse · SMARD-Netzeinspeisung | Bestand 2024 | 3431.3 | 3431.3 | none | 1.000 | – | – | +0.0 % | +0.0 % | SMARD-NETZEINSPEISUNG · KEINE ERTRAGSNORMIERUNG |
| Wasser · SMARD-Netzeinspeisung | Bestand 2024 | 3160.9 | 3160.9 | none | 1.000 | – | – | +0.0 % | +0.0 % | SMARD-NETZEINSPEISUNG · KEINE ERTRAGSNORMIERUNG |

## Quellen

- UBA/AGEE-Stat Kapazitäten: https://www.umweltbundesamt.de/system/files/medien/479/publikationen/2026-03/UBA_Erneuerbare%20Energien%20in%20Deutschland%202025.pdf
- UBA direkte fossile Emissionsansätze: https://www.umweltbundesamt.de/system/files/medien/11850/publikationen/2026-01/11_2026_CC.pdf
- UBA Vorketten Erdgas und Steinkohle: https://www.umweltbundesamt.de/system/files/medien/1410/publikationen/cc_61-2021_emissionsfaktoren-stromerzeugung_bf.pdf
- UNECE Lebenszykluswert Braunkohle: https://unece.org/sites/default/files/2021-11/LCA_final.pdf
- JEC WTT v5 Ölproduktbereitstellung: https://doi.org/10.2760/100379
- SMARD Marktdaten: https://www.smard.de/
- Netztransparenz EEG-Bewegungsdaten: https://www.netztransparenz.de/de-de/Erneuerbare-Energien-und-Umlagen/EEG/EEG-Abrechnungen/EEG-Jahresabrechnungen/EEG-Bewegungsdaten
- EEG Anlage 1, Marktprämie mindestens null: https://www.gesetze-im-internet.de/eeg_2014/anlage_1.html
- PVGIS: https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/using-pvgis-5/api-non-interactive-service_en
- Deutsche WindGuard 2026: https://www.windguard.de/veroeffentlichungen.html?file=files%2Fcto_layout%2Fimg%2Funternehmen%2Fveroeffentlichungen%2F2026%2FVolllaststunden+von+Windenergieanlagen+an+Land.pdf
