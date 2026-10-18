from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.drivers.base import DriverMeta, InverterDriver, InverterReading
from app.drivers.registry import register_driver
from app.services.discovery import (
    DiscoveryStatus,
    InverterDiscovery,
    get_local_subnet,
    iter_subnet_hosts,
    probe_drivers,
    subnet_around,
)


def test_iter_subnet_hosts_returns_usable_hosts() -> None:
    hosts = iter_subnet_hosts("192.168.1.0/30")
    assert hosts == ["192.168.1.1", "192.168.1.2"]


def test_get_local_subnet_uses_prefix_length() -> None:
    with patch("app.services.discovery.socket.socket") as socket_cls:
        sock = MagicMock()
        sock.getsockname.return_value = ("10.0.0.15", 54321)
        socket_cls.return_value.__enter__.return_value = sock
        assert get_local_subnet(24) == "10.0.0.0/24"


@pytest.mark.asyncio
async def test_probe_drivers_returns_matching_driver() -> None:
    @register_driver
    class ProbeDriver(InverterDriver):
        meta = DriverMeta(id="probe-test", name="Probe", manufacturer="Test", protocol="test")

        async def read(self) -> InverterReading:
            return InverterReading()

        @classmethod
        async def probe(
            cls, host: str, *, port: int = 502, unit_id: int = 1, timeout: float = 2.0
        ) -> bool:
            return host.endswith(".20")

    candidates = await probe_drivers("192.168.1.20")
    ids = {item.driver_id for item in candidates}
    assert "probe-test" in ids
    assert not await ProbeDriver.probe("192.168.1.10")


@pytest.mark.asyncio
async def test_discover_inverter_returns_found_candidate() -> None:
    discovery = InverterDiscovery(concurrency=2)

    async def fake_probe(host: str, *, port: int = 502, timeout: float = 2.0):
        if host == "192.168.1.20":
            from app.services.discovery import DiscoveryCandidate

            return [DiscoveryCandidate(host=host, driver_id="saj-h2", latency_ms=8.5, port=port)]
        return []

    with (
        patch.object(
            discovery, "_scan_open_ports", AsyncMock(return_value=["192.168.1.10", "192.168.1.20"])
        ),
        patch("app.services.discovery.probe_drivers", side_effect=fake_probe),
        patch("app.services.discovery.get_local_subnet", return_value="192.168.1.0/24"),
    ):
        result = await discovery.discover()

    assert result.status == DiscoveryStatus.FOUND
    assert result.host == "192.168.1.20"
    assert result.driver_id == "saj-h2"
    assert result.candidates[0].driver_id == "saj-h2"


@pytest.mark.asyncio
async def test_discover_inverter_returns_not_found() -> None:
    discovery = InverterDiscovery(concurrency=2)

    with (
        patch.object(discovery, "_scan_open_ports", AsyncMock(return_value=["192.168.1.10"])),
        patch("app.services.discovery.probe_drivers", AsyncMock(return_value=[])),
        patch("app.services.discovery.get_local_subnet", return_value="192.168.1.0/24"),
    ):
        result = await discovery.discover()

    assert result.status == DiscoveryStatus.NOT_FOUND
    assert result.host is None


def test_subnet_around_host() -> None:
    assert subnet_around("192.168.1.77", 24) == "192.168.1.0/24"
    assert subnet_around("inverter.lan", 24) is None


def _serial_driver(driver_id: str, serials: dict[str, str]) -> type[InverterDriver]:
    @register_driver
    class SerialDriver(InverterDriver):
        meta = DriverMeta(id=driver_id, name="Serial", manufacturer="Test", protocol="test")

        async def read(self) -> InverterReading:
            return InverterReading()

        async def identify(self) -> str | None:
            if self.host not in serials:
                raise ConnectionError("no answer")
            return serials[self.host]

        @classmethod
        async def probe(
            cls, host: str, *, port: int = 502, unit_id: int = 1, timeout: float = 2.0
        ) -> bool:
            return host in serials

    return SerialDriver


@pytest.mark.asyncio
async def test_probe_drivers_reads_serial_number() -> None:
    _serial_driver("serial-test", {"192.168.1.20": "SN-20"})
    candidates = await probe_drivers("192.168.1.20")
    found = next(item for item in candidates if item.driver_id == "serial-test")
    assert found.serial_number == "SN-20"
    assert found.to_dict()["serial_number"] == "SN-20"


@pytest.mark.asyncio
async def test_locate_finds_inverter_by_serial_number() -> None:
    _serial_driver("locate-test", {"192.168.1.30": "SN-OTHER", "192.168.1.31": "SN-ROOF"})
    discovery = InverterDiscovery()
    scan = AsyncMock(return_value=["192.168.1.5", "192.168.1.30", "192.168.1.31"])

    with patch.object(discovery, "_scan_open_ports", scan):
        host = await discovery.locate(
            driver_id="locate-test",
            serial_number="SN-ROOF",
            port=1502,
            unit_id=1,
            near="192.168.1.10",
        )
        missing = await discovery.locate(
            driver_id="locate-test",
            serial_number="SN-GONE",
            port=1502,
            unit_id=1,
            near="192.168.1.10",
        )

    assert host == "192.168.1.31"
    assert missing is None
    scan.assert_awaited_with("192.168.1.0/24", 1502)


@pytest.mark.asyncio
async def test_locate_skips_host_names() -> None:
    discovery = InverterDiscovery()
    scan = AsyncMock(return_value=[])
    with patch.object(discovery, "_scan_open_ports", scan):
        host = await discovery.locate(
            driver_id="saj-h2", serial_number="SN", port=502, unit_id=1, near="inverter.lan"
        )
    assert host is None
    scan.assert_not_awaited()
