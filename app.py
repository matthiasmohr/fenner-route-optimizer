"""
Streamlit Web-Frontend für die Fenner Tourenoptimierung.
Starten: streamlit run app.py
"""
from __future__ import annotations

import warnings
from datetime import date, datetime, time as dt_time

import pandas as pd
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
from src.route_stats import compute_route_totals
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
    num_vehicles  = st.number_input("Anzahl Fahrzeuge",        min_value=1, max_value=30,  value=6)
    service_min   = st.number_input("Servicezeit (min)",        min_value=0, max_value=60,  value=5)
    max_wait      = st.number_input("Max. Wartezeit (min)",     min_value=0, max_value=480, value=240)
    max_route_dur = st.number_input("Max. Tourdauer (min)",     min_value=0, max_value=720, value=240,
                                    help="0 = keine Begrenzung. Standard: 240 min (4 Stunden)")
    ref_date      = st.date_input("Referenzdatum", value=date.today())

    st.subheader("Kosten")
    cost_ct_per_km = st.number_input("Streckenkosten (ct/km)", min_value=0, max_value=500, value=30,
                                      help="Kosten pro gefahrenem Kilometer in Cent")
    cost_eur_per_h = st.number_input("Zeitkosten (EUR/h)", min_value=0.0, max_value=200.0, value=35.0,
                                      step=0.5, format="%.2f",
                                      help="Kosten pro Stunde (Fahrzeit + Wartezeit + Service)")

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
    max_route_duration_min=max_route_dur,
)
# Basiszeit für Uhrzeitumrechnung (00:00 des Referenzdatums)
time_origin = datetime.combine(ref_date, dt_time(0, 0))

