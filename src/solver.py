from __future__ import annotations

from datetime import datetime, date, time, timedelta
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .config import SolveConfig
from .io_excel import depot_union_windows


def restrict_intvar_to_union(intvar, windows: list[tuple[int, int]]):
    """
    Erlaubt nur Werte innerhalb der Union von Zeitfenstern.
    Beispiel: [(660, 690), (840, 870)] => CumulVar darf nur in diesen Bereichen liegen.
    """
    min_start = windows[0][0]
    max_end = windows[-1][1]
    intvar.SetRange(min_start, max_end)

    # Entferne die Lücken zwischen den Fenstern.
    for (s1, e1), (s2, e2) in zip(windows, windows[1:]):
        gap_start = e1 + 1
        gap_end = s2 - 1
        if gap_start <= gap_end:
            intvar.RemoveInterval(gap_start, gap_end)


def _pseudo_wait_from_timewindow(
        node: int,
        arrival_min: int,
        node_time_windows: list[tuple[int, int] | None],
) -> int:
    """
    Robust gegen OR-Tools SlackVar-Probleme (Python 3.13):
    Wir berechnen eine 'Wartezeit' als:
      wait = max(0, TW_start - arrival_time)
    Das entspricht dem klassischen 'zu früh angekommen, muss warten bis Fenster öffnet'.

    Achtung:
    - Das ist NICHT exakt die interne SlackVar des Solvers (der kann Warten auch anders verteilen),
      aber es ist für Debug & Output meistens das, was man fachlich sehen will.
    """
    if node == 0:
        return 0
    tw = node_time_windows[node]
    if tw is None:
        return 0
    tw_start, _tw_end = tw
    return max(0, tw_start - arrival_min)


