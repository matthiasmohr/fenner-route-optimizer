from __future__ import annotations
from dataclasses import dataclass
from datetime import date



@dataclass
class DepotConfig:
    lat: float
    lon: float

    # 1..3 mögliche Einliefer-/Depot-Fenster
    depot_1_von: str
    depot_1_bis: str
    depot_2_von: str | None = None
    depot_2_bis: str | None = None
    depot_3_von: str | None = None
    depot_3_bis: str | None = None


@dataclass
class SolveConfig:
    # Anzahl Fahrer / Touren
    num_vehicles: int = 6

    # Wenn Excel nur "HH:MM" hat, wird es an reference_date gehängt
    reference_date: date = date.today()

    # Servicezeit je Abholung
    default_service_min: int = 5

    # Erlaubte Wartezeit (zu früh ankommen -> warten bis Zeitfenster öffnet)
    max_wait_min: int = 240

    # Harte Maximaldauer pro Route in Minuten
    max_route_duration_min: int = 240
