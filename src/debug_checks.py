from __future__ import annotations

import math
import pandas as pd


def check_basic_nodes(node_tws, labels):
    """
    Prüft, ob alle Pflicht-Nodes ein Zeitfenster haben und ob Start<=Ende.
    """
    problems = []
    for i in range(1, len(node_tws)):
        tw = node_tws[i]
        if tw is None:
            problems.append(f"Node {i} ({labels[i]}): hat kein Zeitfenster (None)")
            continue
        s, e = tw
        if e < s:
            problems.append(f"Node {i} ({labels[i]}): ungültiges Zeitfenster {s}-{e}")
    return problems


def check_depot_union(depot_windows):
    """
    Prüft Depotfenster (Union) auf Plausibilität.
    """
    if not depot_windows:
        return ["Depot: keine Zeitfenster erkannt"]
    for s, e in depot_windows:
        if e < s:
            return [f"Depot: ungültiges Fenster {s}-{e}"]
    return []


def check_matrix_sanity(time_matrix_min, max_reasonable_min=24*60):
    """
    Prüft:
      - quadratisch
      - keine None
      - keine negativen Zeiten
      - keine extremen 'unendlich'-Werte (z.B. 1e6 aus Google fallback)
    """
    n = len(time_matrix_min)
    probs = []
    for i, row in enumerate(time_matrix_min):
        if len(row) != n:
            probs.append(f"Matrix: Zeile {i} hat Länge {len(row)} statt {n}")
            continue
        for j, v in enumerate(row):
            if v is None:
                probs.append(f"Matrix: None bei ({i},{j})")
            elif v < 0:
                probs.append(f"Matrix: negativ bei ({i},{j}) = {v}")
            elif v >= 1_000_000:
                probs.append(f"Matrix: 'unendlich' bei ({i},{j}) = {v} (Google status!=OK?)")
            elif v > max_reasonable_min:
                probs.append(f"Matrix: ungewöhnlich groß bei ({i},{j}) = {v} min")
    return probs


def check_reachability_quick(
        node_tws,
        service_mins,
        time_matrix_min,
        depot_windows,
        labels,
):
    """
    Neue Modellannahme:
      - Start ist frei (Abfahrt jederzeit möglich)
      - Ende muss in Depotfenster-Union liegen (Ankunft/Einlieferung)

    Notwendiger Check:
      Für jeden Node muss es ein Szenario geben, wo:
        Depot -> Node innerhalb Node-TW erreichbar ist (mit freiem Start)
        und danach Node -> Depot so, dass Ankunft in ein Depotfenster fällt.
    """
    probs = []

    def any_depot_window_can_accept(arrival_min: int) -> bool:
        # Ankunft kann auch "zu früh" sein -> warten bis Fenster öffnet.
        # Daher reicht: es gibt ein Fenster mit w_end >= arrival_min
        return any(arrival_min <= w_end for (w_start, w_end) in depot_windows)

    for node in range(1, len(node_tws)):
        s, e = node_tws[node]
        travel_to = time_matrix_min[0][node]
        travel_back = time_matrix_min[node][0]
        service = service_mins[node]

        # Mit freiem Start kann man die Ankunft im Node-Fenster immer "treffen",
        # solange travel_to endlich ist.
        if travel_to >= 1_000_000:
            probs.append(f"{labels[node]}: Depot->Node nicht routbar (Matrix='unendlich', travel={travel_to})")
            continue

        # Worst-case Rückkehr: wenn man am spätesten Zeitpunkt (TW-Ende) fertig wird
        latest_finish = e + service
        arrival_depot = latest_finish + travel_back

        if travel_back >= 1_000_000:
            probs.append(f"{labels[node]}: Node->Depot nicht routbar (Matrix='unendlich', travel_back={travel_back})")
            continue

        if not any_depot_window_can_accept(arrival_depot):
            probs.append(
                f"{labels[node]}: Rückkehr passt in kein Depotfenster. "
                f"Spätestes Finish {latest_finish} + Rückfahrt {travel_back} => Ankunft {arrival_depot}, "
                f"Depotfenster {depot_windows}."
            )

    return probs


def summarize_input(df: pd.DataFrame, node_meta_df: pd.DataFrame):
    """
    Hilfreiche Statistik: wie viele Einsender, wie viele Nodes (Pickups), wie viele leere Fenster.
    """
    total = len(df)
    tw1_empty = int(df["tw1"].isna().sum())
    tw2_empty = int(df["tw2"].isna().sum())
    nodes = len(node_meta_df)

    return {
        "einsender_rows": total,
        "tw1_empty": tw1_empty,
        "tw2_empty": tw2_empty,
        "mandatory_nodes_created": nodes,
    }
