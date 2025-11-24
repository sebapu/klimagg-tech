## Open-Source-Referenzimplementation zum KlimaGG

Diese Open-Source-Referenzimplementation demonstriert die digitalen Bausteine des KlimaGG in einer lauffähigen, aber bewusst schlank gehaltenen Form.  
Sie dient **nicht** als produktives Bund/Länder-System, sondern als:

- **Blaupause** für Architektur, Datenmodelle und Workflows,
- **Spielwiese / Sandbox** für Kommunen, Unternehmen, Finanzakteure und IT-Dienstleister,
- **Startpunkt** für eigene Implementierungen (Forks, Erweiterungen, Integrationen).

Ziel ist es, zentrale Prozesse des Gesetzes nachvollziehbar und testbar zu machen – von der Erfassung von Klimaleistungen über Register-Logik und Förderprozesse bis hin zu öffentlichen Dashboards.

---

## Abgedeckte Einsatzbereiche

Die Referenzimplementation deckt in einer „minimal, aber echt benutzbaren“ Form folgende Bereiche ab:

1. **MRV-Basisplattform**  
   Erfassung, Prüfung und Speicherung von THG-Daten und Klimaleistungen (Emissionen, Minderung, Removals).

2. **Förder- und Belohnungs-Workflows**  
   Abbildung vereinfachter Prozesse für:
   - Transformationskredite (TFK),
   - Transformationsförderung (Zuschüsse),
   - Carbon Reward für nachgewiesene THG-Minderungen und Removals.

3. **Auszahlungs- und Projektregister (Climate-Ledger-Light)**  
   Verwaltung von Anträgen, Genehmigungen und Auszahlungen mit nachvollziehbarer Verknüpfung zu Klimaleistungen.

4. **Öffentliche Klima-Dashboards**  
   Visualisierung von Budgets, Ampeln, Projekten und Kennzahlen für Öffentlichkeit und Entscheidungsträger.

5. **APIs & Datenschemata**  
   Maschinenlesbare Schnittstellen und Datenmodelle, an denen sich Bund/Land-Implementierungen und Drittsoftware orientieren können.

6. **Identität & Rollenmodell (Mock)**  
   Ein einfaches, aber klares Rollen- und Rechtekonzept, das zeigt, wie eID/BundID & Co. später „eingehängt“ werden können.

---

## Funktionsumfang im Detail

### 1. MRV & Klimaleistungs-Erfassung

- Weboberfläche zur Erfassung von:
  - Stammdaten (Akteur, Standort, Branche/NACE),
  - Basis-THG-Bilanzen (Scope 1/2, optional Scope 3),
  - Klimaprojekten (Maßnahme, Zeitraum, Methodik, erwartete/erreichte Minderung).
- Hinterlegte **Standardmethodiken** als Templates.
- Upload von Nachweisen (Dokumente, Messdaten).
- Versionierung inkl. Änderungshistorie und Audit-Log.
- Export in **maschinenlesbaren Formaten** (z.B. JSON, CSV) gemäß KlimaGG-Datenmodell.

### 2. Referenz-Register für Förderungen & Carbon Reward

- Abbildung eines einfachen **Auszahlungsregisters**:
  - Anträge mit Status (Entwurf → eingereicht → Prüfung → genehmigt → abgelehnt → ausgezahlt).
- Verknüpfung von Anträgen mit MRV-Einträgen:
  - z.B. „Dieser Antrag beruht auf Klimaleistung #123 (tCO₂e)“.
- Beispielhafte **Berechnung** von Förder- und Reward-Beträgen:
  - `Betrag = tCO₂e * Satz` (Satz konfigurierbar).
- Export von Auszahlungsinformationen für Buchhaltung und Statistik.
- Öffentliche Ansicht der wichtigsten Registerdaten (z.B. Liste geförderter Projekte mit Ort, tCO₂e, Betrag).

### 3. Dashboard & Klima-Ampeln

- **Budget-Ampel** auf Basis von Beispielbudgets:
  - Anzeige von Budget, kumulierten Emissionen/Verbuchen und Restspielraum.
- Sektorampeln (vereinfacht):
  - z.B. Gebäude, Energie, Verkehr mit Zielerreichungsindikatoren.
- Projektübersicht (Liste oder Karte) mit Filtermöglichkeiten nach Region, Sektor, Instrument.
- Export von Dashboard-Daten für externe Visualisierungen.

