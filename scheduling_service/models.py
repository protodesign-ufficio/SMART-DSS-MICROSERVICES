"""
Domain models for the scheduling service.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


def parse_datetime(value: str) -> datetime:
    """Parse datetime from multiple formats."""
    fmts = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"]
    for fmt in fmts:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized datetime format: {value}")


def to_epoch_seconds(dt: datetime) -> int:
    return int(dt.timestamp())


@dataclass(frozen=True)
class Route:
    """Represents a route/percorso for scheduling."""
    route_id: str
    corsa_id: str
    corsa_name: Optional[str]
    vessel_id: str
    vessel_name: Optional[str]
    capacity: float
    origin: str
    destination: str
    start_dt: datetime
    end_dt: datetime
    consumo: float
    comfort: float
    pax_min: float
    pax_max: float

    @property
    def start_s(self) -> int:
        return to_epoch_seconds(self.start_dt)

    @property
    def end_s(self) -> int:
        return to_epoch_seconds(self.end_dt)

    @property
    def duration_s(self) -> int:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class Vessel:
    """Represents a vessel."""
    vessel_id: str
    name: str
    capacity: float
