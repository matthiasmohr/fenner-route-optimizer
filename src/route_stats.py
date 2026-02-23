"""Wiederverwendbare Berechnung von Routen-Kennzahlen (Distanz, Zeit, …)."""

from __future__ import annotations


def compute_route_totals(
        routes: list[list[tuple]],
        time_matrix_min: list[list[int]],
        dist_matrix_m: list[list[int]],
        node_service_mins: list[int],
) -> list[dict]:
    """
    Berechnet pro Route aggregierte Kennzahlen.

    Rückgabe: Liste von Dicts, eines pro Route:
        route_id          int   – laufende Nummer (ab 1)
        n_stops           int   – Anzahl Kundenstopps (ohne Depot)
        total_dist_km     float – Gesamtdistanz in km
        total_drive_min   int   – reine Fahrzeit in Minuten
        total_wait_min    int   – Wartezeit in Minuten
        total_service_min int   – Servicezeit in Minuten
        total_time_min    int   – Gesamtzeit (Fahrt + Warten + Service)
    """
    totals: list[dict] = []

    for r_idx, route in enumerate(routes, start=1):
        if len(route) < 2:
            continue

        drive_sum = 0
        wait_sum = 0
        service_sum = 0
        dist_sum_m = 0
        n_stops = 0

        for seq, step in enumerate(route):
            node = step[0]
            tmin = int(step[1])

            if seq == 0:
                continue  # Depot-Start – kein Segment

            prev_step = route[seq - 1]
            prev_node = prev_step[0]
            prev_tmin = int(prev_step[1])

            travel = int(time_matrix_min[prev_node][node])
            dist_m = int(dist_matrix_m[prev_node][node])
            service = int(node_service_mins[node]) if node != 0 else 0

            wait = tmin - prev_tmin - travel - service
            if wait < 0:
                wait = 0

            drive_sum += travel
            wait_sum += wait
            service_sum += service
            dist_sum_m += dist_m

            if node != 0:
                n_stops += 1

        totals.append({
            "route_id": r_idx,
            "n_stops": n_stops,
            "total_dist_km": dist_sum_m / 1000.0,
            "total_drive_min": drive_sum,
            "total_wait_min": wait_sum,
            "total_service_min": service_sum,
            "total_time_min": drive_sum + wait_sum + service_sum,
        })

    return totals