def solve_vrptw(
        depot,
        solve_cfg: SolveConfig,
        time_matrix_min: list[list[int]],
        node_time_windows: list[tuple[int, int] | None],
        node_service_mins: list[int],
):
    """
    Pflichtbedienung:
      - Alle Kunden-Nodes (Index >=1) sind obligatorisch. Kein Drop.
      - Jeder Node hat genau 1 Zeitfenster.

    Depot / Labor (WICHTIG: neue Anforderung):
      - Fahrzeuge dürfen jederzeit starten (Start-Zeit frei).
      - Sie müssen nur innerhalb der Depot-Öffnungszeiten ANKOMMEN (Ende in UNION der Depotfenster).
      => wir setzen Depotfenster nur auf routing.End(v), NICHT auf routing.Start(v).
    """
    n_locations = len(node_time_windows)
    if n_locations != len(time_matrix_min):
        raise ValueError("Matrixgröße passt nicht zur Node-Liste.")

    num_vehicles = max(1, solve_cfg.num_vehicles)

    manager = pywrapcp.RoutingIndexManager(n_locations, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    # Transitzeit = Fahrzeit + Servicezeit am Zielknoten
    def time_cb(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        travel = time_matrix_min[from_node][to_node]
        service = node_service_mins[to_node] if to_node != 0 else 0
        return travel + service

    transit_idx = routing.RegisterTransitCallback(time_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    horizon = 24 * 60

    # "Time"-Dimension: absoluter Taktgeber (Minuten seit 00:00).
    # capacity MUSS 24*60 sein – capacity ist der maximale absolute CumulVar-Wert,
    # NICHT die Tourdauer. Würde man hier max_route_duration_min übergeben,
    # kollidiert es mit Depotfenstern >= 660 min (11:00 Uhr).
    routing.AddDimension(
        transit_idx,
        solve_cfg.max_wait_min,  # max. Wartezeit (slack) pro Node
        horizon,                 # max. absoluter Zeitwert = 24 h
        False,
        "Time",
    )
    time_dim = routing.GetDimensionOrDie("Time")

    # "Duration"-Dimension: misst die reine Tourdauer ab Abfahrt (fix_start=True → startet bei 0).
    # Über capacity wird die Maximaldauer hart begrenzt.
    if solve_cfg.max_route_duration_min > 0:
        routing.AddDimension(
            transit_idx,
            solve_cfg.max_wait_min,
            solve_cfg.max_route_duration_min,
            True,   # fix_start_cumul_to_zero=True: CumulVar = vergangene Zeit seit Depot
            "Duration",
        )

    # Depotfenster: NUR fürs Ende (Einlieferung)
    depot_windows = depot_union_windows(depot, solve_cfg)

    for v in range(num_vehicles):
        # Start frei (kann sehr früh sein, falls nötig)
        time_dim.CumulVar(routing.Start(v)).SetRange(0, horizon)

        # Ende muss in Depot-Union liegen
        restrict_intvar_to_union(time_dim.CumulVar(routing.End(v)), depot_windows)

    # Kundenzeitfenster: harte Constraints
    for node in range(1, n_locations):
        tw = node_time_windows[node]
        if tw is None:
            raise RuntimeError("Kundennode ohne Zeitfenster gefunden.")
        idx = manager.NodeToIndex(node)
        time_dim.CumulVar(idx).SetRange(tw[0], tw[1])

    # Optional: reduziert oft „unnötig frühe“ Starts (minimiert Spannweite der Touren)
    # time_dim.SetGlobalSpanCostCoefficient(1)

    # Suchparameter
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(30)

    solution = routing.SolveWithParameters(params)
    if solution is None:
        raise RuntimeError("INFEASIBLE")

    # Extraktion: (node, arrival_time_min, pseudo_wait_min)
    routes = []
    for v in range(num_vehicles):
        idx = routing.Start(v)
        nxt = solution.Value(routing.NextVar(idx))
        if routing.IsEnd(nxt):
            continue

        route = []
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            tmin = solution.Value(time_dim.CumulVar(idx))
            pseudo_wait = _pseudo_wait_from_timewindow(node, tmin, node_time_windows)
            route.append((node, tmin, pseudo_wait))
            idx = solution.Value(routing.NextVar(idx))

        # Endknoten (Depot)
        node = manager.IndexToNode(idx)
        tmin = solution.Value(time_dim.CumulVar(idx))
        route.append((node, tmin, 0))

        # Fix: Depot-Startzeit korrigieren.
        # Der Solver setzt CumulVar(Start) oft auf 0, weil der Start-Zeitpunkt
        # keine Kostenwirkung hat. Wir berechnen die echte Abfahrtszeit aus dem
        # ersten Kundenstopp zurück: Ankunft_Kunde − Fahrzeit − Servicezeit.
        if len(route) >= 2:
            first_node = route[1][0]
            first_tmin = route[1][1]
            travel     = time_matrix_min[0][first_node]
            service    = node_service_mins[first_node]
            departure  = max(0, first_tmin - travel - service)
            route[0]   = (route[0][0], departure, route[0][2])

        routes.append(route)

    return {
        "routes": routes,
        "depot_windows": depot_windows,
    }


def solve_vrptw_relaxed_soft_timewindows(
        depot,
        solve_cfg: SolveConfig,
        time_matrix_min: list[list[int]],
        node_time_windows: list[tuple[int, int] | None],
        node_service_mins: list[int],
        soft_penalty_per_min: int = 1000,
):
    """
    Debug-Only:
    - Kundenzeitfenster werden 'soft': Verletzungen erlaubt, aber teuer.
    - Depot-Ende bleibt hart innerhalb der Depot-Union (Einlieferung muss in Öffnungszeit passieren).
    - Start bleibt frei.
    """
    n_locations = len(node_time_windows)
    num_vehicles = max(1, solve_cfg.num_vehicles)

    manager = pywrapcp.RoutingIndexManager(n_locations, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    def time_cb(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        travel = time_matrix_min[from_node][to_node]
        service = node_service_mins[to_node] if to_node != 0 else 0
        return travel + service

    transit_idx = routing.RegisterTransitCallback(time_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    horizon = 24 * 60

    routing.AddDimension(
        transit_idx,
        solve_cfg.max_wait_min,
        horizon,
        False,
        "Time",
    )
    time_dim = routing.GetDimensionOrDie("Time")

    if solve_cfg.max_route_duration_min > 0:
        routing.AddDimension(
            transit_idx,
            solve_cfg.max_wait_min,
            solve_cfg.max_route_duration_min,
            True,
            "Duration",
        )

    # Depot-Ende hart in Union, Start frei
    depot_windows = depot_union_windows(depot, solve_cfg)
    for v in range(num_vehicles):
        time_dim.CumulVar(routing.Start(v)).SetRange(0, horizon)
        restrict_intvar_to_union(time_dim.CumulVar(routing.End(v)), depot_windows)

    # Kunden-TWs soft: großer Range + SoftBounds
    for node in range(1, n_locations):
        tw = node_time_windows[node]
        if tw is None:
            raise RuntimeError("Kundennode ohne Zeitfenster gefunden.")
        idx = manager.NodeToIndex(node)

        time_dim.CumulVar(idx).SetRange(0, horizon)

        s, e = tw
        time_dim.SetCumulVarSoftLowerBound(idx, s, soft_penalty_per_min)
        time_dim.SetCumulVarSoftUpperBound(idx, e, soft_penalty_per_min)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(10)

    sol = routing.SolveWithParameters(params)
    if sol is None:
        return None

    # Extraktion: (node, arrival_time_min, pseudo_wait_min)
    routes = []
    for v in range(num_vehicles):
        idx = routing.Start(v)
        nxt = sol.Value(routing.NextVar(idx))
        if routing.IsEnd(nxt):
            continue

        route = []
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            tmin = sol.Value(time_dim.CumulVar(idx))
            pseudo_wait = _pseudo_wait_from_timewindow(node, tmin, node_time_windows)
            route.append((node, tmin, pseudo_wait))
            idx = sol.Value(routing.NextVar(idx))

        node = manager.IndexToNode(idx)
        tmin = sol.Value(time_dim.CumulVar(idx))
        route.append((node, tmin, 0))

        # Fix: Depot-Startzeit korrigieren (gleiche Logik wie solve_vrptw)
        if len(route) >= 2:
            first_node = route[1][0]
            first_tmin = route[1][1]
            travel     = time_matrix_min[0][first_node]
            service    = node_service_mins[first_node]
            departure  = max(0, first_tmin - travel - service)
            route[0]   = (route[0][0], departure, route[0][2])

        routes.append(route)

    # Verletzungen reporten (gegen Original-TWs)
    violations = []
    for node in range(1, n_locations):
        idx = manager.NodeToIndex(node)
        tmin = sol.Value(time_dim.CumulVar(idx))
        s, e = node_time_windows[node]
        early = max(0, s - tmin)
        late = max(0, tmin - e)
        if early or late:
            violations.append(
                {"node": node, "time_min": tmin, "early_min": early, "late_min": late, "tw": (s, e)}
            )

    violations.sort(key=lambda x: (x["late_min"], x["early_min"]), reverse=True)
    return {"routes": routes, "violations": violations, "depot_windows": depot_windows}


def fmt_min_to_hhmm(day: date, mins: int) -> str:
    dt = datetime.combine(day, time(0, 0)) + timedelta(minutes=mins)
    return dt.strftime("%H:%M")
