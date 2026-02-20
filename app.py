"""
Streamlit Web-Frontend für die Fenner Tourenoptimierung.
Starten: streamlit run app.py
"""
from __future__ import annotations

import warnings
from datetime import date

import streamlit as st
import streamlit.components.v1 as components

from src.config import DepotConfig, SolveConfig
from src.io_excel import (
    load_einsender_excel,
    build_nodes_mandatory_both_windows,
    depot_union_windows,
)
from src.matrix import build_matrices
from src.solver import solve_vrptw, solve_vrptw_relaxed_soft_timewindows, fmt_min_to_hhmm
from src.export_excel import export_solution_to_excel
from src.export_map import export_routes_map_html
from src.debug_checks import (
    check_basic_nodes,
    check_depot_union,
    check_matrix_sanity,
    check_reachability_quick,
    summarize_input,
)

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# ── Seiten-Setup ────────────────────────────────────────────────────
st.set_page_config(page_title="Fenner Tourenoptimierung", layout="wide")
st.title("🚗 Fenner Tourenoptimierung")

# ── Sidebar: Konfiguration ──────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Konfiguration")

    st.subheader("Depot / Labor")
    depot_lat = st.number_input("Breitengrad (lat)", value=53.054218, format="%.6f")
    depot_lon = st.number_input("Längengrad (lon)", value=9.031621,  format="%.6f")

    st.subheader("Depot-Zeitfenster")
    c1, c2 = st.columns(2)
    d1_von = c1.text_input("Fenster 1 von", "11:00")
    d1_bis = c2.text_input("Fenster 1 bis", "11:30")
    d2_von = c1.text_input("Fenster 2 von", "14:00")
    d2_bis = c2.text_input("Fenster 2 bis", "14:30")
    d3_von = c1.text_input("Fenster 3 von", "17:30")
    d3_bis = c2.text_input("Fenster 3 bis", "18:00")

    st.subheader("Solver")
    num_vehicles = st.number_input("Anzahl Fahrzeuge",    min_value=1, max_value=30,  value=6)
    service_min  = st.number_input("Servicezeit (min)",   min_value=0, max_value=60,  value=5)
    max_wait     = st.number_input("Max. Wartezeit (min)", min_value=0, max_value=480, value=240)
    ref_date     = st.date_input("Referenzdatum", value=date.today())

# ── Haupt-Bereich ───────────────────────────────────────────────────
uploaded = st.file_uploader("📂 Einsender-Datei (.xlsx) hochladen", type=["xlsx"])
run = st.button("🚀 Berechnen", type="primary", disabled=(uploaded is None))

if not run or uploaded is None:
    st.stop()

# ── Konfiguration zusammenbauen ─────────────────────────────────────
depot = DepotConfig(
    lat=depot_lat, lon=depot_lon,
    depot_1_von=d1_von, depot_1_bis=d1_bis,
    depot_2_von=d2_von or None, depot_2_bis=d2_bis or None,
    depot_3_von=d3_von or None, depot_3_bis=d3_bis or None,
)
solve_cfg = SolveConfig(
    num_vehicles=num_vehicles,
    reference_date=ref_date,
    default_service_min=service_min,
    max_wait_min=max_wait,
    max_route_duration_min=0,
)

# ── Schritt 1: Daten laden ──────────────────────────────────────────
with st.spinner("Lade Eingabedaten …"):
    try:
        df = load_einsender_excel(uploaded, solve_cfg)
        coords, node_tws, service_mins, labels, node_meta_df = (
            build_nodes_mandatory_both_windows(depot, df, solve_cfg)
        )
    except Exception as e:
        st.error(f"Fehler beim Laden der Datei: {e}")
        st.stop()

if len(coords) <= 1:
    st.error("Keine Abholfenster im Input gefunden – prüfe 'Abholung 1 von/bis'.")
    st.stop()