### 4. APIs & Datenschemata

- **REST-API** für:
  - Akteurs- und Organisationsdaten,
  - MRV-Daten (Emissionen, Projekte, Zeitreihen),
  - Registereinträge und -status,
  - Budget- und Dashbord-Daten.
- Dokumentation der API als **OpenAPI/Swagger-Spezifikation**.
- Beispiel-Adapter:
  - Import von CSV/Excel-Bilanzen,
  - einfache Webhook-Beispiele (z.B. „benachrichtige System X, wenn Antrag genehmigt“).
- Beispiel-Client-Bibliotheken (z.B. minimal für Python/Typescript).

### 5. Identitäten, Rollen & Rechte

- Einfache Benutzer- und Organisationsverwaltung.
- Rollen wie z.B.:
  - `ROLE_COMMUNE_ADMIN`,
  - `ROLE_COMPANY_EDITOR`,
  - `ROLE_REGISTER_ADMIN`,
  - `ROLE_REVIEWER`,
  - `ROLE_PUBLIC`.
- Rechte-Steuerung:
  - Wer darf Daten anlegen/bearbeiten?
  - Wer darf prüfen/freigeben?
  - Welche Daten sind öffentlich (z.B. nur aggregierte Werte)?

### 6. Sandbox & Testdaten

- Vorbefüllte Testfälle:
  - fiktive Kommune, Stadtwerk, Industriebetrieb, Landwirtschaftsbetrieb etc.
- Beispiel-Szenarien:
  - kommunale Sanierungsoffensive,
  - Stadtwerk-Projekt „Wärmepumpe statt Gaskessel“,
  - landwirtschaftliches Boden-Kohlenstoff-Projekt (Carbon Reward).
- Reset-Funktionen, um Demo-Instanzen in einen Ausgangszustand zurückzusetzen.

---

## Anwender-Gruppen & typische Nutzung

### Kommunen & kommunale Unternehmen

- Erproben eine **kommunale THG-Bilanz** in der MRV-Komponente.
- Legen Klimaprojekte an und simulieren Anträge für
  - Transformationskredit,
  - Transformationsförderung,
  - Carbon Reward.
- Kommunizieren über das Dashboard lokale Ziele und Fortschritte.

### Unternehmen & KMU

- Erfassen eigene Emissionen und Projekte.
- Testen, wie sie **Klimaleistungen nachweisen** und in Förder-/Reward-Logiken einspeisen können.
- Integrieren die API in eigene Systeme (ERP, Energiemanagement, Nachhaltigkeitsreporting).

### Banken & Förderinstitute

- Erproben einen digitalen **TFK-Prozess** von Antrag bis Auszahlung.
- Testen die **Anbindung** ihres Kernbanksystems an ein Climate-Ledger-Light.
- Bewerten, wie Klimadaten in Kredit- und Risikoentscheidungen einfließen können.

### Fachbehörden & Ministerien

- Testen Prozessvarianten (z.B. Prüfintensität, Datenumfänge).
- Nutzen das Dashboard zur **Simulation von Reporting-Varianten**.
- Experimentieren mit der Kopplung von Budgets, Registerlogik und Förderprioritäten.

### Softwarehersteller & IT-Dienstleister

- Verwenden die Referenzimplementation als **lebende Spezifikation**:
  - Datenmodelle,
  - API-Verträge,
  - Workflows.
- Entwickeln darauf aufbauend eigene, skalierbare Lösungen.
- Prüfen Kompatibilität mittels Conformance-Tests.

### Forschung, Zivilgesellschaft & NGOs

- Spielen Policy-Szenarien durch (Reward-Sätze, Förderdesign, Budgetpfade).
- Nutzen die offenen Datenstrukturen für Evaluierungen und Studien.
- Bauen ergänzende Auswertungs- und Visualisierungsbausteine.

---

## Nicht-Ziele

Die Referenzimplementation ist **kein**:

- produktives System des Bundes, der Länder oder Kommunen,
- Ersatz für Fachverfahren in Verwaltung, Banken oder Unternehmen,
- hochverfügbare, hochskalierte Infrastruktur.

Sie ist bewusst:

- **einfach genug**, um verstanden, installiert und erweitert zu werden,
- **realistisch genug**, um echte Prozesse und Datenflüsse zu demonstrieren,
- **offen genug**, um als Grundlage für vielfältige Implementierungen zu dienen.

