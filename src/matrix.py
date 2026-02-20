from __future__ import annotations
import os
import json
import requests


def build_matrices_osrm(coords: list[tuple[float, float]]) -> tuple[list[list[int]], list[list[int]]]:
    coord_str = ";".join([f"{lon},{lat}" for (lat, lon) in coords])
    url = f"https://router.project-osrm.org/table/v1/driving/{coord_str}"
    params = {"annotations": "duration,distance"}

    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()

    durations = data["durations"]  # seconds
    distances = data["distances"]  # meters

    time_matrix_min = [[0 if d is None else int(round(d / 60)) for d in row] for row in durations]
    dist_matrix_m = [[0 if d is None else int(round(d)) for d in row] for row in distances]
    return time_matrix_min, dist_matrix_m


def build_matrices_google_routes(coords: list[tuple[float, float]], api_key: str) -> tuple[list[list[int]], list[list[int]]]:
    endpoint = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"

    origins = [{"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lon}}}} for lat, lon in coords]
    destinations = [{"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lon}}}} for lat, lon in coords]

    body = {"origins": origins, "destinations": destinations, "travelMode": "DRIVE"}
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,status",
    }

    r = requests.post(endpoint, headers=headers, data=json.dumps(body), timeout=120)
    r.raise_for_status()
    elements = r.json()

    n = len(coords)
    time_matrix_min = [[0] * n for _ in range(n)]
    dist_matrix_m = [[0] * n for _ in range(n)]

    for el in elements:
        oi = el.get("originIndex")
        di = el.get("destinationIndex")
        status = el.get("status", {})
        code = status.get("code", 0)

        if code != 0:
            time_matrix_min[oi][di] = 10**6
            dist_matrix_m[oi][di] = 10**9
            continue

        dur = el.get("duration")  # oft "123s"
        seconds = int(float(dur[:-1])) if isinstance(dur, str) and dur.endswith("s") else int(float(dur or 0))
        time_matrix_min[oi][di] = int(round(seconds / 60))
        dist_matrix_m[oi][di] = int(el.get("distanceMeters", 0))

    return time_matrix_min, dist_matrix_m


def build_matrices(coords: list[tuple[float, float]]) -> tuple[list[list[int]], list[list[int]]]:
    provider = os.getenv("MATRIX_PROVIDER", "OSRM").upper()
    if provider == "GOOGLE":
        api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            raise RuntimeError("Setze GOOGLE_MAPS_API_KEY als Umgebungsvariable.")
        return build_matrices_google_routes(coords, api_key)
    return build_matrices_osrm(coords)