# ── Schritt 2: Matrix ───────────────────────────────────────────────
with st.spinner("Berechne Fahrzeit-Matrix (OSRM) …"):
    try:
        time_matrix_min, dist_matrix_m = build_matrices(coords)
    except Exception as e:
        st.error(f"Fehler bei Matrix-Berechnung: {e}")
        st.stop()

# ── Schritt 3: Prechecks ────────────────────────────────────────────
depot_windows = depot_union_windows(depot, solve_cfg)
stats = summarize_input(df, node_meta_df)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Einsender",     stats["einsender_rows"])
c2.metric("Pflicht-Nodes", stats["mandatory_nodes_created"])
c3.metric("Fahrzeuge",     num_vehicles)
c4.metric("Leere Fenster", stats["tw1_empty"] + stats["tw2_empty"])

problems = (
    check_depot_union(depot_windows)
    + check_basic_nodes(node_tws, labels)
    + check_matrix_sanity(time_matrix_min)
    + check_reachability_quick(node_tws, service_mins, time_matrix_min, depot_windows, labels)
)
if problems:
    with st.expander(f"⚠️ {len(problems)} Precheck-Problem(e) gefunden", expanded=True):
        for p in problems[:80]:
            st.warning(p)

# ── Schritt 4: Optimieren ───────────────────────────────────────────
is_relaxed = False
with st.spinner("Optimiere Routen …"):
    try:
        result = solve_vrptw(depot, solve_cfg, time_matrix_min, node_tws, service_mins)
        routes = result["routes"]
        st.success(f"✅ Harte Lösung gefunden – {len(routes)} Route(n).")

    except RuntimeError as exc:
        if str(exc) != "INFEASIBLE":
            st.exception(exc)
            st.stop()

        st.error("❌ Keine harte Lösung. Berechne Debug-Relaxation …")
        relaxed = solve_vrptw_relaxed_soft_timewindows(
            depot, solve_cfg, time_matrix_min, node_tws, service_mins,
            soft_penalty_per_min=1000,
        )
        if relaxed is None:
            st.error("Auch die Relaxierung liefert keine Lösung. Prüfe Matrix und Depotfenster.")
            st.stop()

        routes    = relaxed["routes"]
        is_relaxed = True

        violations = relaxed["violations"]
        with st.expander(f"🔎 {len(violations)} Zeitfenster-Verletzungen (relaxed)", expanded=True):
            for v in violations[:20]:
                s, e = v["tw"]
                st.warning(
                    f"**{labels[v['node']]}** @ {v['time_min']} min "
                    f"(TW {s}–{e}) | zu spät: {v['late_min']} min | zu früh: {v['early_min']} min"
                )

# ── Schritt 5: Ergebnisse anzeigen ──────────────────────────────────
tab_map, tab_routes, tab_dl = st.tabs(["🗺️ Karte", "📋 Routen", "📥 Download"])

with tab_map:
    m = export_routes_map_html(routes=routes, labels=labels, coords=coords)
    components.html(m._repr_html_(), height=620)

with tab_routes:
    for i, route in enumerate(routes, start=1):
        with st.expander(f"Route #{i}  ({len(route) - 1} Stopps + Depot)", expanded=True):
            rows = [
                {
                    "Ankunft": fmt_min_to_hhmm(solve_cfg.reference_date, int(step[1])),
                    "Node":    labels[step[0]],
                    "Wartezeit": f"{int(step[2])} min" if len(step) > 2 else "—",
                }
                for step in route
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)

with tab_dl:
    excel_bytes = export_solution_to_excel(
        day=solve_cfg.reference_date,
        routes=routes,
        labels=labels,
        coords=coords,
        node_meta_df=node_meta_df,
        time_matrix_min=time_matrix_min,
        dist_matrix_m=dist_matrix_m,
        node_service_mins=service_mins,
    )
    fname = "solution_relaxed.xlsx" if is_relaxed else "solution.xlsx"
    st.download_button(
        label="📊 Excel herunterladen",
        data=excel_bytes,
        file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
