# Fenner Tourenoptimierung

Automatische Routenplanung mit Zeitfenstern (VRPTW) für Proben-Abholungen.
Berechnet optimale Touren unter Berücksichtigung von Abholzeitfenstern, Depot-Einlieferzeiten und Fahrzeugkapazitäten.

## Voraussetzungen

- **Python 3.10+**
- Internetverbindung (für OSRM-Routing)

## Installation

```bash
# Repository klonen
git clone <repo-url>
cd fenner-route-optimizer

# Virtuelle Umgebung erstellen & aktivieren
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS

# Abhängigkeiten installieren
pip install -r requirements.txt
```

## Starten

### Web-Oberfläche (empfohlen)

```bash
streamlit run app.py
```

Öffnet sich automatisch im Browser unter `http://localhost:8501`.

1. In der **Sidebar** Depot-Koordinaten, Zeitfenster, Solver-Parameter und Kosten konfigurieren
2. Excel-Datei hochladen
3. **Berechnen** klicken
4. Ergebnisse in den Tabs ansehen: Karte, Routen, Einsender, Kosten, Download

### Kommandozeile

```bash
python main.py
```

Liest `src/einsender.xlsx` und erzeugt `solution.xlsx` + `solution_map.html` im Projektordner.

## Excel-Input

Die hochgeladene `.xlsx`-Datei muss folgende Spalten enthalten (Groß-/Kleinschreibung egal):

| Spalte | Pflicht | Beschreibung | Beispiel |
|---|:---:|---|---|
| `lat` | ja | Breitengrad (WGS84) | `53.0752` |
| `lon` | ja | Längengrad (WGS84) | `8.8077` |
| `Abholung 1 von` | ja | Beginn Abholzeitfenster 1 | `08:00` |
| `Abholung 1 bis` | ja | Ende Abholzeitfenster 1 | `10:00` |
| `Abholung 2 von` | ja | Beginn Abholzeitfenster 2 (leer = keine 2. Abholung) | `14:00` |
| `Abholung 2 bis` | ja | Ende Abholzeitfenster 2 (leer = keine 2. Abholung) | `16:00` |
| `Einsender` | optional | Name des Einsenders | `Praxis Müller` |
| `Adresse` | optional | Adresse für Anzeige | `Hauptstr. 12, 28195 Bremen` |
| `id` oder `name` | optional | Eindeutige Kennung (Fallback wenn `Einsender` fehlt) | `E-0042` |
| `service_min` | optional | Servicezeit vor Ort in Minuten (Default: 5) | `10` |

### Hinweise zum Input

- **Zeitformate**: `HH:MM` (z.B. `08:00`) oder vollständige Timestamps (`2026-01-07 08:00`)
- **Zwei Abholungen**: Wenn beide Zeitfenster gefüllt sind, werden **zwei separate Pflicht-Stopps** erzeugt
- **Eine Abholung**: Wenn nur Fenster 1 gefüllt ist (Fenster 2 leer), wird nur ein Stopp erzeugt
- Leere Zeilen oder fehlende Koordinaten führen zu Fehlermeldungen

## Konfiguration

### Sidebar-Parameter (Web-UI)

| Parameter | Default | Beschreibung |
|---|---|---|
| Depot-Koordinaten | 53.054218, 9.031621 | Standort des Labors |
| Depot-Zeitfenster 1–3 | 11:00–11:30, 14:00–14:30, 17:30–18:00 | Einlieferzeiten am Depot |
| Anzahl Fahrzeuge | 6 | Maximale Anzahl paralleler Touren |
| Servicezeit | 5 min | Zeit pro Abholung vor Ort |
| Max. Wartezeit | 240 min | Erlaubte Wartezeit, wenn Fahrer zu früh ankommt |
| Max. Tourdauer | 240 min | Harte Obergrenze pro Tour (0 = unbegrenzt) |
| Streckenkosten | 30 ct/km | Kosten pro Kilometer |
| Zeitkosten | 35,00 EUR/h | Kosten pro Stunde (Fahrt + Wartezeit + Service) |

### Routing-Provider

Standardmäßig wird der **öffentliche OSRM-Server** verwendet (keine API-Keys nötig).

Optional kann Google Routes genutzt werden:

```bash
set MATRIX_PROVIDER=GOOGLE
set GOOGLE_MAPS_API_KEY=dein-api-key
streamlit run app.py
```

## Projektstruktur

```
fenner-route-optimizer/
  app.py                  # Streamlit Web-Frontend
  main.py                 # CLI-Einstieg
  requirements.txt        # Python-Abhängigkeiten
  src/
    config.py             # Konfigurationsklassen (DepotConfig, SolveConfig)
    io_excel.py           # Excel-Import, Zeitfenster-Parsing
    matrix.py             # Fahrzeit-/Distanzmatrix (OSRM / Google)
    solver.py             # OR-Tools VRPTW-Solver
    route_stats.py        # Routen-Kennzahlen (Distanz, Zeit, Kosten)
    export_excel.py       # Excel-Export der Lösung
    export_map.py         # Interaktive Karte (Folium)
    debug_checks.py       # Vorab-Validierung der Eingabedaten
```

## Abhängigkeiten

| Paket | Zweck |
|---|---|
| `streamlit` | Web-Oberfläche |
| `ortools` | Google OR-Tools – VRPTW-Solver |
| `pandas` / `openpyxl` | Excel lesen & schreiben |
| `folium` | Interaktive Kartendarstellung |
| `requests` | HTTP-Anfragen an Routing-APIs |
| `python-dateutil` | Flexibles Zeitformat-Parsing |
