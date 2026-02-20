from __future__ import annotations

import folium
from datetime import datetime, timedelta
from typing import Optional, Union

# 12 gut unterscheidbare Farben für die Touren
ROUTE_COLORS = [
    "#e6194b",  # Rot
    "#3cb44b",  # Grün
    "#4363d8",  # Blau
    "#f58231",  # Orange
    "#911eb4",  # Lila
    "#42d4f4",  # Cyan
    "#f032e6",  # Magenta
    "#bfef45",  # Gelbgrün
    "#9A6324",  # Braun
    "#469990",  # Teal
    "#800000",  # Dunkelrot
    "#000075",  # Dunkelblau
]


def export_routes_map_html(
        routes: list[list[tuple]],
        labels: list[str],
        coords: list[tuple[float, float]],
        node_senders: Optional[list[str]] = None,
        node_addresses: Optional[list[str]] = None,
        time_origin: Optional[Union[str, datetime]] = None,
        time_format: str = "%H:%M",
) -> folium.Map:
    """
    Erzeugt eine interaktive Folium-Karte und gibt das Map-Objekt zurück.

    Für Streamlit:    st.components.v1.html(m._repr_html_(), height=600)
    Für CLI/Datei:    m.save("solution_map.html")

    - Jede Route bekommt eine eigene Farbe aus ROUTE_COLORS.
    - Tooltip zeigt: Uhrzeit | Einsender | Adresse.
    - Popup zeigt alle Details.
    - `time_origin`: Basiszeit für tmin-Umrechnung (Minuten ab 00:00 dieses Tags).
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

    # Depot-Marker (immer schwarz/standard)
    folium.Marker(
        [depot_lat, depot_lon],
        popup="<b>LABOR (Depot)</b>",
        tooltip="🏥 LABOR",
        icon=folium.Icon(color="black", icon="home", prefix="fa"),
    ).add_to(m)

    for r_idx, route in enumerate(routes, start=1):
        color = ROUTE_COLORS[(r_idx - 1) % len(ROUTE_COLORS)]
        latlons = []

        for step in route:
            node  = step[0]
            tmin  = step[1] if len(step) > 1 else None
            slack = step[2] if len(step) > 2 else 0

            lat, lon = coords[node]
            latlons.append((lat, lon))

            # Hilfsdaten
            sender  = (node_senders[node]   if node_senders   and node < len(node_senders)   else None) or labels[node]
            address = (node_addresses[node] if node_addresses and node < len(node_addresses) else None) or ""

            # Ankunftszeit als Uhrzeit
            if tmin is not None:
                real_dt    = origin + timedelta(minutes=float(tmin))
                time_str   = real_dt.strftime(time_format)
            else:
                time_str = "n/a"

            # ── Tooltip (erscheint beim Hover, kurz & knapp) ──────────────
            if node == 0:
                tooltip_html = f"🏥 LABOR | {time_str}"
            else:
                tooltip_html = (
                    f"<b>Route {r_idx} | {time_str}</b><br>"
                    f"{sender}<br>"
                    f"<i>{address}</i>"
                )

            # ── Popup (erscheint beim Klick, ausführlich) ─────────────────
            popup_lines = [f"<b>Route {r_idx}: {labels[node]}</b>"]
            if node != 0:
                popup_lines.append(f"Einsender: {sender}")
                if address:
                    popup_lines.append(f"Adresse: {address}")
            popup_lines.append(f"Ankunft: {time_str}")
            if slack:
                popup_lines.append(f"Wartezeit ≈ {int(slack)} min")

            popup_html = "<br>".join(popup_lines)

            # Depot-Stopp am Ende der Route: kleiner, durchsichtiger
            if node == 0:
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=4,
                    color=color,
                    fill=True,
                    fill_color=color,
                    fill_opacity=0.3,
                    popup=folium.Popup(popup_html, max_width=300),
                    tooltip=folium.Tooltip(tooltip_html, sticky=True),
                ).add_to(m)
            else:
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=7,
                    color=color,
                    fill=True,
                    fill_color=color,
                    fill_opacity=0.85,
                    popup=folium.Popup(popup_html, max_width=300),
                    tooltip=folium.Tooltip(tooltip_html, sticky=True),
                ).add_to(m)

        # Linie der Route in der gleichen Farbe
        if len(latlons) >= 2:
            folium.PolyLine(
                locations=latlons,
                color=color,
                weight=3,
                opacity=0.75,
                tooltip=f"Route {r_idx}",
            ).add_to(m)

    return m
