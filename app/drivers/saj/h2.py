from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from app.drivers.base import DriverMeta, InverterDriver, InverterReading
from app.drivers.registry import register_driver
from app.drivers.transports.modbus_tcp import ModbusTcpTransport

LIVE_START_ADDRESS = 16533
LIVE_REGISTER_COUNT = 25
BATTERY_STATUS_START_ADDRESS = 16494
BATTERY_STATUS_REGISTER_COUNT = 2
# Device information block (0x8F00): type, subtype, protocol version, then the
# serial number as 20 ASCII characters.
SERIAL_NUMBER_START_ADDRESS = 0x8F03
SERIAL_NUMBER_REGISTER_COUNT = 10

FIELD_MAP: tuple[tuple[str, int, str], ...] = (
    ("direction_pv", 0, "u16"),
    ("direction_battery", 1, "i16"),
    ("direction_grid", 2, "i16"),
    ("direction_output", 3, "u16"),
    ("load_power_w", 11, "i16"),
    ("ct_grid_power_w", 12, "i16"),
    ("ct_grid_power_va", 13, "i16"),
    ("ct_pv_power_w", 14, "i16"),
    ("ct_pv_power_va", 15, "i16"),
    ("pv_power_w", 16, "i16"),
    ("battery_power_w", 17, "i16"),
    ("total_grid_power_w", 18, "i16"),
    ("total_grid_power_va", 19, "i16"),
    ("inverter_power_w", 20, "i16"),
    ("inverter_power_va", 21, "i16"),
    ("backup_load_power_w", 22, "u16"),
    ("backup_load_power_va", 23, "u16"),
    ("grid_power_w", 24, "i16"),
)

CANONICAL_FIELDS = {
    "pv_power_w",
    "battery_power_w",
    "grid_power_w",
    "load_power_w",
    "inverter_power_w",
}


def _to_i16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def decode_live_registers(
    registers: list[int], *, include_raw_registers: bool = False
) -> dict[str, Any]:
    if len(registers) < LIVE_REGISTER_COUNT:
        raise ValueError(f"Expected {LIVE_REGISTER_COUNT} registers, got {len(registers)}")

    decoded: dict[str, Any] = {}
    for name, index, kind in FIELD_MAP:
        raw = registers[index]
        decoded[name] = _to_i16(raw) if kind == "i16" else raw

    if include_raw_registers:
        decoded["raw_registers"] = registers[:LIVE_REGISTER_COUNT]
    return decoded


def decode_battery_status_registers(registers: list[int]) -> dict[str, Any]:
    if len(registers) < BATTERY_STATUS_REGISTER_COUNT:
        raise ValueError(
            f"Expected {BATTERY_STATUS_REGISTER_COUNT} registers, got {len(registers)}"
        )
    return {
        "battery_temp_c": round(_to_i16(registers[0]) * 0.1, 1),
        "battery_soc_pct": round(registers[1] * 0.01, 2),
    }


def decode_serial_number(registers: list[int]) -> str | None:
    if len(registers) < SERIAL_NUMBER_REGISTER_COUNT:
        raise ValueError(f"Expected {SERIAL_NUMBER_REGISTER_COUNT} registers, got {len(registers)}")
    raw = b"".join(value.to_bytes(2, "big") for value in registers[:SERIAL_NUMBER_REGISTER_COUNT])
    try:
        text = raw.split(b"\x00", 1)[0].decode("ascii").strip()
    except UnicodeDecodeError:
        return None
    return text if text and text.isprintable() else None


def reading_from_registers(
    live_registers: list[int],
    battery_registers: list[int],
    *,
    include_raw_registers: bool = False,
    latency_ms: float | None = None,
) -> InverterReading:
    decoded = decode_live_registers(live_registers, include_raw_registers=include_raw_registers)
    decoded.update(decode_battery_status_registers(battery_registers))
    extra = {key: value for key, value in decoded.items() if key not in CANONICAL_FIELDS}
    extra.pop("battery_soc_pct", None)
    extra.pop("battery_temp_c", None)
    return InverterReading(
        pv_power_w=decoded.get("pv_power_w"),
        battery_power_w=decoded.get("battery_power_w"),
        grid_power_w=decoded.get("grid_power_w"),
        load_power_w=decoded.get("load_power_w"),
        inverter_power_w=decoded.get("inverter_power_w"),
        battery_soc_pct=decoded.get("battery_soc_pct"),
        battery_temp_c=decoded.get("battery_temp_c"),
        timestamp=datetime.now(UTC),
        latency_ms=latency_ms,
        extra=extra,
    )


@register_driver
class SajH2Driver(InverterDriver):
    meta = DriverMeta(
        id="saj-h2",
        name="SAJ H2 / AIO3",
        manufacturer="SAJ",
        protocol="modbus-tcp",
        default_port=502,
        default_unit_id=1,
    )

    def __init__(
        self,
        *,
        host: str,
        port: int = 502,
        unit_id: int = 1,
        timeout_seconds: float = 3.0,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            host=host,
            port=port,
            unit_id=unit_id,
            timeout_seconds=timeout_seconds,
            extra=extra,
        )
        self._transport = ModbusTcpTransport(host, port, unit_id, timeout_seconds)
        self._include_raw = bool((extra or {}).get("include_raw_registers"))

    async def read(self) -> InverterReading:
        started = time.perf_counter()
        live = await self._transport.read_holding_registers(LIVE_START_ADDRESS, LIVE_REGISTER_COUNT)
        battery = await self._transport.read_holding_registers(
            BATTERY_STATUS_START_ADDRESS, BATTERY_STATUS_REGISTER_COUNT
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return reading_from_registers(
            live,
            battery,
            include_raw_registers=self._include_raw,
            latency_ms=latency_ms,
        )

    async def identify(self) -> str | None:
        registers = await self._transport.read_holding_registers(
            SERIAL_NUMBER_START_ADDRESS, SERIAL_NUMBER_REGISTER_COUNT
        )
        return decode_serial_number(registers)

    async def close(self) -> None:
        await self._transport.close()

    @classmethod
    async def probe(
        cls,
        host: str,
        *,
        port: int = 502,
        unit_id: int = 1,
        timeout: float = 2.0,
    ) -> bool:
        transport = ModbusTcpTransport(host, port, unit_id, timeout)
        try:
            registers = await transport.read_holding_registers(
                LIVE_START_ADDRESS, LIVE_REGISTER_COUNT
            )
            return len(registers) >= LIVE_REGISTER_COUNT
        except Exception:
            return False
        finally:
            await transport.close()