# ── Schritt 1: Daten laden ──────────────────────────────────────────
with st.spinner("Lade Eingabedaten …"):
    try:
        df = load_einsender_excel(uploaded, solve_cfg)
        coords, node_tws, service_mins, labels, node_senders, node_addresses, node_meta_df = (
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

m1, m2, m3, m4 = st.columns(4)
m1.metric("Einsender",     stats["einsender_rows"])
m2.metric("Pflicht-Nodes", stats["mandatory_nodes_created"])
m3.metric("Fahrzeuge",     num_vehicles)
m4.metric("Leere Fenster", stats["tw1_empty"] + stats["tw2_empty"])

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

        routes     = relaxed["routes"]
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
tab_map, tab_routes, tab_einsender, tab_costs, tab_dl = st.tabs(
    ["🗺️ Karte", "📋 Routen", "🏥 Einsender", "💰 Kosten", "📥 Download"]
)

# ── Tab: Karte ──────────────────────────────────────────────────────
with tab_map:
    m = export_routes_map_html(
        routes=routes,
        labels=labels,
        coords=coords,
        node_senders=node_senders,
        node_addresses=node_addresses,
        time_origin=time_origin,
    )
    components.html(m._repr_html_(), height=640)

# ── Tab: Routen ─────────────────────────────────────────────────────
with tab_routes:
    for i, route in enumerate(routes, start=1):
        n_stops = sum(1 for step in route if step[0] != 0)
        with st.expander(f"Route #{i}  –  {n_stops} Stopp(s)", expanded=True):
            rows = []
            for step in route:
                node = step[0]
                tmin = int(step[1])
                slack = int(step[2]) if len(step) > 2 else 0
                rows.append({
                    "Uhrzeit":   fmt_min_to_hhmm(solve_cfg.reference_date, tmin),
                    "Einsender": node_senders[node] if node_senders[node] else "LABOR (Depot)",
                    "Adresse":   node_addresses[node],
                    "Wartezeit": f"{slack} min" if slack else "—",
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)

# ── Tab: Einsender ──────────────────────────────────────────────────
with tab_einsender:
    # Baue Mapping: node_index → (route_id, arrival_min)
    node_to_route: dict[int, tuple[int, int]] = {}
    for r_idx, route in enumerate(routes, start=1):
        for step in route:
            node = step[0]
            tmin = int(step[1])
            if node != 0:
                node_to_route[node] = (r_idx, tmin)

    einsender_rows = []
    for _, meta in node_meta_df.iterrows():
        node_idx = int(meta["node_index"])
        route_id, arrival = node_to_route.get(node_idx, (None, None))

        tw_s = fmt_min_to_hhmm(solve_cfg.reference_date, int(meta["tw_start_min"]))
        tw_e = fmt_min_to_hhmm(solve_cfg.reference_date, int(meta["tw_end_min"]))

        einsender_rows.append({
            "Einsender":   meta.get("einsender_name", meta["einsender_id"]),
            "Adresse":     meta.get("adresse", ""),
            "Abholung":    f"Abh. {int(meta['pickup_no'])}",
            "Route":       f"Route {route_id}" if route_id else "—",
            "Ankunft":     fmt_min_to_hhmm(solve_cfg.reference_date, arrival) if arrival is not None else "—",
            "Zeitfenster": f"{tw_s} – {tw_e}",
        })

    einsender_df = pd.DataFrame(einsender_rows)
    st.dataframe(einsender_df, use_container_width=True, hide_index=True)

# ── Tab: Kosten ────────────────────────────────────────────────────
with tab_costs:
    route_totals = compute_route_totals(routes, time_matrix_min, dist_matrix_m, service_mins)

    cost_rows = []
    sum_dist = 0.0
    sum_drive = 0
    sum_wait = 0
    sum_service = 0
    sum_time = 0
    sum_cost_dist = 0.0
    sum_cost_time = 0.0
    sum_cost_total = 0.0

    for rt in route_totals:
        k_strecke = rt["total_dist_km"] * (cost_ct_per_km / 100.0)
        k_zeit = rt["total_time_min"] * (cost_eur_per_h / 60.0)
        k_gesamt = k_strecke + k_zeit

        sum_dist += rt["total_dist_km"]
        sum_drive += rt["total_drive_min"]
        sum_wait += rt["total_wait_min"]
        sum_service += rt["total_service_min"]
        sum_time += rt["total_time_min"]
        sum_cost_dist += k_strecke
        sum_cost_time += k_zeit
        sum_cost_total += k_gesamt

        cost_rows.append({
            "Route": f"Route {rt['route_id']}",
            "Stopps": rt["n_stops"],
            "Distanz (km)": f"{rt['total_dist_km']:.1f}",
            "Fahrzeit (min)": rt["total_drive_min"],
            "Wartezeit (min)": rt["total_wait_min"],
            "Service (min)": rt["total_service_min"],
            "Gesamtzeit (min)": rt["total_time_min"],
            "Strecke (EUR)": f"{k_strecke:.2f}",
            "Zeit (EUR)": f"{k_zeit:.2f}",
            "Gesamt (EUR)": f"{k_gesamt:.2f}",
        })

    # Summenzeile
    cost_rows.append({
        "Route": "GESAMT",
        "Stopps": sum(rt["n_stops"] for rt in route_totals),
        "Distanz (km)": f"{sum_dist:.1f}",
        "Fahrzeit (min)": sum_drive,
        "Wartezeit (min)": sum_wait,
        "Service (min)": sum_service,
        "Gesamtzeit (min)": sum_time,
        "Strecke (EUR)": f"{sum_cost_dist:.2f}",
        "Zeit (EUR)": f"{sum_cost_time:.2f}",
        "Gesamt (EUR)": f"{sum_cost_total:.2f}",
    })

    # Kennzahlen-Kacheln
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Gesamtkosten", f"{sum_cost_total:.2f} EUR")
    k2.metric("davon Strecke", f"{sum_cost_dist:.2f} EUR")
    k3.metric("davon Zeit", f"{sum_cost_time:.2f} EUR")
    k4.metric("Gesamt-km", f"{sum_dist:.1f} km")

    st.dataframe(cost_rows, use_container_width=True, hide_index=True)

# ── Tab: Download ────────────────────────────────────────────────────
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
