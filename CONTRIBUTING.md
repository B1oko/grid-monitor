# Contributing to Grid Monitor

Thanks for helping. This project is in early `0.x` development, so APIs and
the database schema may still change.

## Development setup

```bash
uv sync --all-groups
cp .env.example .env
uv run uvicorn app.main:app --reload
```

Run tests and linters:

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

## Branches

- `main` is the stable branch. Every merge publishes the `edge` image, and a new
  version also publishes a release (see below).
- Work on `feature/<name>` branches created from `main`, and open the PR against `main`.

## Pull requests

- Keep changes focused. A new inverter driver should not mix with unrelated UI work.
- Add or update tests for behavior you change.
- Run `pytest` and `ruff` before opening the PR.
- Raise the version and add its `CHANGELOG.md` section, as described in
  [AGENTS.md](AGENTS.md#versioning). CI fails if the version is not higher than
  on `main`.
- New or changed UI text must be added to every catalog in `app/i18n/locales/`.
  See the translation rules in [AGENTS.md](AGENTS.md#translations).

## How to add a new inverter driver

Drivers live under `app/drivers/<manufacturer>/`. Each driver is a Python class
that subclasses `InverterDriver` and is registered with `@register_driver`.

### 1. Implement the class

```python
from app.drivers.base import DriverMeta, InverterDriver, InverterReading
from app.drivers.registry import register_driver
from app.drivers.transports.modbus_tcp import ModbusTcpTransport


@register_driver
class AcmeX1Driver(InverterDriver):
    meta = DriverMeta(
        id="acme-x1",
        name="Acme X1",
        manufacturer="Acme",
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
        extra: dict | None = None,
    ) -> None:
        self._transport = ModbusTcpTransport(host, port, unit_id, timeout_seconds)

    async def read(self) -> InverterReading:
        registers = await self._transport.read_holding_registers(address=..., count=...)
        return InverterReading(pv_power_w=..., extra={...})

    async def identify(self) -> str | None:
        registers = await self._transport.read_holding_registers(address=..., count=...)
        return ...  # serial number decoded from the registers

    async def close(self) -> None:
        await self._transport.close()

    @classmethod
    async def probe(
        cls, host: str, port: int = 502, unit_id: int = 1, timeout: float = 2.0
    ) -> bool:
        transport = ModbusTcpTransport(host, port, unit_id, timeout)
        try:
            await transport.read_holding_registers(address=..., count=...)
            return True
        except Exception:
            return False
        finally:
            await transport.close()
```

Map manufacturer-specific fields into the canonical `InverterReading` model
(`pv_power_w`, `battery_power_w`, `grid_power_w`, `load_power_w`,
`inverter_power_w`, `battery_soc_pct`, `battery_temp_c`). Put anything else
in `extra`.

Implement `identify()` if the model reports a serial number (or another id
that does not change). Grid Monitor stores it and uses it to find the inverter
again when its IP address changes. Without it, users have to type the new
address themselves.

### 2. Add a golden-file test

Commit a register dump under `tests/fixtures/drivers/<driver-id>.json`:

```json
{
  "driver_id": "acme-x1",
  "description": "Daytime sample from a real unit",
  "holding_registers": {
    "1000": [0, 1181, 501, 0, 1682]
  },
  "expected": {
    "pv_power_w": 1181,
    "battery_power_w": 501,
    "grid_power_w": 0,
    "load_power_w": 1682
  }
}
```

Decode that dump in a unit test so the mapping cannot regress without hardware.

If you do not have a unit in front of you, open an issue with the
"New inverter support" template and attach:

- Brand, model, and firmware
- Protocol (Modbus TCP port, unit/slave id, or HTTP API)
- A register dump or a short packet capture of a live poll
- Links to a public protocol document if one exists

### 3. Document it

Add a row to the supported-inverters table in `README.md`.

The driver registry imports every module under `app/drivers/` except `base`,
`registry`, and `transports`, so dropping a new module in is enough — no
central list to edit.
