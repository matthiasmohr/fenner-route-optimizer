from __future__ import annotations
import os
import json
import requests

# Maximale Anzahl *einzigartiger* Koordinaten pro OSRM-Request.
# Off-diagonal-Blöcke enthalten src + dst = 2 × CHUNK_SIZE Coords in der URL.
# Öffentlicher OSRM-Server limitiert die URL auf ~2000 Zeichen.
# Bei 25 sind das max. 50 Coords → ~1500 Zeichen, sicher darunter.
_OSRM_CHUNK_SIZE = 25


def _osrm_full_table(coords: list[tuple[float, float]]) -> tuple[list[list], list[list]]:
    """Vollständige N×N-Matrix – OHNE sources/destinations (OSRM-Default = alles)."""
    coord_str = ";".join(f"{lon},{lat}" for lat, lon in coords)
    url = f"https://router.project-osrm.org/table/v1/driving/{coord_str}"
    params = {"annotations": "duration,distance"}
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data["durations"], data["distances"]


def _osrm_sub_table(
        sub_coords: list[tuple[float, float]],
        src_local: list[int],
        dst_local: list[int],
) -> tuple[list[list], list[list]]:
    """
    Teilmatrix-Request mit expliziten sources/destinations.
    Dimension Rückgabe: len(src_local) × len(dst_local).
    """
    coord_str = ";".join(f"{lon},{lat}" for lat, lon in sub_coords)
    url = f"https://router.project-osrm.org/table/v1/driving/{coord_str}"
    params = {
        "annotations": "duration,distance",
        "sources":      ",".join(map(str, src_local)),
        "destinations": ",".join(map(str, dst_local)),
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data["durations"], data["distances"]


def build_matrices_osrm(coords: list[tuple[float, float]]) -> tuple[list[list[int]], list[list[int]]]:
    n = len(coords)

    # ── Schritt 1: Koordinaten deduplizieren ──────────────────────────
    # Viele Einsender haben identische lat/lon (gleicher Standort, mehrere Abholungen).
    # Wir arbeiten nur mit einzigartigen Koordinaten und expandieren danach.
    unique_coords: list[tuple[float, float]] = []
    coord_to_uid:  dict[tuple[float, float], int] = {}
    node_to_uid:   list[int] = []

    for coord in coords:
        if coord not in coord_to_uid:
            coord_to_uid[coord] = len(unique_coords)
            unique_coords.append(coord)
        node_to_uid.append(coord_to_uid[coord])

    m = len(unique_coords)

    # ── Schritt 2: Matrix für einzigartige Koordinaten berechnen ──────
    if m <= _OSRM_CHUNK_SIZE:
        # Kleiner Input: ein einziger Request ohne sources/destinations
        dur_raw, dist_raw = _osrm_full_table(unique_coords)
        uid_time: list[list[int]] = [[0 if d is None else int(round(d / 60)) for d in row] for row in dur_raw]
        uid_dist: list[list[int]] = [[0 if d is None else int(round(d))       for d in row] for row in dist_raw]
    else:
        # Großer Input: Block-Chunking auf den einzigartigen Koordinaten.
        # Off-diagonal-Blöcke enthalten max. 2 × CHUNK_SIZE Coords in der URL.
        uid_time = [[0] * m for _ in range(m)]
        uid_dist = [[0] * m for _ in range(m)]

        chunks = [list(range(i, min(i + _OSRM_CHUNK_SIZE, m))) for i in range(0, m, _OSRM_CHUNK_SIZE)]

        for src_chunk in chunks:
            for dst_chunk in chunks:
                # Lokale Koordinatenliste: nur src + dst (dedupliziert)
                seen: dict[int, int] = {}
                combined: list[int] = []
                for uid in src_chunk + dst_chunk:
                    if uid not in seen:
                        seen[uid] = len(combined)
                        combined.append(uid)

                sub_coords = [unique_coords[i] for i in combined]
                src_local  = [seen[i] for i in src_chunk]
                dst_local  = [seen[i] for i in dst_chunk]

                # Wenn src + dst alle Coords abdecken → kein sources/destinations (→ 400)
                full_range = list(range(len(sub_coords)))
                if src_local == full_range and dst_local == full_range:
                    dur_raw, dist_raw = _osrm_full_table(sub_coords)
                else:
                    dur_raw, dist_raw = _osrm_sub_table(sub_coords, src_local, dst_local)

                for i, src_uid in enumerate(src_chunk):
                    for j, dst_uid in enumerate(dst_chunk):
                        d  = dur_raw[i][j]
                        dm = dist_raw[i][j]
                        uid_time[src_uid][dst_uid] = 0 if d  is None else int(round(d  / 60))
                        uid_dist[src_uid][dst_uid] = 0 if dm is None else int(round(dm))

    # ── Schritt 3: Auf vollständige Node-Matrix expandieren ───────────
    time_matrix_min = [[uid_time[node_to_uid[i]][node_to_uid[j]] for j in range(n)] for i in range(n)]
    dist_matrix_m   = [[uid_dist[node_to_uid[i]][node_to_uid[j]] for j in range(n)] for i in range(n)]

    return time_matrix_min, dist_matrix_m


def build_matrices_google_routes(coords: list[tuple[float, float]], api_key: str) -> tuple[list[list[int]], list[list[int]]]:
    endpoint = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"

    origins      = [{"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lon}}}} for lat, lon in coords]
    destinations = [{"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lon}}}} for lat, lon in coords]

    body    = {"origins": origins, "destinations": destinations, "travelMode": "DRIVE"}
    headers = {
        "Content-Type":   "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,status",
    }

    r = requests.post(endpoint, headers=headers, data=json.dumps(body), timeout=120)
    r.raise_for_status()
    elements = r.json()

    n = len(coords)
    time_matrix_min = [[0] * n for _ in range(n)]
    dist_matrix_m   = [[0] * n for _ in range(n)]

    for el in elements:
        oi     = el.get("originIndex")
        di     = el.get("destinationIndex")
        status = el.get("status", {})
        code   = status.get("code", 0)

        if code != 0:
            time_matrix_min[oi][di] = 10**6
            dist_matrix_m  [oi][di] = 10**9
            continue

        dur     = el.get("duration")  # oft "123s"
        seconds = int(float(dur[:-1])) if isinstance(dur, str) and dur.endswith("s") else int(float(dur or 0))
        time_matrix_min[oi][di] = int(round(seconds / 60))
        dist_matrix_m  [oi][di] = int(el.get("distanceMeters", 0))

    return time_matrix_min, dist_matrix_m


def build_matrices(coords: list[tuple[float, float]]) -> tuple[list[list[int]], list[list[int]]]:
    provider = os.getenv("MATRIX_PROVIDER", "OSRM").upper()
    if provider == "GOOGLE":
        api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            raise RuntimeError("Setze GOOGLE_MAPS_API_KEY als Umgebungsvariable.")
        return build_matrices_google_routes(coords, api_key)
    return build_matrices_osrm(coords)
