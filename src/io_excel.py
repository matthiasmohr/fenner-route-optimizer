from __future__ import annotations

import pandas as pd
from datetime import datetime, date, time
from dateutil import parser as dtparser

from .config import SolveConfig, DepotConfig


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    cols = {}
    for c in df.columns:
        cc = str(c).strip().lower()
        cc = " ".join(cc.split())
        cols[c] = cc
    return df.rename(columns=cols)


def parse_to_datetime(val, ref_date: date) -> datetime:
    """
    Unterstützt:
      - "08:00"
      - "2026-01-07 08:00"
      - pandas Timestamp / datetime
    """
    if pd.isna(val):
        raise ValueError("Zeitwert ist leer/NaN")

    if isinstance(val, (pd.Timestamp, datetime)):
        return pd.Timestamp(val).to_pydatetime()

    s = str(val).strip()
    if ":" in s and len(s) <= 5:
        t = dtparser.parse(s).time()
        return datetime.combine(ref_date, t)

    return dtparser.parse(s)


def minutes_from_day_start(dt: datetime, day: date) -> int:
    base = datetime.combine(day, time(0, 0))
    return int((dt - base).total_seconds() // 60)


def parse_optional_window(von, bis, ref_date: date) -> tuple[int, int] | None:
    if von is None or bis is None or pd.isna(von) or pd.isna(bis):
        return None
    sdt = parse_to_datetime(von, ref_date)
    edt = parse_to_datetime(bis, ref_date)
    s = minutes_from_day_start(sdt, ref_date)
    e = minutes_from_day_start(edt, ref_date)
    if e < s:
        raise ValueError(f"Zeitfenster endet vor Start: {von} - {bis}")
    return (s, e)


def load_einsender_excel(path: str, solve_cfg: SolveConfig) -> pd.DataFrame:
    """
    Erwartete Spalten (case-insensitive):
      - einsender (Freitext-Name)
      - adresse   (Freitext-Adresse)
      - id oder name (optional, Fallback)
      - lat, lon
      - abholung 1 von, abholung 1 bis
      - abholung 2 von, abholung 2 bis
      - service_min (optional)
    """
    df = pd.read_excel(path)
    df = normalize_column_names(df)

    required = {
        "lat", "lon",
        "abholung 1 von", "abholung 1 bis",
        "abholung 2 von", "abholung 2 bis",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Fehlende Spalten in Excel: {sorted(missing)}")

    if "id" not in df.columns and "name" not in df.columns:
        df["id"] = [f"stop_{i}" for i in range(len(df))]

    if "service_min" not in df.columns:
        df["service_min"] = solve_cfg.default_service_min

    df["tw1"] = df.apply(
        lambda r: parse_optional_window(r["abholung 1 von"], r["abholung 1 bis"], solve_cfg.reference_date),
        axis=1,
    )
    df["tw2"] = df.apply(
        lambda r: parse_optional_window(r["abholung 2 von"], r["abholung 2 bis"], solve_cfg.reference_date),
        axis=1,
    )

    return df


def depot_union_windows(depot: DepotConfig, solve_cfg: SolveConfig) -> list[tuple[int, int]]:
    """
    Liefert UNION der Depotfenster als sortierte, ggf. gemergte Liste.
    """
    day = solve_cfg.reference_date
    wins = []

    for von, bis in [
        (depot.depot_1_von, depot.depot_1_bis),
        (depot.depot_2_von, depot.depot_2_bis),
        (depot.depot_3_von, depot.depot_3_bis),
    ]:
        w = parse_optional_window(von, bis, day)
        if w:
            wins.append(w)

    if not wins:
        raise ValueError("Depot hat kein gültiges Zeitfenster.")

    wins.sort()

    merged: list[tuple[int, int]] = []
    for s, e in wins:
        if not merged:
            merged.append((s, e))
        else:
            ps, pe = merged[-1]
            if s <= pe + 1:
                merged[-1] = (ps, max(pe, e))
            else:
                merged.append((s, e))
    return merged


def build_nodes_mandatory_both_windows(
        depot: DepotConfig,
        df: pd.DataFrame,
        solve_cfg: SolveConfig,
):
    """
    Modell:
      - Node 0: Depot (Labor)
      - Für jeden Einsender:
          - Wenn tw1 vorhanden -> Node "Einsender (Abh. 1)" Pflicht
          - Wenn tw2 vorhanden -> Node "Einsender (Abh. 2)" Pflicht
        => wenn beide vorhanden: beide müssen bedient werden (kein ODER)

    Rückgabe:
      coords:         [(lat, lon), ...]
      node_tws:       [None/tuple] (Depot None, sonst Pflicht-Zeitfenster)
      service_mins:   [int] (Depot 0)
      labels:         [str] – sprechend: Einsendername (+ Abh.-Nr. wenn mehrere)
      node_senders:   [str] – Einsendername je Node (Depot = "")
      node_addresses: [str] – Adresse je Node (Depot = "")
      node_meta:      DataFrame für Export (mapping node -> einsender/pickup)
    """
    coords:         list[tuple[float, float]] = [(depot.lat, depot.lon)]
    node_tws:       list[tuple[int, int] | None] = [None]
    service_mins:   list[int] = [0]
    labels:         list[str] = ["LABOR"]
    node_senders:   list[str] = [""]
    node_addresses: list[str] = [""]

    meta_rows = []

    for _, r in df.iterrows():
        fallback_id   = str(r.get("id", r.get("name", ""))).strip()
        einsender_str = str(r.get("einsender", fallback_id)).strip() or fallback_id
        adresse_str   = str(r.get("adresse", "")).strip()

        lat     = float(r["lat"])
        lon     = float(r["lon"])
        service = int(r.get("service_min", solve_cfg.default_service_min))

        tws = [(1, r["tw1"]), (2, r["tw2"])]
        active_pickups = [(no, tw) for no, tw in tws if tw is not None]

        for pickup_no, tw in active_pickups:
            # Bei mehreren Abholungen Nr. anhängen, sonst nur Name
            if len(active_pickups) > 1:
                label = f"{einsender_str} (Abh. {pickup_no})"
            else:
                label = einsender_str

            coords.append((lat, lon))
            node_tws.append(tw)
            service_mins.append(service)
            labels.append(label)
            node_senders.append(einsender_str)
            node_addresses.append(adresse_str)

            node_index = len(coords) - 1
            meta_rows.append({
                "node_index":     node_index,
                "einsender_id":   fallback_id,
                "einsender_name": einsender_str,
                "adresse":        adresse_str,
                "pickup_no":      pickup_no,
                "lat":            lat,
                "lon":            lon,
                "tw_start_min":   tw[0],
                "tw_end_min":     tw[1],
                "service_min":    service,
            })

    meta_df = pd.DataFrame(meta_rows)
    return coords, node_tws, service_mins, labels, node_senders, node_addresses, meta_df
