from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class DriverMeta:
    id: str
    name: str
    manufacturer: str
    protocol: str
    default_port: int = 502
    default_unit_id: int = 1


class InverterReading(BaseModel):
    """Canonical live sample, independent of the inverter manufacturer."""

    pv_power_w: int | None = None
    battery_power_w: int | None = None
    grid_power_w: int | None = None
    load_power_w: int | None = None
    inverter_power_w: int | None = None
    battery_soc_pct: float | None = None
    battery_temp_c: float | None = None
    connected: bool = True
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    latency_ms: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class InverterDriver(ABC):
    meta: ClassVar[DriverMeta]

    def __init__(
        self,
        *,
        host: str,
        port: int = 502,
        unit_id: int = 1,
        timeout_seconds: float = 3.0,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout_seconds = timeout_seconds
        self.extra = extra or {}

    @abstractmethod
    async def read(self) -> InverterReading:
        """Return a live reading from the inverter."""

    async def identify(self) -> str | None:
        """Return a hardware id that survives IP changes, such as the serial number.

        Grid Monitor uses it to find the inverter again when it gets a new address.
        Drivers for models without one keep this default.
        """
        return None

    async def close(self) -> None:
        return None

    @classmethod
    @abstractmethod
    async def probe(
        cls,
        host: str,
        *,
        port: int = 502,
        unit_id: int = 1,
        timeout: float = 2.0,
    ) -> bool:
        """Return True if this driver believes `host` is a compatible inverter."""
