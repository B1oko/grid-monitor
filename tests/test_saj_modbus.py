import json
from pathlib import Path

import pytest

from app.drivers.registry import get_driver_class, list_drivers
from app.drivers.saj.h2 import (
    LIVE_REGISTER_COUNT,
    SERIAL_NUMBER_REGISTER_COUNT,
    decode_battery_status_registers,
    decode_live_registers,
    decode_serial_number,
    reading_from_registers,
)

FIXTURE = Path(__file__).parent / "fixtures" / "drivers" / "saj-h2.json"


def registers_from_modbus_response(hex_response: str) -> list[int]:
    data = bytes.fromhex(hex_response)
    payload = data[9:]
    return [int.from_bytes(payload[i : i + 2], "big") for i in range(0, len(payload), 2)]


def test_saj_h2_driver_is_registered() -> None:
    ids = {meta.id for meta in list_drivers()}
    assert "saj-h2" in ids
    assert get_driver_class("saj-h2").meta.manufacturer == "SAJ"


def test_decode_live_registers_from_golden_file() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    registers = registers_from_modbus_response(payload["live_response_hex"])
    decoded = decode_live_registers(registers)
    reading = reading_from_registers(registers, payload["battery_registers"])

    assert len(registers) == LIVE_REGISTER_COUNT
    assert decoded["load_power_w"] == 1682
    assert decoded["pv_power_w"] == 1181
    expected = payload["expected"]
    assert reading.pv_power_w == expected["pv_power_w"]
    assert reading.battery_power_w == expected["battery_power_w"]
    assert reading.grid_power_w == expected["grid_power_w"]
    assert reading.load_power_w == expected["load_power_w"]
    assert reading.inverter_power_w == expected["inverter_power_w"]
    assert reading.battery_soc_pct == expected["battery_soc_pct"]
    assert reading.battery_temp_c == expected["battery_temp_c"]
    assert reading.extra["direction_pv"] == 1


def test_decode_live_registers_rejects_short_response() -> None:
    with pytest.raises(ValueError, match="Expected 25 registers"):
        decode_live_registers([0] * 24)


def test_decode_battery_status_registers() -> None:
    decoded = decode_battery_status_registers([251, 5367])
    assert decoded["battery_temp_c"] == 25.1
    assert decoded["battery_soc_pct"] == 53.67


def test_decode_battery_status_registers_rejects_short_response() -> None:
    with pytest.raises(ValueError, match="Expected 2 registers"):
        decode_battery_status_registers([0])


def _ascii_registers(text: str) -> list[int]:
    raw = text.encode("ascii").ljust(SERIAL_NUMBER_REGISTER_COUNT * 2, b"\x00")
    return [int.from_bytes(raw[i : i + 2], "big") for i in range(0, len(raw), 2)]


def test_decode_serial_number() -> None:
    assert decode_serial_number(_ascii_registers("H2S30K2235001234")) == "H2S30K2235001234"
    assert decode_serial_number(_ascii_registers("ABC123   ")) == "ABC123"


def test_decode_serial_number_without_text() -> None:
    assert decode_serial_number([0] * SERIAL_NUMBER_REGISTER_COUNT) is None
    assert decode_serial_number([0xFFFF] * SERIAL_NUMBER_REGISTER_COUNT) is None


def test_decode_serial_number_rejects_short_response() -> None:
    with pytest.raises(ValueError, match="Expected 10 registers"):
        decode_serial_number([0] * 9)
