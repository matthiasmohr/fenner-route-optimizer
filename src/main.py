from __future__ import annotations

import warnings
from datetime import date

from config import DepotConfig, SolveConfig
from io_excel import (
load_einsender_excel,
build_nodes_mandatory_both_windows,
depot_union_windows,
)
from matrix import build_matrices
from solver import (
solve_vrptw,
solve_vrptw_relaxed_soft_timewindows,
fmt_min_to_hhmm,
)
from export_excel import export_solution_to_excel
from export_map import export_routes_map_html
from debug_checks import (
check_basic_nodes,
check_depot_union,
check_matrix_sanity,
check_reachability_quick,
summarize_input,
)


def main():
    # ------------------------------------------------------------
    # Optional: OpenPyXL-Excel-Warnungen unterdrücken (harmlos)
    # ------------------------------------------------------------
    warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

    # ------------------------------------------------------------
    # Dateien / Outputs
    # ------------------------------------------------------------
    excel_in = "einsender.xlsx"

    # Normale Outputs (nur wenn "harte" Lösung gefunden wurde)
    excel_out = "solution.xlsx"
    map_out = "solution_map.html"

    # Debug-Outputs (wenn keine harte Lösung gefunden wurde)
    debug_excel_out = "solution_relaxed.xlsx"
    debug_map_out = "solution_relaxed_map.html"

    # ------------------------------------------------------------
    # Depot / Labor Parameter
    # ------------------------------------------------------------

    depot = DepotConfig(
        lat=53.054218,
        lon=9.031621,
        depot_1_von="11:00", depot_1_bis="11:30",
        depot_2_von="14:00", depot_2_bis="14:30",
        depot_3_von="17:30", depot_3_bis="18:00",
    )

    # ------------------------------------------------------------
    # Solver Parameter
    # ------------------------------------------------------------
    solve_cfg = SolveConfig(
        num_vehicles=6,
        reference_date=date.today(),  # oder z.B. date(2026, 1, 12)
        default_service_min=5,
        max_wait_min=240,
        max_route_duration_min=0,
    )

    # ------------------------------------------------------------
    # 1) Input laden
    # ------------------------------------------------------------
    df = load_einsender_excel(excel_in, solve_cfg)

    # Nodes: pro Einsender werden Pickup 1 und Pickup 2 (falls vorhanden) als Pflicht-Nodes erzeugt
    coords, node_tws, service_mins, labels, node_meta_df = build_nodes_mandatory_both_windows(
        depot, df, solve_cfg
    )

    if len(coords) <= 1:
        raise RuntimeError(
            "Keine Abholfenster im Input gefunden (keine Kunden-Nodes). "
            "Prüfe die Spalten 'Abholung 1 von/bis' und 'Abholung 2 von/bis'."
        )

    # ------------------------------------------------------------
    # 2) Matrix bauen (OSRM default; Google via env MATRIX_PROVIDER=GOOGLE)
    # ------------------------------------------------------------
    time_matrix_min, dist_matrix_m = build_matrices(coords)

    # ------------------------------------------------------------
    # 3) Vorab-Checks (sehr hilfreich bei Infeasible)
    # ------------------------------------------------------------
    depot_windows = depot_union_windows(depot, solve_cfg)

    print("Input-Statistik:", summarize_input(df, node_meta_df))

    problems = []
    problems += check_depot_union(depot_windows)
    problems += check_basic_nodes(node_tws, labels)
    problems += check_matrix_sanity(time_matrix_min)
    problems += check_reachability_quick(
        node_tws, service_mins, time_matrix_min, depot_windows, labels
    )

    if problems:
        print("\n=== PRECHECK PROBLEMS (mögliche Ursachen) ===")
        for p in problems[:80]:
            print(" -", p)
        if len(problems) > 80:
            print(f" ... {len(problems) - 80} weitere")
        print("=== Ende PRECHECK ===\n")

    # ------------------------------------------------------------
    # 4) Solve (hart) – MUSS bedient werden
    # ------------------------------------------------------------
    try:
        result = solve_vrptw(
            depot=depot,
            solve_cfg=solve_cfg,
            time_matrix_min=time_matrix_min,
            node_time_windows=node_tws,
            node_service_mins=service_mins,
        )
    except RuntimeError as e:
        # solve_vrptw wirft bei Unlösbarkeit "INFEASIBLE"
        if str(e) != "INFEASIBLE":
            raise

        print("\n❌ Keine harte Lösung gefunden.")
        print("Starte Debug-Relax-Solve (soft time windows), um Engpässe zu identifizieren...\n")

        relaxed = solve_vrptw_relaxed_soft_timewindows(
            depot=depot,
            solve_cfg=solve_cfg,
            time_matrix_min=time_matrix_min,
            node_time_windows=node_tws,
            node_service_mins=service_mins,
            soft_penalty_per_min=1000,
        )

        if relaxed is None:
            print("Auch Relax-Solve findet nichts. Dann ist meist die Matrix oder Depotfenster-Union kaputt.")
            raise RuntimeError("Keine Lösung (auch relaxed).")

        # Größte Zeitfenster-Verletzungen zeigen
        violations = relaxed["violations"]
        print("=== Größte Zeitfenster-Verletzungen (Top 20) ===")
        for v in violations[:20]:
            node = v["node"]
            s, e2 = v["tw"]
            print(
                f"- {labels[node]} @ {v['time_min']}min "
                f"(TW {s}-{e2})  late={v['late_min']}  early={v['early_min']}"
            )

        # Debug-Exports erstellen (damit du die 'fast-Lösung' ansehen kannst)
        routes = relaxed["routes"]
        export_solution_to_excel(
            out_path=debug_excel_out,
            day=solve_cfg.reference_date,
            routes=routes,
            labels=labels,
            coords=coords,
            node_meta_df=node_meta_df,
        )
        export_routes_map_html(
            out_html=debug_map_out,
            routes=routes,
            labels=labels,
            coords=coords,
        )

        print(f"\n🔎 Debug-Exports erstellt: {debug_excel_out} + {debug_map_out}")
        raise RuntimeError("Keine harte Lösung – siehe Debug-Ausgaben/Relax-Exports.")

    # ------------------------------------------------------------
    # 5) Ergebnis ausgeben + Exporte (harte Lösung)
    # ------------------------------------------------------------
    routes = result["routes"]

    print("Depot-Zeitfenster (Union):")
    for s, e in result["depot_windows"]:
        print(f"  {fmt_min_to_hhmm(solve_cfg.reference_date, s)} - {fmt_min_to_hhmm(solve_cfg.reference_date, e)}")
    print()

    for i, route in enumerate(routes, start=1):
        print(f"Route #{i}")
        for node, tmin, slack in route:
            print(f"  {fmt_min_to_hhmm(solve_cfg.reference_date, tmin)} (+wait {slack}m) -> {labels[node]}")
        print()

    # Exporte: Excel + Karte
    export_solution_to_excel(
        out_path=excel_out,
        day=solve_cfg.reference_date,
        routes=routes,
        labels=labels,
        coords=coords,
        node_meta_df=node_meta_df,
        time_matrix_min=time_matrix_min,
        dist_matrix_m=dist_matrix_m,
        node_service_mins=service_mins,
    )

    export_routes_map_html(
        out_html=map_out,
        routes=routes,
        labels=labels,
        coords=coords,
    )

    print(f"✅ Excel exportiert: {excel_out}")
    print(f"✅ Karte exportiert: {map_out}")


if __name__ == "__main__":
    main()
