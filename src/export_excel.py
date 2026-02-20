from __future__ import annotations

import pandas as pd
from datetime import datetime, date, time, timedelta


def fmt_min_to_datetime(day: date, mins: int) -> datetime:
    return datetime.combine(day, time(0, 0)) + timedelta(minutes=mins)


def export_solution_to_excel(
        out_path: str,
        day: date,
        routes: list[list[tuple]],
        labels: list[str],
        coords: list[tuple[float, float]],
        node_meta_df: pd.DataFrame,
        time_matrix_min: list[list[int]],
        dist_matrix_m: list[list[int]],
        node_service_mins: list[int],
):
    """
    Exportiert:
      Sheet "routes": Zeile pro Stopp (inkl. Segmentzeiten/-distanzen)
      Sheet "route_totals": Summen je Route (km, Fahrzeit, Wartezeit, Service, Gesamt)
      Sheet "nodes": Node-Metadaten
      Sheet "summary": Überblick

    routes kann Steps enthalten als:
      - (node, tmin) oder
      - (node, tmin, irgendwas)
    Wir verwenden IMMER node = step[0], tmin = step[1].
    Wartezeit berechnen wir EXAKT aus Differenzen der CumulTimes.
    """

    rows = []
    totals = []

    for r_idx, route in enumerate(routes, start=1):
        if len(route) < 2:
            continue

        drive_sum = 0
        wait_sum = 0
        service_sum = 0
        dist_sum_m = 0

        for seq, step in enumerate(route):
            node = step[0]
            tmin = int(step[1])

            lat, lon = coords[node]

            # Segmentwerte (vom Vorgänger auf diesen Node)
            if seq == 0:
                prev_node = None
                travel = 0
                dist_m = 0
                service = 0
                wait = 0
            else:
                prev_step = route[seq - 1]
                prev_node = prev_step[0]
                prev_tmin = int(prev_step[1])

                travel = int(time_matrix_min[prev_node][node])
                dist_m = int(dist_matrix_m[prev_node][node])

                # Service ist in deinem Modell am Zielknoten im Transit enthalten
                service = int(node_service_mins[node]) if node != 0 else 0

                # EXAKTE Wartezeit (kann 0 sein, oder >0 wenn Zeitfenster/Depotfenster erzwingt)
                wait = tmin - prev_tmin - travel - service
                if wait < 0:
                    # numerische Rundungen / Matrix-Minuten können das leicht negativ machen -> clamp
                    wait = 0

                drive_sum += travel
                wait_sum += wait
                service_sum += service
                dist_sum_m += dist_m

            rows.append({
                "route_id": r_idx,
                "seq": seq,
                "node_index": node,
                "label": labels[node],
                "arrival_time": fmt_min_to_datetime(day, tmin),
                "arrival_min": tmin,
                "prev_node_index": prev_node,
                "travel_min_from_prev": travel,
                "wait_min_from_prev": wait,
                "service_min_at_node": service,
                "segment_total_min": travel + wait + service,
                "dist_m_from_prev": dist_m,
                "dist_km_from_prev": dist_m / 1000.0,
                "lat": lat,
                "lon": lon,
            })

        totals.append({
            "route_id": r_idx,
            "total_dist_km": dist_sum_m / 1000.0,
            "total_drive_min": drive_sum,
            "total_wait_min": wait_sum,
            "total_service_min": service_sum,
            "total_time_min": drive_sum + wait_sum + service_sum,
        })

    routes_df = pd.DataFrame(rows)
    totals_df = pd.DataFrame(totals)

    summary_df = pd.DataFrame([{
        "routes_used": int(len(totals_df)),
        "total_stops_including_depot": int(routes_df.shape[0]),
        "unique_customer_nodes": int(max(0, len(coords) - 1)),
        "total_dist_km_all_routes": float(totals_df["total_dist_km"].sum()) if not totals_df.empty else 0.0,
        "total_drive_min_all_routes": int(totals_df["total_drive_min"].sum()) if not totals_df.empty else 0,
        "total_wait_min_all_routes": int(totals_df["total_wait_min"].sum()) if not totals_df.empty else 0,
        "total_time_min_all_routes": int(totals_df["total_time_min"].sum()) if not totals_df.empty else 0,
    }])

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        routes_df.to_excel(writer, index=False, sheet_name="routes")
        totals_df.to_excel(writer, index=False, sheet_name="route_totals")
        node_meta_df.to_excel(writer, index=False, sheet_name="nodes")
        summary_df.to_excel(writer, index=False, sheet_name="summary")
