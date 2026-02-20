"""
CLI-Einstieg: python main.py
Web-Frontend: streamlit run app.py
"""
from __future__ import annotations

import warnings
from datetime import date

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


def main():
    warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

    # ── Dateipfade ──────────────────────────────────────────────────
    excel_in        = "src/einsender.xlsx"
    excel_out       = "solution.xlsx"
    map_out         = "solution_map.html"
    debug_excel_out = "solution_relaxed.xlsx"
    debug_map_out   = "solution_relaxed_map.html"

    # ── Depot / Labor ───────────────────────────────────────────────
    depot = DepotConfig(
        lat=53.054218,
        lon=9.031621,
        depot_1_von="11:00", depot_1_bis="11:30",
        depot_2_von="14:00", depot_2_bis="14:30",
        depot_3_von="17:30", depot_3_bis="18:00",
    )

    # ── Solver-Parameter ────────────────────────────────────────────
    solve_cfg = SolveConfig(
        num_vehicles=6,
        reference_date=date.today(),
        default_service_min=5,
        max_wait_min=240,
        max_route_duration_min=0,
    )

    # ── 1) Input laden ──────────────────────────────────────────────
    df = load_einsender_excel(excel_in, solve_cfg)
    coords, node_tws, service_mins, labels, node_meta_df = (
        build_nodes_mandatory_both_windows(depot, df, solve_cfg)
    )

    if len(coords) <= 1:
        raise RuntimeError(
            "Keine Abholfenster im Input gefunden. "
            "Prüfe die Spalten 'Abholung 1 von/bis' und 'Abholung 2 von/bis'."
        )

    # ── 2) Matrix bauen ─────────────────────────────────────────────
    time_matrix_min, dist_matrix_m = build_matrices(coords)

    # ── 3) Vorab-Checks ─────────────────────────────────────────────
    depot_windows = depot_union_windows(depot, solve_cfg)
    print("Input-Statistik:", summarize_input(df, node_meta_df))

    problems = (
        check_depot_union(depot_windows)
        + check_basic_nodes(node_tws, labels)
        + check_matrix_sanity(time_matrix_min)
        + check_reachability_quick(node_tws, service_mins, time_matrix_min, depot_windows, labels)
    )
    if problems:
        print("\n=== PRECHECK PROBLEMS ===")
        for p in problems[:80]:
            print(" -", p)
        if len(problems) > 80:
            print(f" ... {len(problems) - 80} weitere")
        print("=== Ende PRECHECK ===\n")

    # ── 4) Solve (hart) ─────────────────────────────────────────────
    try:
        result = solve_vrptw(depot, solve_cfg, time_matrix_min, node_tws, service_mins)
    except RuntimeError as e:
        if str(e) != "INFEASIBLE":
            raise

        print("\n❌ Keine harte Lösung gefunden.")
        print("Starte Debug-Relax-Solve …\n")

        relaxed = solve_vrptw_relaxed_soft_timewindows(
            depot, solve_cfg, time_matrix_min, node_tws, service_mins,
            soft_penalty_per_min=1000,
        )
        if relaxed is None:
            raise RuntimeError("Keine Lösung (auch relaxed).")

        violations = relaxed["violations"]
        print(f"=== Größte Zeitfenster-Verletzungen (Top {min(20, len(violations))}) ===")
        for v in violations[:20]:
            s, e = v["tw"]
            print(
                f"  {labels[v['node']]} @ {v['time_min']}min "
                f"(TW {s}-{e})  late={v['late_min']}  early={v['early_min']}"
            )

        routes = relaxed["routes"]
        with open(debug_excel_out, "wb") as f:
            f.write(export_solution_to_excel(
                day=solve_cfg.reference_date, routes=routes, labels=labels,
                coords=coords, node_meta_df=node_meta_df,
                time_matrix_min=time_matrix_min, dist_matrix_m=dist_matrix_m,
                node_service_mins=service_mins,
            ))
        export_routes_map_html(routes=routes, labels=labels, coords=coords).save(debug_map_out)

        print(f"\n🔎 Debug-Exports: {debug_excel_out} + {debug_map_out}")
        raise RuntimeError("Keine harte Lösung – Debug-Exports erstellt.")

    # ── 5) Ergebnis ausgeben + Exporte ──────────────────────────────
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

    with open(excel_out, "wb") as f:
        f.write(export_solution_to_excel(
            day=solve_cfg.reference_date, routes=routes, labels=labels,
            coords=coords, node_meta_df=node_meta_df,
            time_matrix_min=time_matrix_min, dist_matrix_m=dist_matrix_m,
            node_service_mins=service_mins,
        ))
    export_routes_map_html(routes=routes, labels=labels, coords=coords).save(map_out)

    print(f"✅ Excel exportiert: {excel_out}")
    print(f"✅ Karte exportiert: {map_out}")


if __name__ == "__main__":
    main()
