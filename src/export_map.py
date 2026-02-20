from __future__ import annotations

import folium
from datetime import datetime, timedelta
from typing import Optional, Union


def export_routes_map_html(
        routes: list[list[tuple]],
        labels: list[str],
        coords: list[tuple[float, float]],
        senders: Optional[list[str]] = None,
        addresses: Optional[list[str]] = None,
        time_origin: Optional[Union[str, datetime]] = None,
        time_format: str = "%Y-%m-%d %H:%M",
) -> folium.Map:
    """
    Erzeugt eine interaktive Folium-Karte und gibt das Map-Objekt zurück.

    Für Streamlit:    st.components.v1.html(m._repr_html_(), height=600)
    Für CLI/Datei:    m.save("solution_map.html")

    Optional: `senders` und `addresses` (parallel zu `labels`) werden im Popup angezeigt.
    `time_origin` kann ein datetime oder ISO-String sein; wenn None -> heutiges 00:00.
    `tmin` in den Route-Steps wird als Minuten seit `time_origin` als echte Uhrzeit angezeigt.
    """
    if time_origin is None:
        origin = datetime.combine(datetime.today(), datetime.min.time())
    elif isinstance(time_origin, str):
        try:
            origin = datetime.fromisoformat(time_origin)
        except ValueError:
            origin = datetime.combine(datetime.today(), datetime.min.time())
    else:
        origin = time_origin

    depot_lat, depot_lon = coords[0]
    m = folium.Map(location=[depot_lat, depot_lon], zoom_start=10)

    folium.Marker(
        [depot_lat, depot_lon],
        popup="LABOR (Depot)",
        tooltip="LABOR",
        icon=folium.Icon(),
    ).add_to(m)

    for r_idx, route in enumerate(routes, start=1):
        latlons = []

        for step in route:
            node = step[0]
            tmin = step[1] if len(step) > 1 else None
            slack = step[2] if len(step) > 2 else 0

            lat, lon = coords[node]
            latlons.append((lat, lon))

            sender = senders[node] if (senders and node < len(senders)) else None
            address = addresses[node] if (addresses and node < len(addresses)) else None

            popup_parts = [f"Route {r_idx}: {labels[node]}"]
            if sender:
                popup_parts.append(f"Name: {sender}")
            if address:
                popup_parts.append(f"Adresse: {address}")

            if tmin is not None:
                real_dt = origin + timedelta(minutes=float(tmin))
                popup_parts.append(f"Ankunft: {real_dt.strftime(time_format)}")
            else:
                popup_parts.append("Ankunft: n/a")

            if slack:
                popup_parts.append(f"Wartezeit ≈ {int(slack)} min")

            folium.CircleMarker(
                location=[lat, lon],
                radius=5,
                popup="<br>".join(popup_parts),
                tooltip=f"R{r_idx}: {labels[node]}",
            ).add_to(m)

        folium.PolyLine(
            locations=latlons,
            weight=4,
            opacity=0.8,
            tooltip=f"Route {r_idx}",
        ).add_to(m)

    return m
